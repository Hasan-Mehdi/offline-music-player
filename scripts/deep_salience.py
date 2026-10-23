"""Deep Salience melody extraction (Bittner et al., ISMIR 2017), ported to PyTorch.

Polyphonic melody extraction for the hum index: a harmonic CQT (6 harmonics x 360 bins,
5 bins/semitone from C1) goes through a 6-layer fully-convolutional net that outputs a
per-frame salience map of the *melody* line. Unlike CREPE (monophonic pitch tracking,
which locks onto whatever is loudest — usually bass/pads in game music), this model was
trained on MedleyDB to follow the lead voice, including instrumental leads.

The weights are the authors' Keras `melody2.h5` (MIT licensed,
github.com/rabitt/ismir2017-deepsalience); `load_model` converts them on the fly, so
only h5py is needed, not Keras/TensorFlow. The HCQT is librosa's CQT ported to the GPU.
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

SR = 22050
HOP = 256                       # 86.1 frames/s, as trained
FMIN = 32.7                     # C1
BINS_PER_OCTAVE = 60
N_OCTAVES = 6
N_BINS = BINS_PER_OCTAVE * N_OCTAVES
HARMONICS = (0.5, 1, 2, 3, 4, 5)
MIDI_LO = 24.0                  # bin 0 = C1 = MIDI 24; bin k = MIDI 24 + k/5
DEFAULT_WEIGHTS = "data/models/deepsalience_melody2.h5"


class DeepSalience(nn.Module):
    def __init__(self):
        super().__init__()
        self.bn0 = nn.BatchNorm2d(6, eps=1e-3)
        self.c1 = nn.Conv2d(6, 128, 5, padding=2)
        self.bn1 = nn.BatchNorm2d(128, eps=1e-3)
        self.c2 = nn.Conv2d(128, 64, 5, padding=2)
        self.bn2 = nn.BatchNorm2d(64, eps=1e-3)
        self.c3 = nn.Conv2d(64, 64, 3, padding=1)
        self.bn3 = nn.BatchNorm2d(64, eps=1e-3)
        self.c4 = nn.Conv2d(64, 64, 3, padding=1)
        self.bn4 = nn.BatchNorm2d(64, eps=1e-3)
        self.c5 = nn.Conv2d(64, 8, (70, 3))   # 'same' padding applied by hand (even kernel)
        self.bn5 = nn.BatchNorm2d(8, eps=1e-3)
        self.c6 = nn.Conv2d(8, 1, 1)

    def forward(self, x):                      # x: (B, 6, freq, time)
        x = self.bn0(x)
        x = self.bn1(F.relu(self.c1(x)))
        x = self.bn2(F.relu(self.c2(x)))
        x = self.bn3(F.relu(self.c3(x)))
        x = self.bn4(F.relu(self.c4(x)))
        x = F.pad(x, (1, 1, 34, 35))           # TF 'same' for a 70-tall kernel: 34 before, 35 after
        x = self.bn5(F.relu(self.c5(x)))
        return torch.sigmoid(self.c6(x))[:, 0]  # (B, freq, time)


def load_model(weights=DEFAULT_WEIGHTS, device="cuda"):
    import h5py
    m = DeepSalience()
    with h5py.File(weights, "r") as f:
        def ds(group):
            g = f[group]
            g = g[list(g.keys())[0]]
            return {k.split(":")[0]: np.array(g[k]) for k in g.keys()}
        convs = {"bendy1": m.c1, "bendy2": m.c2, "smoothy1": m.c3, "smoothy2": m.c4,
                 "distribute": m.c5, "squishy": m.c6}
        for name, conv in convs.items():
            w = ds(name)
            conv.weight.data = torch.from_numpy(w["kernel"].transpose(3, 2, 0, 1).copy())
            conv.bias.data = torch.from_numpy(w["bias"])
        bns = sorted([k for k in f.keys() if k.startswith("batch_normalization")],
                     key=lambda s: int(s.rsplit("_", 1)[1]))
        for name, bn in zip(bns, [m.bn0, m.bn1, m.bn2, m.bn3, m.bn4, m.bn5]):
            w = ds(name)
            bn.weight.data = torch.from_numpy(w["gamma"])
            bn.bias.data = torch.from_numpy(w["beta"])
            bn.running_mean.data = torch.from_numpy(w["moving_mean"])
            bn.running_var.data = torch.from_numpy(w["moving_variance"])
    return m.eval().to(device)


class _HCQTPlan:
    """librosa.cqt, ported to the GPU: multirate (one 2:1 downsampling per octave) with
    librosa's own sparse FFT filter bases, built once per harmonic.

    nnAudio's CQT is a direct conv1d with every kernel padded to the 16 Hz bin's 116k taps:
    ~10^12 MACs and GBs of cuDNN workspace per track. This does the same transform as the
    training front-end (librosa) as a handful of small STFTs + matmuls - measured: mean
    |difference| from librosa 0.01 dB, ~3x faster than nnAudio, a few hundred MB of VRAM."""

    def __init__(self, device):
        import librosa
        from librosa import filters
        from librosa.core import constantq as cq
        vqt_filter_fft = getattr(cq, "__vqt_filter_fft")
        early_count = getattr(cq, "__early_downsample_count")
        self.device = device
        self.plans = []
        for h in HARMONICS:
            freqs = librosa.interval_frequencies(n_bins=N_BINS, fmin=FMIN * h, intervals="equal",
                                                 bins_per_octave=BINS_PER_OCTAVE, sort=True)
            alpha = filters._relative_bandwidth(freqs=freqs)
            _, cutoff = filters.wavelet_lengths(freqs=freqs, sr=SR, window="hann",
                                                filter_scale=1, gamma=0, alpha=alpha)
            early = early_count(SR / 2.0, cutoff, HOP, N_OCTAVES)
            sr, hop, level = SR / 2 ** early, HOP // 2 ** early, early
            base_sr = sr
            lengths, _ = filters.wavelet_lengths(freqs=freqs, sr=base_sr, window="hann",
                                                 filter_scale=1, gamma=0, alpha=alpha)
            octs = []
            for i in range(N_OCTAVES):       # top octave first, as librosa does
                sl = slice(-BINS_PER_OCTAVE, None) if i == 0 else                     slice(-BINS_PER_OCTAVE * (i + 1), -BINS_PER_OCTAVE * i)
                fb, n_fft, _ = vqt_filter_fft(sr, freqs[sl], 1, 1, 0.01, window="hann",
                                              gamma=0, dtype=np.complex64, alpha=alpha[sl])
                fb = (fb.toarray() if hasattr(fb, "toarray") else np.asarray(fb))                     * np.sqrt(base_sr / sr)
                octs.append((level, int(n_fft), int(hop),
                             torch.from_numpy(fb.astype(np.complex64)).to(device),
                             torch.ones(int(n_fft), device=device)))
                if hop % 2 == 0:
                    hop //= 2; sr /= 2.0; level += 1
            scale = torch.from_numpy((1.0 / np.sqrt(lengths)).astype(np.float32)).to(device)
            self.plans.append((octs, scale))
        self.max_level = max(o[0] for octs, _ in self.plans for o in octs)

    @torch.no_grad()
    def __call__(self, audio):
        import torchaudio
        y = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).to(self.device)
        chain = [y]      # y downsampled 2:1 per level; librosa.resample(scale=True) keeps energy
        for _ in range(self.max_level):
            chain.append(torchaudio.functional.resample(
                chain[-1], 2, 1, lowpass_filter_width=64, rolloff=0.9475937167399596,
                resampling_method="sinc_interp_kaiser", beta=14.769656459379492) * np.sqrt(2.0))
        mags = []
        for octs, scale in self.plans:
            resp = []
            for level, n_fft, hop, basis, win in octs:
                D = torch.stft(chain[level], n_fft=n_fft, hop_length=hop, window=win,
                               center=True, pad_mode="constant", return_complex=True)
                resp.append(basis @ D)
            T = min(r.shape[-1] for r in resp)
            V = torch.cat([r[:, :T] for r in resp[::-1]], 0)
            mags.append(V.abs() * scale[:, None])
        T = min(m.shape[-1] for m in mags)
        return torch.stack([m[:, :T] for m in mags])


_HCQT = {}


@torch.no_grad()
def hcqt(audio, device="cuda"):
    """(6, 360, T) log-magnitude HCQT scaled to [0,1] like the original (dB/80 + 1, ref=max)."""
    if device not in _HCQT:
        _HCQT[device] = _HCQTPlan(device)
    H = _HCQT[device](audio)
    db = 20.0 * torch.log10(torch.clamp(H, min=1e-5) / H.max())
    return torch.clamp(db, min=-80.0) / 80.0 + 1.0


CTX = 16                        # time receptive field of the net is +/-9 frames; chunk overlap


@torch.no_grad()
def _salience_t(model, audio, device="cuda", chunk=4000):
    H = hcqt(audio, device)
    T = H.shape[-1]
    # every chunk goes through the net at the same (chunk + 2*CTX) width, edges zero-padded
    Hp = F.pad(H, (CTX, chunk + CTX))
    outs = []
    with torch.autocast("cuda", dtype=torch.float16, enabled=device.startswith("cuda")):
        for t in range(0, T, chunk):        # fp16: measured 99.99% top-peak agreement with fp32
            y = model(Hp[None, :, :, t:t + chunk + 2 * CTX])[0]
            outs.append(y[:, CTX:CTX + min(chunk, T - t)].float())
    return torch.cat(outs, dim=-1)


def salience(model, audio, device="cuda", chunk=4000):
    """Melody salience map (360, T) float32 in [0,1] at 86 frames/s."""
    return _salience_t(model, audio, device, chunk).float().cpu().numpy()


PEAK_RATE = 10.0                # index frame rate (Hz)
PEAK_K = 3                      # salience peaks kept per frame
PEAK_FLOOR = 0.05


@torch.no_grad()
def melody_peaks(model, audio, device="cuda", k=PEAK_K, rate=PEAK_RATE, floor=PEAK_FLOOR):
    """Compact index form of the salience map: per 1/rate-s frame, the k strongest local
    maxima along pitch. Returns (bins int16 (T,k): MIDI = 24 + bin/5, vals uint8 (T,k):
    salience*255, 0 = no peak). Max-pooled over time so short notes survive the 86->10 Hz
    reduction."""
    M = _salience_t(model, audio, device)                 # (360, T86)
    n = max(1, int(M.shape[1] * rate * HOP / SR))
    M = F.adaptive_max_pool1d(M[None], n)[0]              # (360, n)
    up = F.pad(M[1:], (0, 0, 0, 1))
    dn = F.pad(M[:-1], (0, 0, 1, 0))
    pk = torch.where((M >= up) & (M >= dn) & (M > floor), M, torch.zeros_like(M))
    val, idx = torch.topk(pk, k, dim=0)                   # (k, n)
    idx = torch.where(val > 0, idx, torch.zeros_like(idx))
    return (np.ascontiguousarray(idx.T.to(torch.int16).cpu().numpy()),
            np.ascontiguousarray(torch.round(val.T * 255).to(torch.uint8).cpu().numpy()))


def bin_to_midi(b):
    return MIDI_LO + np.asarray(b, dtype=np.float64) / 5.0
