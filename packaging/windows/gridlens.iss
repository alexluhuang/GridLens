; Per-user installer for the GridLens Windows bundle.
;
; Build it with packaging\windows\build_windows.ps1, which builds the bundle in
; dist\GridLens and the icon in build\gridlens.ico, then runs this script with
; /DAppVersion=<version>. Paths are relative to this file. The installer needs
; no administrator rights: it installs for the current user only, under
; %LOCALAPPDATA%\Programs\GridLens.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define SourceRoot "..\..\dist\GridLens"

[Setup]
; The AppId identifies GridLens to Windows across versions; never change it.
AppId={{492ECFEC-3062-4F4E-BDAA-14E289C7C361}
AppName=GridLens
AppVersion={#AppVersion}
AppPublisher=GridLens Contributors
DefaultDirName={autopf}\GridLens
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=GridLens-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\build\gridlens.ico
UninstallDisplayIcon={app}\GridLens.exe
LicenseFile=..\..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\GridLens"; Filename: "{app}\GridLens.exe"
Name: "{autodesktop}\GridLens"; Filename: "{app}\GridLens.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GridLens.exe"; Description: "{cm:LaunchProgram,GridLens}"; Flags: nowait postinstall skipifsilent
