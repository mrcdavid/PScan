; Inno Setup script for the PScan installer.
; Compiled by pc\build_windows.ps1:  ISCC /DMyAppVersion=0.4.0 pscan.iss
; Paths are relative to this file (pc\packaging).

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "PScan"
#define MyAppPublisher "Marc Allen David"
#define MyAppExe "PScan.exe"
#define MyAppId "{{8F2B5E54-7C3A-4E2B-9E1D-2A6B4C8D1E30}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={autopf}\PScan
DefaultGroupName=PScan
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
OutputDir=..\dist
OutputBaseFilename=PScan-Setup-{#MyAppVersion}
SetupIconFile=..\..\phone\icons\pscan.ico
LicenseFile=..\..\phone\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\PScan\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\PScan"; Filename: "{app}\{#MyAppExe}"; AppUserModelID: "PScan"
Name: "{group}\Uninstall PScan"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PScan"; Filename: "{app}\{#MyAppExe}"; AppUserModelID: "PScan"; Tasks: desktopicon

[Run]
; Open the firewall for the installed exe on private and domain networks (never public).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""PScan"""; Flags: runhidden; StatusMsg: "Updating firewall..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""PScan"" dir=in action=allow program=""{app}\{#MyAppExe}"" enable=yes profile=private,domain"; Flags: runhidden; StatusMsg: "Updating firewall..."
; Offer to start PScan now (runs as the logged-in user, not the installer's admin token).
Filename: "{app}\{#MyAppExe}"; Description: "Start PScan now"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#MyAppExe} /F"; Flags: runhidden; RunOnceId: "StopPScan"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""PScan"""; Flags: runhidden; RunOnceId: "DelFwRule"

[Code]
procedure StopRunningPScan();
var
  ResultCode: Integer;
begin
  // Stop a running copy so its files can be replaced during an upgrade.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#MyAppExe} /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningPScan();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    // Remove this user's "start with Windows" entry. Pairings in %LOCALAPPDATA%\PScan are kept.
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'PScan');
  end;
end;
