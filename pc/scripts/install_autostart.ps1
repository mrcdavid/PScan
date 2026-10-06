# Start PScan automatically when you log in to Windows (and add it to the Start menu).
#
#   powershell -ExecutionPolicy Bypass -File C:\Users\Marc\dev\PScan\pc\scripts\install_autostart.ps1
#
# Undo with uninstall_autostart.ps1. No administrator rights needed.
$ErrorActionPreference = "Stop"
$pc = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $pc ".venv\Scripts\pythonw.exe"
$icon = Join-Path (Split-Path -Parent $pc) "phone\icons\pscan.ico"

if (-not (Test-Path $pythonw)) {
    throw "Run setup.ps1 first ($pythonw is missing)."
}

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath("Startup")) "PScan.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "PScan.lnk")
)
foreach ($path in $targets) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $pythonw
    $link.Arguments = "-m pscan_server"
    $link.WorkingDirectory = $pc
    $link.Description = "PScan: receives scans from your phone"
    if (Test-Path $icon) { $link.IconLocation = $icon }
    $link.Save()
    Write-Host "Created $path"
}

# Start it now as well, unless it's already running.
$listening = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Start-Process -FilePath $pythonw -ArgumentList "-m", "pscan_server" -WorkingDirectory $pc
    Write-Host "PScan started. Look for its icon next to the clock (it may be under the ^ arrow)."
} else {
    Write-Host "PScan is already running."
}
