# One-time setup for building the PScan phone app on this PC.
#
#   powershell -ExecutionPolicy Bypass -File phone\setup.ps1
#
# Creates phone\.venv with BeeWare Briefcase. Only needed on a PC where you build the APK;
# a PC that just receives scans needs pc\scripts\setup.ps1 only.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $here ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment in $venv ..."
    python -m venv $venv
}
Write-Host "Installing Briefcase and Toga ..."
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r (Join-Path $here "requirements-dev.txt")
if ($LASTEXITCODE) { throw "pip install failed" }

Write-Host ""
Write-Host "Done. Next (downloads Java + the Android SDK, about 2-3 GB, and asks you to accept Google's licenses):"
Write-Host "    powershell -ExecutionPolicy Bypass -File $here\briefcase.ps1 create android"
Write-Host "To build release APKs here, first copy phone\signing\ from the PC that has PScan's signing key."
