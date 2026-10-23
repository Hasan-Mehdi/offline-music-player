# Build the Coda UI screenshot runner (firmware/ui + core + host platform) with zig cc.
#   powershell -File firmware\host\build_coda.ps1
#   firmware\host\build\coda_shots.exe D:\coda-h2card\.coda data\device_pack docs\h2\c
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here "..\..")
$py = Join-Path $root ".venv\Scripts\python.exe"
$build = Join-Path $here "build"
New-Item -ItemType Directory -Force $build | Out-Null
$fw = Join-Path $root "firmware"
$src = @()
$src += Get-ChildItem (Join-Path $fw "core\*.c") | ForEach-Object { $_.FullName }
$src += Get-ChildItem (Join-Path $fw "ui\*.c") | ForEach-Object { $_.FullName }
$src += (Join-Path $fw "plat\host\plat_host.c")
$src += (Join-Path $here "coda_shots.c")
& $py -m ziglang cc -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter `
    -I (Join-Path $fw "core") -I (Join-Path $fw "ui") -I (Join-Path $fw "plat\host") `
    @src -o (Join-Path $build "coda_shots.exe")
if ($LASTEXITCODE -ne 0) { throw "build failed" }
Write-Host "built coda_shots"

# brain.c's radio over a real pack (test_brain_radio.c: how a sitting's skips steer it)
$tsrc = @($src | Where-Object { $_ -notmatch "coda_shots\.c$" -and $_ -notmatch "\\ui\\app\.c$" })
$tsrc += (Join-Path $here "test_brain_radio.c")
& $py -m ziglang cc -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter `
    -I (Join-Path $fw "core") -I (Join-Path $fw "ui") -I (Join-Path $fw "plat\host") `
    @tsrc -o (Join-Path $build "test_brain_radio.exe")
if ($LASTEXITCODE -ne 0) { throw "test_brain_radio build failed" }
Write-Host "built test_brain_radio"

# the Coda OS boot animation, rendered from the device's own code
$bsrc = @((Join-Path $fw "ui\boot.c"), (Join-Path $fw "ui\gfx.c"), (Join-Path $fw "ui\fx.c"),
          (Join-Path $fw "plat\host\plat_host.c"), (Join-Path $here "boot_shots.c"))
& $py -m ziglang cc -O2 -std=c11 -Wall -Wextra -Wno-unused-parameter `
    -I (Join-Path $fw "core") -I (Join-Path $fw "ui") -I (Join-Path $fw "plat\host") `
    @bsrc -o (Join-Path $build "boot_shots.exe")
if ($LASTEXITCODE -ne 0) { throw "boot_shots build failed" }
Write-Host "built boot_shots"
