#define AppName "Azimut"
#ifndef AppVer
  #define AppVer "1.7.1"
#endif
#define AppPublisher "Azimut"
#define AppId "{{A7E3C1D0-4B92-4F18-9E6A-8C2D5F1B0A34}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName} {#AppVer}
AppPublisher={#AppPublisher}
AppCopyright={#AppName}
VersionInfoVersion={#AppVer}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
Compression=lzma2/ultra
SolidCompression=yes
LZMAUseSeparateProcess=yes
SetupIconFile=assets\azimut-app.ico
UninstallDisplayIcon={app}\Azimut.exe
UninstallDisplayName={#AppName}
OutputDir=dist
OutputBaseFilename=Azimut-Setup-{#AppVer}
SourceDir=..
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no
UsedUserAreasWarning=no
DisableWelcomePage=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "dist\Azimut\Azimut.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Azimut\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "engine\*"; DestDir: "{app}\engine"; Flags: ignoreversion
Source: "zapret\bin\*"; DestDir: "{app}\zapret\bin"; Flags: ignoreversion
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "installer\Readme.txt"; DestDir: "{app}"; DestName: "Readme.txt"; Flags: isreadme ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Azimut.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\azimut-app.ico"; Comment: "{#AppName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Azimut.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\azimut-app.ico"; Comment: "{#AppName}"; Tasks: desktopicon

[Run]
Filename: "{app}\Azimut.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runascurrentuser; WorkingDir: "{app}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\active"
Type: filesandordirs; Name: "{app}\profiles"
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\github.token"
