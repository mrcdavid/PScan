# Runs BeeWare Briefcase from this project's venv, with its Android tools (JDK + SDK)
# kept in C:\Users\Marc\dev\.briefcase instead of %LOCALAPPDATA%.
#
# Examples (run from the phone\ folder):
#   .\briefcase.ps1 dev                                  # run the app on Windows (file picker instead of camera)
#   .\briefcase.ps1 run android -d "@<device>"           # build, install and start on a USB-connected phone
#   .\briefcase.ps1 package android -p debug-apk         # make an installable APK in dist\
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:BRIEFCASE_HOME = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) ".briefcase"
New-Item -ItemType Directory -Force $env:BRIEFCASE_HOME | Out-Null
Push-Location $here
try {
    & (Join-Path $here ".venv\Scripts\briefcase.exe") @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
