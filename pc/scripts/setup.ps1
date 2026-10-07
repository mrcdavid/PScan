# One-time setup for the PScan PC server.
#
#   powershell -ExecutionPolicy Bypass -File C:\Users\Marc\dev\PScan\pc\scripts\setup.ps1
#
# 1. Creates pc\.venv and installs the Python packages.
# 2. Adds Windows Firewall rules (Private and Domain networks; never Public) so the phone can reach this PC.
#    This part asks for administrator rights. Skip it with -SkipFirewall.
param([switch]$SkipFirewall)

$ErrorActionPreference = "Stop"
$pc = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $pc ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment in $venv ..."
    python -m venv $venv
}
Write-Host "Installing Python packages ..."
& $python -m pip install --upgrade pip --quiet
& $python -m pip install -r (Join-Path $pc "requirements.txt")

Push-Location $pc
try {
    $ports = & $python -c "from pscan_server.config import load_config; c = load_config(); print(c.port, c.discovery_port)"
} finally {
    Pop-Location
}
$tcp, $udp = $ports.Trim() -split " "

if (-not $SkipFirewall) {
    Write-Host "Adding firewall rules for TCP $tcp and UDP $udp (Private and Domain networks, never Public). Approve the admin prompt ..."
    $rules = @"
Remove-NetFirewallRule -DisplayName 'PScan (TCP $tcp)' -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName 'PScan discovery (UDP $udp)' -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName 'PScan (TCP $tcp)' -Direction Inbound -Protocol TCP -LocalPort $tcp -Action Allow -Profile Private,Domain | Out-Null
New-NetFirewallRule -DisplayName 'PScan discovery (UDP $udp)' -Direction Inbound -Protocol UDP -LocalPort $udp -Action Allow -Profile Private,Domain | Out-Null
"@
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile", "-Command", $rules
    Get-NetFirewallRule -DisplayName "PScan*" -ErrorAction SilentlyContinue |
        Select-Object DisplayName, Enabled, Profile, Action | Format-Table -AutoSize
}

$tesseract = & $python -c "import sys; sys.path.insert(0, r'$pc'); from pscan_server.config import load_config; print(load_config().find_tesseract() or '')"
if ($tesseract) {
    Write-Host "Tesseract OCR found: $tesseract"
} else {
    Write-Host "Tesseract OCR not found; PDFs won't be searchable until you install it:" -ForegroundColor Yellow
    Write-Host "    winget install --id UB-Mannheim.TesseractOCR" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Done. Start PScan with:  $pc\.venv\Scripts\python -m pscan_server   (from the pc folder)"
Write-Host "Or make it start with Windows:  powershell -ExecutionPolicy Bypass -File $PSScriptRoot\install_autostart.ps1"
