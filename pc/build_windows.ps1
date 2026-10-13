# Build the PScan Windows installer.
#
#   powershell -ExecutionPolicy Bypass -File pc\build_windows.ps1
#
# Produces pc\dist\PScan-Setup-<version>.exe. Steps:
#   1. PyInstaller freezes PScan.exe (one folder) into pc\dist\PScan.
#   2. A trimmed copy of Tesseract OCR is placed in pc\dist\PScan\tesseract.
#   3. A smoke test drives the built exe end-to-end.
#   4. Inno Setup (ISCC) wraps it all into the installer.
#
# Prerequisites: pc\.venv exists (pc\scripts\setup.ps1), and Inno Setup is installed
# (winget install --id JRSoftware.InnoSetup).
param(
    [string]$Tesseract = "C:\Program Files\Tesseract-OCR",
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$pc = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $pc
try {
    $python = Join-Path $pc ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) { throw "Run pc\scripts\setup.ps1 first ($python is missing)." }

    $version = (& $python -c "import pscan_server; print(pscan_server.__version__)").Trim()
    $env:PSCAN_VERSION = $version
    Write-Host "Building PScan $version" -ForegroundColor Cyan

    # --- 1. Clean and freeze ------------------------------------------------
    Remove-Item -Recurse -Force (Join-Path $pc "build"), (Join-Path $pc "dist\PScan") -ErrorAction SilentlyContinue
    Write-Host "Ensuring PyInstaller is installed ..."
    & $python -m pip install --quiet --disable-pip-version-check "pyinstaller>=6.11" "pyinstaller-hooks-contrib>=2024.10"
    if ($LASTEXITCODE) { throw "pip install pyinstaller failed" }

    # Windows version resource (name/version/author shown in file properties).
    $v4 = ($version.Split('.') + @('0','0','0','0'))[0..3] -join ','
    @"
VSVersionInfo(ffi=FixedFileInfo(filevers=($v4), prodvers=($v4), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
kids=[StringFileInfo([StringTable('040904B0', [
  StringStruct('CompanyName', 'Marc Allen David'),
  StringStruct('FileDescription', 'PScan - Phone-to-PC Document Scanner'),
  StringStruct('FileVersion', '$version'),
  StringStruct('ProductName', 'PScan'),
  StringStruct('ProductVersion', '$version'),
  StringStruct('OriginalFilename', 'PScan.exe')])]),
VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"@ | Set-Content -Encoding utf8 (Join-Path $pc "packaging\version_info.txt")

    & $python -m PyInstaller --clean --noconfirm --distpath (Join-Path $pc "dist") --workpath (Join-Path $pc "build") (Join-Path $pc "packaging\pscan.spec")
    if ($LASTEXITCODE) { throw "PyInstaller failed" }
    $appDir = Join-Path $pc "dist\PScan"

    # --- 2. Bundle a trimmed Tesseract -------------------------------------
    if (-not (Test-Path (Join-Path $Tesseract "tesseract.exe"))) {
        throw "Tesseract not found at $Tesseract. Install it (winget install --id UB-Mannheim.TesseractOCR) or pass -Tesseract."
    }
    $dst = Join-Path $appDir "tesseract"
    New-Item -ItemType Directory -Force $dst, (Join-Path $dst "tessdata") | Out-Null
    # tesseract.exe + its runtime DLLs (skip the training tools and Java jars).
    Copy-Item (Join-Path $Tesseract "tesseract.exe") $dst
    Get-ChildItem (Join-Path $Tesseract "*.dll") | Copy-Item -Destination $dst
    foreach ($item in @("eng.traineddata", "osd.traineddata", "pdf.ttf", "configs", "tessconfigs")) {
        $src = Join-Path $Tesseract "tessdata\$item"
        if (Test-Path $src) { Copy-Item $src (Join-Path $dst "tessdata") -Recurse -Force }
    }
    if (Test-Path (Join-Path $Tesseract "doc\LICENSE")) {
        Copy-Item (Join-Path $Tesseract "doc\LICENSE") (Join-Path $dst "LICENSE.tesseract.txt")
    }
    "{0:N0} MB bundled app" -f ((Get-ChildItem $appDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB) | Write-Host

    # --- 3. Smoke test the built exe ---------------------------------------
    Write-Host "Smoke testing the built exe ..." -ForegroundColor Cyan
    & $python (Join-Path $pc "packaging\smoke_test.py") (Join-Path $appDir "PScan.exe")
    if ($LASTEXITCODE) { throw "Smoke test failed" }

    # --- 4. Installer -------------------------------------------------------
    if ($SkipInstaller) { Write-Host "Skipping installer (-SkipInstaller)."; return }
    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $isccPaths = @(
            "C:\Program Files (x86)\Inno Setup*\ISCC.exe",
            "C:\Program Files\Inno Setup*\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup*\ISCC.exe"
        )
        $iscc = (Get-ChildItem $isccPaths -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
    }
    if (-not $iscc) { throw "Inno Setup (ISCC.exe) not found. Install it: winget install --id JRSoftware.InnoSetup" }
    & $iscc "/DMyAppVersion=$version" (Join-Path $pc "packaging\pscan.iss")
    if ($LASTEXITCODE) { throw "ISCC failed" }

    $setup = Join-Path $pc "dist\PScan-Setup-$version.exe"
    Write-Host ""
    Write-Host "Installer ready: $setup" -ForegroundColor Green
    "{0:N0} MB" -f ((Get-Item $setup).Length / 1MB) | Write-Host
}
finally {
    Pop-Location
}
