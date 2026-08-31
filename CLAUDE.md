# CLAUDE.md

给 agent 看的。人看的现状和用法在 [README.md](README.md)。

## 这是什么

一个 **PySide6（Qt 6）+ Python 3.11** 的单窗口桌面应用，用来浏览和编辑 CHUNITHM 的
`option` 文件夹——那些装歌曲、谱面和角色的 mod 包（`A001`、`A300`、`AXVX`、`AZUR`…）。
扫 option 根目录，把歌曲和角色画成游戏内那种卡片，编辑后写回原来的
`Music.xml` / `Chara.xml` / `DDSImage.xml`。**所有面向用户的文字都是中文。**

打包成 PyInstaller onedir + Inno Setup 安装器，装到 `%LOCALAPPDATA%\Programs`。

> **2026-08-27 之前它是 WinUI 3 / .NET 8 的 C# 应用，而且装在 option 文件夹里面。**
> 那一版整个重写掉了，git 历史里还在（标签 `winui-final`）。看到网上或旧笔记里提
> `dotnet build -p:Platform=x64`、`MainWindow.xaml.cs`、`OptionRepository.cs` 的，
> 说的都是那一版，现在一个都不存在。

## 跑起来 / 打包

```powershell
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py                       # 跑
.venv\Scripts\python -m pytest tests -q            # 129 条测试
.venv\Scripts\python packaging\build.py            # 出 exe + 安装包
```

- **必须是 Python 3.11**。这台机器上 `python` 就指向 3.11.9；3.14 也装着，但 PySide6
  这类轮子在它上面多半还没有。
- 测试**不需要显示器也不碰真实游戏目录**：`tests/conftest.py` 把
  `QT_QPA_PLATFORM` 钉成 `offscreen`，并在 `tmp_path` 里造一棵假的 option 树。
- 打包脚本四步：测试 → PyInstaller → **启动冒烟** → Inno Setup。冒烟那步不能省，
  少一个隐藏依赖的表现就是双击没反应，而这在源码里跑是看不出来的。
- `packaging/installer.iss` **必须存成 UTF-8 with BOM**。没有 BOM 的话 ISCC 按 ANSI 读，
  中文全变乱码，而且**它不报错**。
- Inno Setup 在 `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`（`build.py` 会自己找）。

## 架构

三层，方向单向：`ui/` → `core/` → 文件系统。**`core/` 不许 import 任何 Qt 的东西**，
测试和将来可能的命令行入口都指着这条。

```
main.py                先确定 option 在哪，再开主窗口
  ↓
ui/main_window.py      三页（歌曲 / 角色 / 排查）+ 右侧检查器
  ↓ 用
ui/cards.py            自绘的 delegate（歌曲行 / 角色格 / 排查行）
ui/editors.py          两个检查器面板
ui/add_character.py → ui/crop_window.py, ui/works_dialogs.py
ui/first_run.py        选 option 文件夹
ui/tokens.py           设计 Token 的唯一真源，**不 import 任何 Qt**
ui/theme.py            把 Token 映射到 Qt：亮暗模式、样式表、自绘控件、Mica
                       ui/imagecache.py 异步解贴图
  ↓ 都用
core/repository.py     扫描、排查、保存、软删除、新增角色、作品库
  ↓ 用
core/xmlio.py          两套写法（见下）  core/dds.py 编码  core/ddspreview.py 解码
core/models.py         数据模型          core/difficulty.py 难度的唯一真源
core/paths.py          找 option 根目录、记住它
```

### 数据流

`paths.auto_detect_option_root()` → `repository.scan(root)`（在 `QThreadPool` 的后台线程上）
→ `OptionCatalog` → `MainWindow._apply_filters()` 灌进三个 `ObjectListModel`。
搜索 / 筛选 / 排序全部走 `_apply_filters()`，它只查内存里那份 catalog（上限
`MAX_ROWS = 2000`）。保存或删除之后**整棵树重新扫**，再按 `xml_path` 把刚才那条选回来。

## 不许破坏的不变量

1. **删除永远是软删除。** 目录移进 `option\_deleted\<时间戳>_<类型>_<id>_<名字>\`，
   扫描时跳过。`_move_to_deleted` 会拒绝三种目标：不在 option 根目录内的、根目录本身、
   已经在 `_deleted` 里的。这道闸是整个删除路径唯一的护栏。
   → 测试 `test_nothing_outside_the_option_root_can_be_deleted`

2. **两套 XML 写法，别混。**
   - 谱面开关走 `xmlio.replace_enable_flags`：**字节级改写**，除了 `<enable>` 之外一个
     字节都不动。`Music.xml` 是游戏自己发出来的文件，保存一次开关就重排一遍缩进，
     「到底改了什么」立刻没法看。
   - 角色 / 作品 / 模板走 `xmlio.save_xml`：重排缩进，UTF-8 无 BOM、CRLF、
     **结尾不留换行**（游戏发出来的文件就是这样收尾的）。
   → 测试 `test_saving_the_toggles_does_not_reformat_the_file`（字节级逐字比对；
     整份重写同样能把开关写对，功能测试全绿，只有这条看得出差别）

3. **`xmlns:xsd` / `xmlns:xsi` 必须原样留住。** `DDSImage.xml` / `CharaWorks.xml` /
   `WorksSort.xml` 的根节点挂着这两行，但文档里**一次都没用到**这两个前缀——
   ElementTree 只写它实际用到的命名空间，读进来再写出去这两行会**静默消失**。
   所以每次 `save_xml` 都要把 `namespace_decls(原文件)` 传进去。
   → 测试 `test_the_namespace_declarations_survive` + 对照组
     `test_dropping_the_declarations_is_what_a_naive_write_does`

4. **写之前先备份，而且只备份一次。** 每个文件第一次被保存时复制一份 `.bak`。
   每次都覆盖的话，改错了第二次保存就把好的那份也盖没了。

5. **解析永远容错。** 一份坏掉的自定义 XML 只能让它自己不出现在列表里，
   不能让整个目录打不开。每个 parse 都包着 `try`。
   → 测试 `test_a_broken_xml_only_loses_itself`

6. **ID 为 0 表示「没有 / 解析失败」，不是一个真的 ID。**
   - 歌曲：`song_id == 0` 的不参与「同 ID 重复」比对，否则会刷出一大堆假告警。
   - 作品：`works_id <= 0` 时 `delete_works` **不做连带删除**，否则一次删除会带走
     所有没填作品的角色。
   → 测试 `test_songs_without_a_valid_id_are_not_grouped`、
     `test_an_invalid_works_id_does_not_cascade`

7. **分配角色 ID 时要把 `_deleted` 一起算上。** 软删除的角色随时可能被恢复，
   重用它的号，恢复的那一刻就撞车。`collect_character_ids` 用的是
   `skip_deleted=False`，这是全仓唯一一处这么传的地方。
   → 测试 `test_an_id_already_in_the_recycle_area_is_refused`

8. **没给源图就不写任何 DDS。** 套模板的贴图会让新角色顶着乳蛙的脸——
   那比没有立绘更让人困惑。
   → 测试 `test_no_texture_means_no_dds_file`

9. **新增角色半路失败要回滚。** 否则 option 里留下一个没有贴图的残缺角色，
   而那个 ID 从此被永久占用，下次想用同一个号还会被自己拦下来。
   → 测试 `test_a_failed_creation_leaves_nothing_behind`

10. **跨包借用的 `DDSImage` 目录不连带删除。** 它可能被别的角色共用，
    删了就是误伤别人的立绘，还不容易发现。同包才连带。
    → 测试 `test_a_borrowed_texture_directory_is_left_alone`

11. **难度只有一个定义**：`core/difficulty.py`。`Music.xml` 里存的是
    `ID_00`..`ID_05`，另有 `ULTRA` / `WorldsEnd` 这些历史写法，一律先过
    `difficulty.normalise`。配色、排序、筛选、卡面全部从这里取——散在各处各写一份，
    同一个难度在列表里是一个颜色、在卡面上是另一个颜色，而这种错没人会报上来。

12. **`option` 根目录的判据是「三个标记包里出现两个 + 底下真的有 Music.xml」。**
    前一半挡住空壳目录，后一半挡住只是同名的文件夹。放宽到「有一个就算」，
    任何一个叫 `A001` 的文件夹都会被误判。这条判据在 **Python 和 Inno 的 Pascal 里
    各有一份实现**（`core/paths.py` 和 `packaging/installer.iss`），改一处要改两处。

13. **预览和真正的裁剪必须用同一套取景算法**：`core.dds.crop_box`。
    写两份的下场是拖出来的位置和生成出来的贴图对不上，而这要生成一次才看得见。

14. **`ui/__init__.py` 不许 import 任何窗口模块。** 包的 `__init__` 一做急切导入，
    `import ui.theme` 就会顺带把整套窗口和 QtWidgets 拉起来。

15. **绝对不要写 `QWidget { background: ... }`。** QSS 的类型选择器连子类一起命中，
    那一条会把每个 QLabel 都刷上底色，在卡片上显示成一条条横杠。背景只画在真正需要
    的容器上。→ 测试 `test_the_stylesheet_has_no_blanket_widget_rule`

16. **Mica 要三件事一起，而且失败必须回滚。** 窗口自己不画底
    （`WA_TranslucentBackground` + 样式表里那两条 `[mica="true"]`）、
    `DwmExtendFrameIntoClientArea(-1)` 把玻璃摊到整个客户区、属性号按版本分
    （22H2 起 `DWMWA_SYSTEMBACKDROP_TYPE`，21H2 只认没进文档的 `DWMWA_MICA_EFFECT`）。
    少一件就只是个透明窗口。半路失败要把透明属性收回去——透明而底下没有材质，看到的
    是一个黑窟窿，而且只在调用失败的那几台上出现，这边永远复现不了。
    → 测试 `test_a_failed_backdrop_leaves_the_window_opaque`、
    `test_the_stylesheet_lets_mica_show_through`

17. **只有主窗口和第一次那个选目录对话框上 Mica。** 新增角色 / 单图快速生成 / 作品库
    是盖在主窗口上的临时窗口，而 Mica 取的是**桌面壁纸**、不是身后那扇窗，临时窗口用它
    会让人对不上位置。它们仍然只走 `apply_titlebar`。

18. **文字要在整个「承载面集合」上够 4.5:1，不是只对 canvas 量一次。**
    集合是 canvas / surface / surfaceElevated / surfaceSunken / fill.control，
    加上所有 `accent.subtle` 和 `semantic.*.subtle`。最容易顶出边界的是浅色的
    `fill.control`（集合里最暗）和深色的 `warning.subtle`（集合里最亮）——
    `text.tertiary` 就是被这两个面逼出规范建议区间的。
    `fill.hover` / `fill.pressed` **不在**集合里：整行 hover 时行内辅助文字要提到
    `text.secondary`（见 `cards._text_colours`）。
    → 测试 `test_every_text_token_is_readable_on_every_bearing_surface`

19. **控件边界要够 3:1。** 自绘输入框是 `fill.control` + 1px `border.default`，
    而填充和 Surface 只差 1.1 左右，**全靠那条边**。候选色板给的 `#C8C6CC` 只有
    1.62:1，重新生成过。→ 测试 `test_control_boundaries_reach_three_to_one`

20. **Accent 的 hover 和 pressed 必须同方向，pressed 走得更远**（ΔL 0.03 / 0.045）。
    生成器最初给的深色方案是 hover 变亮、pressed 变暗，按下去的反馈方向和悬停相反。
    → 测试 `test_the_accent_states_step_the_right_way`

21. **自绘控件要把焦点环的 4px 算进自己的尺寸**（`FOCUS_RING_OFFSET + WIDTH`，
    向外偏移 2px、2px 宽）。不留这块地方，环照样"画了"，只是被父容器裁掉——
    表现是焦点指示时有时无。→ 测试 `test_the_switch_leaves_room_for_its_focus_ring`

## 会浪费半小时的坑

- **`option` 根目录的内容随时在变。** 用户会合并 / 拆分包。别把「有 35 个包、730 首歌」
  这种数字写进代码或测试。测试一律用 `tests/conftest.py` 造的假树。

- **解码线程只碰 `QImage`，`QPixmap` 一律在界面线程构造。** QPixmap 不是线程安全的，
  在工作线程里 new 一个出来是会崩的那种错。见 `ui/imagecache.py`。

- **PySide6 里没有 `QStyleOptionViewItem.State_MouseOver`**，那些状态位在 `QStyle` 上
  （`QStyle.State_MouseOver` / `QStyle.State_Selected`）。写错的表现是每画一行就往
  stderr 打一段 traceback，而窗口照样开着、卡片是空的——只有真画一遍才看得见。
  → 测试 `test_every_page_paints` 就是干这个的（`window.grab()`）。

- **界面测试里的窗口必须真的 `show()`。** 没显示出来的窗口，子控件的 `isVisible()`
  一律是 `False`，「检查器展开了没有」就测不出来。

- **`offscreen` 平台的字体库是空的。** 测试跑在离屏平台上，`grab()` 出来的图**整屏
  都是方框**，连拉丁字母都是——那是平台的问题，不是字体设错了。要出截图就别设
  `QT_QPA_PLATFORM`，用真平台跑（`docs/` 里那两张就是这么出的）。
  但**字族仍然必须显式设**：自绘的 delegate 不吃 QSS，一律走 `theme.font()`。

- **机器上很可能同时开着装好的那份**，窗口标题和源码跑起来的一模一样，
  `FindWindowW(None, "CHUNITHM Option Manager")` 一律先找到装好的那个——于是改完源码
  截图核对，拍到的是没改过的旧版，看着就像「改了没生效」。按「启动前后新冒出来的那扇窗」
  认，别按标题认。**venv 里的 `python.exe` 还会再起一个子进程**，窗口不属于 `Popen`
  拿到的那个 pid，按 pid 认同样会扑空。

- **Mica 得用真的截屏看，`window.grab()` 看不到**：那画的是 Qt 自己的内容，DWM 那层
  根本不在里面。判断挂上没挂上最快的办法是取一个空白处的像素——纯 `#1C1C1E` 就是没
  挂上，Mica 会带一点壁纸的色偏。

- **游戏全屏跑着的时候抢不到前台**，`SetForegroundWindow` + 屏幕截图会拍到游戏画面。
  要给安装器之类的窗口截图就用 `PrintWindow(hwnd, hdc, 2)`，它抓的是窗口自己的内容，
  和 z 序无关。**别用模拟按键去点窗口**——前台不是你以为的那个，按键会打进游戏里。

- **富文本标签要先钉宽度再算高度。** `theme.wrapped_label` 用富文本设行高，
  宽度不定时 `heightForWidth` 算不出来，`adjustSize()` 给回一个偏矮的高度。
  右下角那条状态提示就这么露过一截在窗口外面（`TOAST_WIDTH` 那条注释）。

- **QSS 没有 `transition`。** 自绘控件（Switch、状态条）照常走 motion Token，
  QSS 控件的 hover / pressed 只能是瞬时的。这条偏离登记在 `tokens.OVERRIDES` 里，
  别为了"柔和"去给 QPushButton 硬做动画。

- **Qt 不会自己应用系统字号缩放。** Windows 的「文本大小」在注册表
  `HKCU\Software\Microsoft\Accessibility\TextScaleFactor`，`theme.text_scale()`
  读出来再乘进像素字号。字号仍然按像素给——按 pt 给的话 Qt 在 96 DPI 下把 13pt 算成
  17px，整屏字大一圈。

- **`Pillow` 能读 DDS，但不能写带 mipmap 的 DXT5**，所以 `core/dds.py` 里是手写的
  BC3 编码器（numpy 向量化，一张 1080 的图连 mipmap 有九万多个块，逐块 Python 循环
  要跑几分钟）。判断编码对不对最快的办法：**看文件大小**——1080 的 `big.dds` 应该正好
  是 1,556,896 字节，和游戏自带的那份一模一样。

- **曲绘全是 `.dds`。** 老版本直接把 `.dds` 喂给 WinUI 的 `BitmapImage`，于是 730 张卡
  全显示 NO IMAGE——那不是没有图，是根本没解码。现在走 `ddspreview` 解成 PNG 再给 Qt。

- **`bash` 的 heredoc 里别写 `\r\n` 这类转义**（这个环境下会被提前解释成真的控制字符，
  写进 Python 源码就是未闭合的字符串）。要往文件里写带反斜杠的代码就用 Write 工具。

## 约定

- **中文文档字符串**，参数 / 返回 / 异常分节，中英双语的一行摘要。注释解释**为什么**，
  不复述代码在做什么。
- 界面照全局 `~\.claude\DESIGN.md`，本项目实现的版本是 **`2026.08.31-a11y-baseline`**，
  记在 `tokens.DESIGN_SYSTEM_REVISION`。跨项目比外观只在这个值一致时才成立。
- **颜色、字号、行高、间距、圆角、阴影、动画时长只在 `ui/tokens.py` 里出现一次**，
  界面代码一律引用。品牌方向是薰衣草紫；Light 和 Dark 是两套独立映射，不是反色。
- 偏离全局默认的地方逐条记在 `tokens.OVERRIDES` 里，**带确定值和原因**。
  新增偏离就往那张表里加一条，别只改值。
- 破坏性动作用 `#Destructive`（红字 + 红边），后果说明在确认框里；颜色不是唯一载体。
- 版本的唯一真源是 `core/version.py`。exe 的版本资源、安装包文件名、控制面板里显示的
  版本全从那里读。
- 加了测试要**把修复改回去跑一遍**，确认它真的红、而且红在正确的那条上。
  这一版 19 条变异全部被挡住；不确定新测试有没有用，就照这个办法验一次。
  ⚠️ 变异脚本要设 `PYTHONDONTWRITEBYTECODE=1`：同一秒内改写、且**文件大小不变**的
  改动会命中过期的 `.pyc`，于是变异被「验证」成绿的——这一版真的这么假绿过两条。
