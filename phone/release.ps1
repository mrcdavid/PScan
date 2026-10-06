# Build a release APK of PScan, signed with PScan's own key, ready to copy to phones.
#
#   powershell -ExecutionPolicy Bypass -File C:\Users\Marc\dev\PScan\phone\release.ps1
#
# Output: phone\dist\PScan-<version>.apk   (version comes from pyproject.toml)
#
# Why not the debug APK? Debug builds are marked "debuggable" and signed with a throwaway
# development certificate ("CN=Android Debug"), which Play Protect treats as untrusted.
# This script makes a non-debuggable release build signed with a stable PScan key.
#
# The key is created on the first run in phone\signing\ (kept out of git). BACK IT UP:
# a phone only accepts updates signed with the same key; with a new key you must
# uninstall PScan first (and pair the phone again).
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$tools = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) ".briefcase\tools"
$sdk = Join-Path $tools "android_sdk"
$env:JAVA_HOME = Join-Path $tools "java17"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
$buildTools = (Get-ChildItem (Join-Path $sdk "build-tools") | Sort-Object { [version]$_.Name } | Select-Object -Last 1).FullName
$signing = Join-Path $here "signing"
$keystore = Join-Path $signing "pscan-release.jks"
$passFile = Join-Path $signing "keystore-password.txt"

function Invoke-Briefcase {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here "briefcase.ps1") @args
    if ($LASTEXITCODE) { throw "briefcase $args failed (exit $LASTEXITCODE)" }
}

$version = (Select-String -Path (Join-Path $here "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "PScan $version" -ForegroundColor Cyan

# 1. Briefcase writes the version into the Android project only when it creates it, so
#    re-create the project whenever pyproject.toml has a new version.
$gradle = Join-Path $here "build\pscan\android\gradle\app\build.gradle"
$built = $null
if (Test-Path $gradle) {
    $built = (Select-String -Path $gradle -Pattern 'versionName "([^"]+)"').Matches[0].Groups[1].Value
}
if ($built -ne $version) {
    Write-Host "Android project is at version '$built'; re-creating it for $version ..."
    Remove-Item -Recurse -Force (Join-Path $here "build\pscan\android") -ErrorAction SilentlyContinue
    Invoke-Briefcase create android --no-input
}

# 2. PScan's signing key (made once).
if (-not (Test-Path $keystore)) {
    Write-Host "Creating PScan's signing key in $signing ..."
    New-Item -ItemType Directory -Force $signing | Out-Null
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = [Convert]::ToBase64String($bytes).Replace("+", "A").Replace("/", "B").TrimEnd("=")
    [System.IO.File]::WriteAllText($passFile, $password)
    & keytool -genkeypair -keystore $keystore -storetype PKCS12 -alias pscan -keyalg RSA -keysize 3072 `
        -validity 10000 -storepass:file $passFile -dname "CN=PScan, O=Marc"
    if ($LASTEXITCODE) { throw "keytool failed" }
    Write-Host "Back up the whole phone\signing folder somewhere safe." -ForegroundColor Yellow
}

# 3. Release build (Briefcase leaves it unsigned).
Invoke-Briefcase package android -p apk -u --no-input
$dist = Join-Path $here "dist"
$unsigned = Join-Path $dist "PScan-$version-unsigned.apk"
$aligned = Join-Path $dist "PScan-$version-aligned.apk"
$final = Join-Path $dist "PScan-$version.apk"
Move-Item -Force $final $unsigned

# 4. Align and sign it.
try {
    & (Join-Path $buildTools "zipalign.exe") -f -p 4 $unsigned $aligned
    if ($LASTEXITCODE) { throw "zipalign failed" }
    # PKCS12 keys use the keystore password (apksigner would read a second line for --key-pass).
    & (Join-Path $buildTools "apksigner.bat") sign --ks $keystore --ks-key-alias pscan `
        --ks-pass "file:$passFile" --v4-signing-enabled false --out $final $aligned
    if ($LASTEXITCODE) { throw "apksigner failed" }
} finally {
    Remove-Item -Force $unsigned, $aligned -ErrorAction SilentlyContinue
}
& (Join-Path $buildTools "apksigner.bat") verify --print-certs $final
if ($LASTEXITCODE) { throw "The signed APK did not verify" }

Write-Host ""
Write-Host "Ready: $final" -ForegroundColor Green
Write-Host "Copy it to the phone (or run: adb install -r `"$final`")."
