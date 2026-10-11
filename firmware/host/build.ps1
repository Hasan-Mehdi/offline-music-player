# Build host-side tests + simulator with zig cc (self-contained clang from the
# `ziglang` pip wheel — this machine's Visual Studio has no C++ workload, and
# no other C compiler is installed).
#
#   one-time: .venv\Scripts\python -m pip install ziglang
#   build:    powershell -File firmware\host\build.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here "..\..")
$py = Join-Path $root ".venv\Scripts\python.exe"
$build = Join-Path $here "build"
New-Item -ItemType Directory -Force $build | Out-Null

$core = Get-ChildItem (Join-Path $here "..\core\*.c") | ForEach-Object { $_.FullName }
foreach ($t in "test_pack", "test_brain", "test_engine3", "test_pyrand", "sim_autoplay") {
    & $py -m ziglang cc -O2 -std=c11 -Wall -I (Join-Path $here "..\core") `
        @core (Join-Path $here "$t.c") -o (Join-Path $build "$t.exe")
    if ($LASTEXITCODE -ne 0) { throw "build failed: $t" }
    Write-Host "built $t"
}
Write-Host "ok -> $build"
