; Nimbus installer (Inno Setup 6). Built by build.py, which passes:
;   /DAppVersion=0.2.0  /DSourceDir=<dist\...\Nimbus>  /DOutputDir=<dist\0.2.0>  /DIconFile=<nimbus.ico>
;
; Nimbus updates itself by running the new setup with
;   /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NIMBUSRESTART=1   (or =connect: reconnect afterwards)
; A silent update starts Nimbus again if it was running or if /NIMBUSRESTART asks for it.
;
; Installs per user into %LOCALAPPDATA%\Programs\Nimbus: no administrator rights needed, and
; Nimbus can update its own files. Data stays in %APPDATA%\Nimbus (no "portable" marker here).
; Running a newer setup over an installed Nimbus updates it in place: the same AppId finds the
; old folder, the running copy is closed cleanly first, settings and subscriptions are kept.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z (build.py does)
#endif

#define AppName "Nimbus"
#define AppExe "Nimbus.exe"

[Setup]
; Never change AppId: it is how a new setup recognises an installed Nimbus to update.
AppId={{6F1C2E7A-3B9D-4C55-9A0E-7D2B8E4F1A63}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableDirPage=auto
DisableProgramGroupPage=yes
DisableReadyPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
; The running copy is closed by PrepareToInstall below, gracefully: Restart Manager would only
; ask the user to close it by hand.
CloseApplications=no
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ru.DesktopIcon=Создать значок на рабочем столе
en.DesktopIcon=Create a desktop shortcut
ru.LaunchApp=Запустить Nimbus
en.LaunchApp=Launch Nimbus
ru.RemoveData=Удалить также настройки, подписки и серверы Nimbus?%n%n(%1)%n%nЕсли вы переустанавливаете Nimbus, нажмите «Нет» — всё сохранится.
en.RemoveData=Also delete Nimbus settings, subscriptions and servers?%n%n(%1)%n%nIf you are reinstalling Nimbus, choose No to keep them.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked

[InstallDelete]
; PyInstaller's runtime changes between versions: drop the old one so no stale DLLs linger.
Type: filesandordirs; Name: "{app}\_internal"
; An old portable marker would move the data next to the program.
Type: files; Name: "{app}\portable"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "portable,\data\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; nimbus://import/<subscription URL> links ("add to Nimbus" buttons) open Nimbus. Per user, like the install.
Root: HKCU; Subkey: "Software\Classes\nimbus"; ValueType: string; ValueName: ""; ValueData: "URL:Nimbus"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\nimbus"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\nimbus\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\nimbus\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
; After a silent update (Nimbus updating itself, or a script) Nimbus comes back.
Filename: "{app}\{#AppExe}"; Parameters: "{code:RestartArgs}"; Flags: nowait skipifnotsilent; Check: RestartAfterSilentUpdate

[UninstallRun]
; Disconnect and quit the running copy (puts the system proxy back), drop its autostart entry.
Filename: "{app}\{#AppExe}"; Parameters: "--quit --uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "QuitNimbus"

[UninstallDelete]
; Files Nimbus itself creates in its folder (geo updates etc. live in %APPDATA%, but be thorough).
Type: filesandordirs; Name: "{app}\core"
Type: dirifempty; Name: "{app}"

[Code]
var
  WasRunning: Boolean;

function QuitRunningNimbus(): Boolean;
var
  Exe, Dir, Cmd: String;
  Code: Integer;
begin
  Result := True;
  Dir := ExpandConstant('{app}');
  Exe := Dir + '\{#AppExe}';
  if not FileExists(Exe) then
    Exit;
  // A running copy holds this mutex (see nimbus/ui/app.py): it is started again after a silent update.
  WasRunning := CheckForMutexes('Local\{#AppName}-' + GetUserNameString());
  // The old version is asked to quit the normal way: it disconnects and restores the proxy.
  Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
  // Whatever is still running from this folder (an old version without --quit, a stuck core)
  // is stopped. Only processes from {app}: other programs' xray.exe are left alone.
  Cmd := '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith(''' +
         Dir + '\'', [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue"';
  Exec('powershell.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(500);
end;

function RestartAfterSilentUpdate(): Boolean;
begin
  Result := WasRunning or (ExpandConstant('{param:NIMBUSRESTART|}') <> '');
end;

function RestartArgs(Param: String): String;
begin
  Result := '--updated';
  if CompareText(ExpandConstant('{param:NIMBUSRESTART|}'), 'connect') = 0 then
    Result := Result + ' --connect';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  QuitRunningNimbus();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{userappdata}\{#AppName}');
    if DirExists(Data) and not UninstallSilent() then
      if MsgBox(FmtMessage(CustomMessage('RemoveData'), [Data]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
