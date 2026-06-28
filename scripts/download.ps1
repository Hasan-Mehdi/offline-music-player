# Bulk music downloader — the working free path.
#
# Client: android_vr. It returns native Opus (format 251, ~144k) with NO PO-token
# server and NO cookies, and is NOT affected by YouTube's tv-client DRM experiment
# (yt-dlp #12563) that kills the `tv` client. It IS a guest (unauthenticated) client,
# so it lives under YouTube's per-IP guest rate ceiling — the downloader paces itself
# and AUTO-BACKS-OFF (sleeps, then resumes) on a 403/rate-limit, so just leave it running.
#
# Why not throwaway-account cookies? Every cookie-capable client is a dead end:
# `tv` is DRM-locked for this session, and mweb/ios/web all demand a GVS PO token
# (needs the bgutil token server, which won't build here). android_vr ignores cookies.
#
# Resumes automatically via the download archive (data/downloaded.txt): safe to Ctrl+C
# and re-run any time — it skips everything you already have. Run it in your own terminal
# so it survives (a background task in an editor/agent session can get killed when idle):
#
#   powershell -ExecutionPolicy Bypass -File scripts\download.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\download.ps1 -InputCsv data\candidates.csv
#
param(
  [string]$InputCsv      = "data\download_queue.csv",  # diversified+interleaved; or data\candidates.csv (radio)
  [string]$Outdir        = $(if ($env:MUSIC_DIR) { $env:MUSIC_DIR } else { "music" }),
  [double]$Sleep         = 2.5,
  [double]$SleepRequests = 3.0
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # repo root (this script lives in scripts/)
$env:PYTHONUTF8 = "1"
Write-Host "Downloading $InputCsv -> $Outdir  (android_vr, Opus 251, guest+backoff)" -ForegroundColor Cyan
& ".venv\Scripts\python.exe" scripts\download_tracks.py `
  --input $InputCsv --outdir $Outdir `
  --client android_vr --sleep $Sleep --sleep-requests $SleepRequests --backoff 1800
