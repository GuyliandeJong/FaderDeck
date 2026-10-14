; Installer for FaderDeck. build_faderdeck.ps1 compiles it after the EXE:
;   ISCC.exe /DAppVersion=1.7.0 installer\faderdeck.iss
; It installs for the current user only, so neither installing nor the
; automatic update needs administrator rights.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3C9B2E-4D1A-4F7B-9C55-FADE0DEC0A01}
AppName=FaderDeck
AppVersion={#AppVersion}
AppVerName=FaderDeck {#AppVersion}
AppPublisher=Guylian de Jong
AppPublisherURL=https://github.com/GuyliandeJong/FaderDeck
AppSupportURL=https://github.com/GuyliandeJong/FaderDeck/issues
AppUpdatesURL=https://github.com/GuyliandeJong/FaderDeck/releases
PrivilegesRequired=lowest
DefaultDirName={autopf}\FaderDeck
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=FaderDeck-Setup
SetupIconFile=..\faderdeck.ico
UninstallDisplayIcon={app}\FaderDeck.exe
UninstallDisplayName=FaderDeck
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; FaderDeck is asked to quit in [Code]; the Restart Manager would close it
; without logging out of VoiceMeeter.
CloseApplications=no

[Tasks]
Name: "startup"; Description: "Start FaderDeck with Windows (it waits for VoiceMeeter)"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\FaderDeck.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\FaderDeck"; Filename: "{app}\FaderDeck.exe"
Name: "{autodesktop}\FaderDeck"; Filename: "{app}\FaderDeck.exe"; Tasks: desktopicon
Name: "{userstartup}\FaderDeck"; Filename: "{app}\FaderDeck.exe"; Parameters: "--wait-for-voicemeeter"; Tasks: startup

[InstallDelete]
; Startup shortcuts made by hand or by install_faderdeck_startup.ps1 point
; at another copy. The startup task above makes the one that is wanted.
Type: files; Name: "{userstartup}\FaderDeck.lnk"
Type: files; Name: "{userstartup}\VMStreamer.lnk"

[Run]
; Not skipped in silent mode: after an automatic update FaderDeck starts again.
Filename: "{app}\FaderDeck.exe"; Description: "Start FaderDeck"; Flags: nowait postinstall

[Code]
function FaderDeckIsRunning(): Boolean;
begin
  { The packaged FaderDeck holds this mutex for as long as it runs
    (SINGLE_INSTANCE_NAME in main.py). }
  Result := CheckForMutexes('FaderDeck.SingleInstance');
end;

function QuitFaderDeck(const Exe: String): Boolean;
var
  ResultCode, Waited: Integer;
begin
  if FaderDeckIsRunning() and FileExists(Exe) then
  begin
    { --quit asks the running copy to log out of VoiceMeeter and close. }
    Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Waited := 0;
    while FaderDeckIsRunning() and (Waited < 15000) do
    begin
      Sleep(250);
      Waited := Waited + 250;
    end;
  end;
  Result := not FaderDeckIsRunning();
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if FaderDeckIsRunning() then
  begin
    { The copy being installed can ask any running FaderDeck to quit. }
    ExtractTemporaryFile('FaderDeck.exe');
    if not QuitFaderDeck(ExpandConstant('{tmp}\FaderDeck.exe')) then
      Result := 'FaderDeck is still running. Quit it from its tray icon, then run Setup again.';
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := QuitFaderDeck(ExpandConstant('{app}\FaderDeck.exe'));
  if not Result then
    MsgBox('Quit FaderDeck from its tray icon, then uninstall again.', mbError, MB_OK);
end;
