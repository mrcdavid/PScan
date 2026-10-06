# Stop PScan from starting with Windows (removes the Startup and Start-menu shortcuts).
#
#   powershell -ExecutionPolicy Bypass -File C:\Users\Marc\dev\PScan\pc\scripts\uninstall_autostart.ps1
$paths = @(
    (Join-Path ([Environment]::GetFolderPath("Startup")) "PScan.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "PScan.lnk")
)
foreach ($path in $paths) {
    if (Test-Path $path) {
        Remove-Item $path
        Write-Host "Removed $path"
    }
}
Write-Host "PScan will no longer start with Windows. (If it's running now, use the tray icon -> Quit PScan.)"
