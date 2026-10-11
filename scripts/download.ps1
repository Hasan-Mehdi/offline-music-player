# Bulk music downloader — the working free path.
#
# Client: android_vr. It returns native Opus (format 251, ~144k) with NO PO-token
# server and NO cookies, and is NOT affected by YouTube's tv-client DRM experiment
# (yt-dlp #12563) that kills the `tv` client. It IS a guest (unauthenticated) client,
# so it lives under YouTube's per-IP guest rate ceiling — the downloader paces itself
# and AUTO-BACKS-OFF (sleeps, then resumes) on a 403/rate-limit, so just leave it running.
#
# "Sign in to confirm you're not a bot" (July 2026): usually a PER-VIDEO guest login-lock
# (official anime OPs etc.), NOT an IP flag — those tracks get the search fallback and,
# failing that, land in data\auth_required.csv for the future authenticated run. A canary
# probe detects the rare true IP-level flag and backs off as before.
#
# Why not the throwaway account's cookies? Every cookie-capable client is a dead end:
# `tv` is DRM-locked for our session, and mweb/ios/web all demand a GVS PO token
# (needs the bgutil token server, which won't build here). android_vr ignores cookies.
#
# Resumes automatically via the download archive (data/downloaded.txt): safe to Ctrl+C
# and re-run any time — it skips everything you already have. Run in YOUR OWN terminal
# so it survives (a Claude session reaps background tasks when it goes idle):
#
#   powershell -ExecutionPolicy Bypass -File scripts\download.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\download.ps1 -InputCsv data\candidates.csv
#
# AUTHENTICATED, SLOW mode (-Cookies): when the guest path is bot-checked wholesale (Oct 2026:
# even previously-downloaded videos), use a logged-in cookie export with the `web_embedded`
# client — clean Opus 251, no PO token, no DRM (confirmed 2026-07-07). android_vr cannot take
# cookies, so -Cookies switches the client. An account is easier to flag than an IP, so this
# mode paces itself: a RANDOM 15-40 s between tracks (~100/hr). Export cookies from a PRIVATE
# window and close it right after (the browser then never rotates them):
#
#   powershell -ExecutionPolicy Bypass -File scripts\download.ps1 -InputCsv data\takeout_missing.csv -Cookies auth\yt_cookies.txt
#
param(
  [string]$InputCsv      = "data\download_queue.csv",  # diversified+interleaved; or data\candidates.csv (radio)
  [string]$Outdir        = "D:\OfflineMusic",
  [double]$Sleep         = 2.5,
  [double]$SleepRequests = 3.0,
  [string]$Cookies       = "",                         # logged-in cookie export -> web_embedded, slow
  [double]$MaxSleep      = 40.0                        # -Cookies mode: random $Sleep..$MaxSleep s
)
# NOTE: do NOT add --use-cookies here. yt-dlp drops the android_vr client the moment
# cookies are present ("Skipping client android_vr since it does not support cookies")
# and falls back to web clients that all require a GVS PO token from a running bgutil
# POT server — which would break ALL downloads, not just the age-gated few. Age-gated
# tracks need a separate authenticated+POT path (see notes from Claude session 2026-06-29).
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\hasan\code\apps\offline-music-player"
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"   # live progress when stdout is redirected to a log
if ($Cookies) {
  if (-not (Test-Path $Cookies)) { throw "cookie file not found: $Cookies" }
  if (-not $PSBoundParameters.ContainsKey('Sleep')) { $Sleep = 15.0 }
  if (-not $PSBoundParameters.ContainsKey('SleepRequests')) { $SleepRequests = 4.0 }
  Write-Host "Downloading $InputCsv -> $Outdir  (web_embedded + cookies, SLOW: $Sleep-$MaxSleep s/track)" -ForegroundColor Cyan
  & ".venv\Scripts\python.exe" scripts\download_tracks.py `
    --input $InputCsv --outdir $Outdir `
    --client web_embedded --use-cookies --cookies $Cookies `
    --sleep $Sleep --max-sleep $MaxSleep --sleep-requests $SleepRequests `
    --backoff 3600 --max-cooldowns 3
  exit $LASTEXITCODE
}
Write-Host "Downloading $InputCsv -> $Outdir  (android_vr, Opus 251, guest+backoff)" -ForegroundColor Cyan
& ".venv\Scripts\python.exe" scripts\download_tracks.py `
  --input $InputCsv --outdir $Outdir `
  --client android_vr --sleep $Sleep --sleep-requests $SleepRequests --backoff 1800
