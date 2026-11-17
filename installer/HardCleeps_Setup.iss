; Inno Setup Script para Hard Cleeps Studio 9:16
; Compile com: iscc.exe installer\HardCleeps_Setup.iss

#define MyAppName "Hard Cleeps Studio"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Hard Cleeps"
#define MyAppExeName "run.bat"

[Setup]
AppId={{8E7D2B14-6F3C-4A9E-9B12-4D5A1C3E9011}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\HardCleepsStudio
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=HardCleeps_Setup
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\assets\app_icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "install.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "update_and_restart.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\assets\app_icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\app_icon.ico"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\app_icon.ico"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\install.ps1"" -InstallDir ""{app}"""; StatusMsg: "Configurando Python, FFmpeg, dependências e frontend..."; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\backend"
