#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef DistDir
  #define DistDir "..\build\windows\e2dm2_launcher.dist"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{48E2C137-8DC0-46E6-9209-5EBEF77E5F62}
AppName=Easy Epic Drone Movie Maker
AppVersion={#AppVersion}
AppVerName=Easy Epic Drone Movie Maker {#AppVersion}
AppPublisher=E2DM2
DefaultDirName={localappdata}\Programs\E2DM2
DefaultGroupName=Easy Epic Drone Movie Maker
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=E2DM2-Setup-{#AppVersion}
SetupIconFile=..\e2dm2\assets\icons\app-icon.ico
UninstallDisplayIcon={app}\E2DM2.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#AppVersion}
VersionInfoCompany=E2DM2
VersionInfoDescription=Easy Epic Drone Movie Maker Installer
VersionInfoProductName=Easy Epic Drone Movie Maker
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Easy Epic Drone Movie Maker"; Filename: "{app}\E2DM2.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Easy Epic Drone Movie Maker"; Filename: "{app}\E2DM2.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\E2DM2.exe"; Description: "Launch Easy Epic Drone Movie Maker"; Flags: nowait postinstall skipifsilent
