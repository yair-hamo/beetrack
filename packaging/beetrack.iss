; Inno Setup script: builds dist\beetrack-setup-<version>.exe from the PyInstaller folder dist\beetrack.
; The version comes from the BEETRACK_VERSION environment variable (set by the GitHub workflow).
; Installs per user (no admin rights needed), adds Start-menu and optional desktop shortcuts,
; and upgrades in place. Experiments live in Documents\beetrack and are never touched.

#define AppVersion GetEnv("BEETRACK_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8B0F6C2E-5D3A-4C51-9E2B-7A1F2D3C4B5E}
AppName=beetrack
AppVersion={#AppVersion}
AppVerName=beetrack {#AppVersion}
AppPublisher=beetrack
AppPublisherURL=https://github.com/yair-hamo/beetrack
AppSupportURL=https://github.com/yair-hamo/beetrack/issues
DefaultDirName={autopf}\beetrack
DefaultGroupName=beetrack
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=beetrack-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=beetrack.ico
UninstallDisplayIcon={app}\beetrack.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; remove the previous version's program files on upgrade (data is elsewhere)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\beetrack\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\beetrack"; Filename: "{app}\beetrack.exe"
Name: "{group}\Uninstall beetrack"; Filename: "{uninstallexe}"
Name: "{autodesktop}\beetrack"; Filename: "{app}\beetrack.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\beetrack.exe"; Description: "Start beetrack now"; Flags: nowait postinstall skipifsilent
