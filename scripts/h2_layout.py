"""Where each track lives on the H2's card: Music/<Letter>/<Artist>/<Title> [video_id].opus

One function shared by the pack builder (export_device_pack.py, the file strings the
device resolves) and the copier (export_h2.py), so the two can never disagree.

Rules (docs/H2_APP_PLAN.md, checked against Rockbox source):
- letter buckets keep each folder under Rockbox's 5,000-entry browser default
  (16k+ artists, 12k of them with a single track)
- FAT-safe names, no leading dots (Rockbox hides dot-files), no trailing dots/spaces
- byte budgets: artist folder <= 64 B, file name <= 120 B, whole path <= 200 B UTF-8
  (Rockbox MAX_PATH is 260 bytes including "/Music/")
- FAT is case-insensitive: artist folders are unified by casefold (first spelling
  wins) and file names get a ~N suffix on a case-only clash (video_ids are
  case-sensitive, so 'abc' and 'ABC' would otherwise collide)
"""
import base64
import hashlib
import os
import unicodedata

ARTIST_MAX = 64
NAME_MAX = 120
PATH_MAX = 200
_BAD = set('<>:"/\\|?*')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def short_id(video_id):
    """The 11-byte id the device pack stores (ids.bin) and the card file names carry.
    YouTube ids are already 11 chars; split-chapter ids ('Game Freak - Agate Village
    [sRr9aarnCc8-019]', 122 of them) get a stable hash surrogate starting with '~'
    (never a YouTube id character, so no collisions with real ids)."""
    if len(video_id) == 11:
        return video_id
    return "~" + base64.urlsafe_b64encode(hashlib.sha1(video_id.encode("utf-8")).digest()).decode()[:10]


def fat_clean(s):
    s = unicodedata.normalize("NFC", s or "")
    s = "".join("-" if c in "/\\|" else "'" if c == '"' else "_" if c in _BAD
                else " " if ord(c) < 32 else c for c in s)
    s = " ".join(s.split())
    s = s.lstrip(". ").rstrip(". ")
    if not s:
        s = "_"
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s


def trunc_utf8(s, max_bytes):
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return s
    b = b[:max_bytes]
    while b and (b[-1] & 0xC0) == 0x80:          # drop a split continuation tail
        b = b[:-1]
    if b and b[-1] >= 0xC0:                       # and a dangling lead byte
        b = b[:-1]
    return b.decode("utf-8", "ignore").rstrip(". ")


def bucket(artist):
    for ch in unicodedata.normalize("NFKD", artist or ""):
        if unicodedata.combining(ch):
            continue
        if ch.isascii() and ch.isalpha():
            return ch.upper()
        if ch.isdigit():
            return "0-9"
        if ch.isalnum():
            return "#"                            # CJK, Hangul, Cyrillic, ...
    return "#"


class Layout:
    """Assign relative paths (under Music/) in a stable order; call path() per track."""

    def __init__(self):
        self.artist_dirs = {}                     # casefold -> chosen folder name
        self.names = set()                        # casefolded relpaths already used

    def path(self, video_id, title, artist):
        a = trunc_utf8(fat_clean(artist or "Unknown artist"), ARTIST_MAX)
        a = self.artist_dirs.setdefault(a.casefold(), a)
        b = bucket(a)
        tail = f" [{video_id}].opus"
        head = f"{b}/{a}/"
        room = min(NAME_MAX, PATH_MAX - len(head.encode())) - len(tail.encode())
        t = trunc_utf8(fat_clean(title or video_id), max(8, room))
        rel = head + t + tail
        n = 2
        while rel.casefold() in self.names:
            rel = f"{head}{t} [{video_id}]~{n}.opus"
            n += 1
        self.names.add(rel.casefold())
        return rel


if __name__ == "__main__":
    L = Layout()
    for vid, t, a in [("abc", "Paradise, Paradise", "Toby Fox"),
                      ("ABC", "Paradise, Paradise", "toby fox"),
                      ("x1", "モンキー・メトロポリス", "中野正英"),
                      ("x2", ".hidden: a/b|c?", "...The Artist"),
                      ("x3", "T" * 400, "A" * 400)]:
        p = L.path(vid, t, a)
        print(len(("/Music/" + p).encode()), p)
