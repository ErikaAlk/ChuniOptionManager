; CHUNITHM Option Manager 安装器（Inno Setup 6）
;
; 由 packaging\build.py 调用，版本号通过 /DAppVersion= 传进来——版本的唯一真源是
; core\version.py，别在这里再写一份。
;
; 装到用户目录（PrivilegesRequired=lowest），所以**不弹 UAC**。
;
; 这份脚本比一般的安装器多做一件事：**问出 option 文件夹在哪**。程序装在
; %LOCALAPPDATA%\Programs 下，和游戏目录没有位置关系，不问就只能等第一次启动
; 再弹窗——而那时候人已经以为装完了。
;
; ⚠ 这个文件必须存成 **UTF-8 with BOM**。没有 BOM 的话 ISCC 按 ANSI 读，
; 所有中文会变成乱码，而且它不报错。
;
; ⚠ 安装器**只写 option-root.txt 这个种子文件，绝不碰 config.json**。用户在
; 应用里改过的设置不该被一次升级安装盖掉。

#define AppName "CHUNITHM Option Manager"
#define AppExeName "ChuniOptionManager.exe"
#define AppFileBase "ChuniOptionManager"
#define AppPublisher "ErikaAlk"
#define AppURL "https://github.com/ErikaAlk/ChuniOptionManager"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\ChuniOptionManager"
#endif

[Setup]
AppId={{7C4E1F92-3B5A-4E88-9D21-6F0C8A47B315}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}

DefaultDirName={autopf}\ChuniOptionManager
DefaultGroupName={#AppName}
DisableWelcomePage=no
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\dist_installer
OutputBaseFilename={#AppFileBase}-{#AppVersion}-安装程序
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
WizardStyle=modern

Compression=lzma2/max
SolidCompression=yes

; 升级时旧版还开着的话，让安装器自己关掉，否则 exe 被锁、覆盖会失败
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "cn"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "现在就打开 {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[Code]
var
  OptionPage: TInputDirWizardPage;
  ChosenOptionRoot: String;

{ 这个目录里有没有 option 包（三个里出现两个才算） }
function MarkerCount(Path: String): Integer;
begin
  Result := 0;
  if DirExists(Path + '\A001') then Result := Result + 1;
  if DirExists(Path + '\A300') then Result := Result + 1;
  if DirExists(Path + '\AXVX') then Result := Result + 1;
end;

{ 底下真的找得到 Music.xml 吗。只查 <包>\music\<歌>\Music.xml 这一层，
  整棵树递归一遍要走一万多个文件，向导上按一次「下一步」等不起 }
function HasAnyMusicXml(Path: String): Boolean;
var
  Markers: array[0..2] of String;
  Index: Integer;
  MusicDir: String;
  Found: TFindRec;
begin
  Result := False;
  Markers[0] := 'A001';
  Markers[1] := 'A300';
  Markers[2] := 'AXVX';
  for Index := 0 to 2 do
  begin
    MusicDir := Path + '\' + Markers[Index] + '\music';
    if DirExists(MusicDir) then
    begin
      if FindFirst(MusicDir + '\*', Found) then
      begin
        try
          repeat
            if (Found.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
              if (Found.Name <> '.') and (Found.Name <> '..') then
                if FileExists(MusicDir + '\' + Found.Name + '\Music.xml') then
                begin
                  Result := True;
                  Exit;
                end;
          until not FindNext(Found);
        finally
          FindClose(Found);
        end;
      end;
    end;
  end;
end;

function LooksLikeOptionRoot(Path: String): Boolean;
begin
  Result := (Path <> '') and DirExists(Path) and (MarkerCount(Path) >= 2) and HasAnyMusicXml(Path);
end;

{ 选中游戏根目录或 bin 也认，往下找一层 option。让人精确点中 option 是没必要的刁难 }
function NormaliseOptionRoot(Path: String): String;
var
  Candidates: array[0..2] of String;
  Index: Integer;
begin
  Result := '';
  Path := RemoveBackslashUnlessRoot(Trim(Path));
  if Path = '' then Exit;
  Candidates[0] := Path;
  Candidates[1] := Path + '\option';
  Candidates[2] := Path + '\bin\option';
  for Index := 0 to 2 do
    if LooksLikeOptionRoot(Candidates[Index]) then
    begin
      Result := Candidates[Index];
      Exit;
    end;
end;

{ 应用之前记下来的那个目录。有的话就拿它预填，让人看到的就是正在生效的那个 }
function StoredOptionRoot: String;
var
  Lines: TArrayOfString;
  Index: Integer;
  Text: String;
begin
  Result := '';
  if LoadStringsFromFile(ExpandConstant('{userappdata}\ChuniOptionManager\option-root.txt'), Lines) then
    for Index := 0 to GetArrayLength(Lines) - 1 do
    begin
      Text := Trim(Lines[Index]);
      if Text <> '' then
      begin
        Result := Text;
        Exit;
      end;
    end;
end;

{ 猜几个常见落点。只做便宜的目录判断，不扫盘——全盘搜 CHUNITHM 要几分钟，
  而猜不中的代价只是让人自己点一下「浏览」 }
function DetectOptionRoot: String;
var
  Drives: array[0..4] of String;
  Layouts: array[0..3] of String;
  DriveIndex, LayoutIndex: Integer;
  Candidate: String;
begin
  Result := StoredOptionRoot;
  if LooksLikeOptionRoot(Result) then Exit;
  Result := '';

  Drives[0] := 'C:'; Drives[1] := 'D:'; Drives[2] := 'E:'; Drives[3] := 'F:'; Drives[4] := 'G:';
  Layouts[0] := '\CHUNITHM\bin\option';
  Layouts[1] := '\Chuni\CHUNITHM\bin\option';
  Layouts[2] := '\Games\CHUNITHM\bin\option';
  Layouts[3] := '\chunithm\bin\option';

  for DriveIndex := 0 to 4 do
    for LayoutIndex := 0 to 3 do
    begin
      Candidate := Drives[DriveIndex] + Layouts[LayoutIndex];
      if LooksLikeOptionRoot(Candidate) then
      begin
        Result := Candidate;
        Exit;
      end;
    end;
end;

procedure InitializeWizard;
begin
  OptionPage := CreateInputDirPage(
    wpSelectDir,
    '选择 option 文件夹',
    'CHUNITHM 的 option 在哪？',
    '就是游戏的 bin\option，底下是 A001、A300、AXVX 这些包。' + #13#10 +
    '选游戏根目录或 bin 也行，会自动往下找；留空的话，第一次打开程序时再问。',
    False, '');
  OptionPage.Add('');
  OptionPage.Values[0] := DetectOptionRoot;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Typed, Normalised: String;
begin
  Result := True;
  if CurPageID <> OptionPage.ID then Exit;

  Typed := Trim(OptionPage.Values[0]);
  if Typed = '' then
  begin
    ChosenOptionRoot := '';
    Result := (MsgBox('还没选 option 文件夹。' + #13#10 + #13#10 +
                      '这样也能装，第一次打开程序时会再问一次。现在继续吗？',
                      mbConfirmation, MB_YESNO) = IDYES);
    Exit;
  end;

  Normalised := NormaliseOptionRoot(Typed);
  if Normalised = '' then
  begin
    MsgBox('这个文件夹里找不到 option 包（A001 / A300 / AXVX）和 Music.xml。' + #13#10 + #13#10 +
           '要选的是 CHUNITHM 的 bin\option，选游戏根目录或 bin 也行。',
           mbError, MB_OK);
    Result := False;
    Exit;
  end;

  ChosenOptionRoot := Normalised;
  OptionPage.Values[0] := Normalised;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Directory: String;
begin
  if CurStep <> ssPostInstall then Exit;
  if ChosenOptionRoot = '' then Exit;

  Directory := ExpandConstant('{userappdata}\ChuniOptionManager');
  ForceDirectories(Directory);
  SaveStringToFile(Directory + '\option-root.txt', ChosenOptionRoot, False);
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine;
  if ChosenOptionRoot <> '' then
    Result := Result + 'option 文件夹：' + NewLine + Space + ChosenOptionRoot + NewLine + NewLine
  else
    Result := Result + 'option 文件夹：' + NewLine + Space + '（第一次打开时再选）' + NewLine + NewLine;
  if MemoTasksInfo <> '' then
    Result := Result + MemoTasksInfo;
end;

[Messages]
; --- 标题与按钮 ---
SetupAppTitle=安装
SetupWindowTitle=安装 - %1
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonCancel=取消
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&R)…
ButtonWizardBrowse=浏览(&R)…
ButtonYes=是(&Y)
ButtonNo=否(&N)
ButtonOK=确定
ClickNext=点「下一步」继续，或点「取消」退出安装。
BeveledLabel=

; --- 欢迎页 ---
WelcomeLabel1=欢迎安装 [name]
WelcomeLabel2=即将把 [name/ver] 装到这台电脑上。%n%n它用来浏览和编辑 CHUNITHM 的 option 文件夹：歌曲、谱面开关、角色、作品库。%n%n装的过程中会问一次 option 文件夹在哪。%n%n继续之前建议先关掉正在运行的 [name]。

; --- 选目录 ---
WizardSelectDir=选择安装位置
SelectDirDesc=把 [name] 装到哪里？
SelectDirLabel3=安装程序会把 [name] 装进下面这个文件夹。它不需要放在游戏目录里。
SelectDirBrowseLabel=点「下一步」继续。想换个地方就点「浏览」。
DiskSpaceGBLabel=至少需要 [gb] GB 可用磁盘空间。
DiskSpaceMBLabel=至少需要 [mb] MB 可用磁盘空间。
CannotInstallToNetworkDrive=不能装到网络驱动器上。
CannotInstallToUNCPath=不能装到 UNC 路径上。
InvalidPath=请填写带盘符的完整路径，例如：%nC:\APP
DirExists=文件夹已经存在：%n%n%1%n%n还是要装到这里吗？
DirDoesntExist=文件夹不存在：%n%n%1%n%n要创建它吗？

; --- 附加任务 ---
WizardSelectTasks=选择附加任务
SelectTasksDesc=还要做点什么？
SelectTasksLabel2=勾上安装时要一并做的事，然后点「下一步」。

; --- 准备安装 ---
WizardReady=准备就绪
ReadyLabel1=一切就绪，可以开始安装了。
ReadyLabel2a=点「安装」开始，或点「上一步」回去改。
ReadyLabel2b=点「安装」开始。
ReadyMemoDir=安装位置：
ReadyMemoTasks=附加任务：

; --- 安装中与完成 ---
WizardPreparing=正在准备
PreparingDesc=正在准备安装 [name]。
WizardInstalling=正在安装
InstallingLabel=正在把 [name] 装进去。
FinishedHeadingLabel=[name] 装好了
FinishedLabel=[name] 已经装到这台电脑上，开始菜单里能找到它。%n%n它只读写你指定的那个 option 文件夹：改动前会自动留一份 .bak，删除是移进 option\_deleted，不会真删。
FinishedLabelNoIcons=[name] 已经装到这台电脑上。
ClickFinish=点「完成」结束安装。
RunEntryExec=运行 %1

; --- 取消与出错 ---
ExitSetupTitle=退出安装
ExitSetupMessage=安装还没完成。现在退出的话，[name] 不会被装上。%n%n真的要退出吗？
ErrorTitle=出错了
SetupAborted=安装没能完成。%n%n请解决问题后重新运行安装程序。
StatusExtractFiles=正在释放文件…
StatusCreateIcons=正在创建快捷方式…
StatusUninstalling=正在卸载 %1…
StatusRollback=正在撤销已做的改动…

; --- 卸载 ---
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 %1
ConfirmUninstall=确定要把 %1 删掉吗？%n%n只删程序本身，option 文件夹和里面的数据一个都不动。
UninstalledAll=%1 已经从这台电脑上卸载干净。
UninstalledMost=%1 已卸载。%n%n有一些内容没能删掉，需要你手动清理。
UninstallStatusLabel=正在把 %1 从这台电脑上删掉，稍等一下。
