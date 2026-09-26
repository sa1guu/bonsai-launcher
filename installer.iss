; Bonsai Launcher 安装包脚本 (Inno Setup 6)
; 用法: ISCC.exe installer.iss  ->  输出 installer_output\BonsaiLauncher-Setup.exe

#define AppName "Bonsai Launcher"
#define AppVersion "1.0.0"
#define AppPublisher "Bonsai"
#define AppExe "BonsaiLauncher.exe"

[Setup]
AppId={{8F3A2B71-5C6D-4E7F-9A0B-1C2D3E4F5A6B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; 免管理员安装到用户目录, exe 同目录可写 (runtime/ config.json 会生成在那里)
DefaultDirName={localappdata}\Programs\BonsaiLauncher
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=BonsaiLauncher-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=
DisableProgramGroupPage=yes

[Languages]
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent
