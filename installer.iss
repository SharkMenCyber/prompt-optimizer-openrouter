; Inno Setup script for the OpenRouter edition of the Hermes Prompt Optimizer.
; Packages the PyInstaller one-dir build into a per-user Windows installer (no
; admin/UAC required). The app stores its key + database under %LOCALAPPDATA%,
; so a per-user Program-files location is fine.

#define MyAppName "Prompt Optimizer (OpenRouter)"
#define MyAppVersion "0.6.1"
#define MyAppPublisher "Hermes Prompt Optimizer"
#define MyAppExeName "Prompt Optimizer OpenRouter.exe"
#define MyDistDir "dist\Prompt Optimizer OpenRouter"

[Setup]
AppId={{8F3A6D21-7C4E-4B9A-9E2D-0A1B2C3D4E5F}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Prompt Optimizer OpenRouter
DefaultGroupName=Prompt Optimizer (OpenRouter)
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=PromptOptimizerOpenRouter-Setup-{#MyAppVersion}
SetupIconFile=assets\skull.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
