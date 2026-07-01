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

[Code]
function GetUninstallString(): String;
var
  UninstallKey: String;
  UninstallString: String;
begin
  UninstallKey := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{48E2C137-8DC0-46E6-9209-5EBEF77E5F62}_is1';
  UninstallString := '';
  if not RegQueryStringValue(HKCU, UninstallKey, 'UninstallString', UninstallString) then
  begin
    RegQueryStringValue(HKLM, UninstallKey, 'UninstallString', UninstallString);
  end;
  Result := UninstallString;
end;

function InitializeSetup(): Boolean;
var
  UninstallString: String;
  ResultCode: Integer;
begin
  Result := True;
  UninstallString := GetUninstallString();
  if UninstallString <> '' then
  begin
    if MsgBox('A previous version of Easy Epic Drone Movie Maker is installed. Do you want to uninstall it first?', mbConfirmation, MB_YESNO) = idYes then
    begin
      if Exec(RemoveQuotes(UninstallString), '/SILENT /NORESTART', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      begin
        Sleep(500);
      end
      else
      begin
        MsgBox('Uninstallation of the previous version failed. Proceeding with installation anyway.', mbInformation, MB_OK);
      end;
    end;
  end;
end;
