# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 配置 / The PyInstaller spec.

**目录模式（onedir），不是单文件。** 单文件每次启动都要把整个包解压到 %TEMP%，
杀毒软件还会每次重扫一遍；这个包带着 Qt，解一遍要好几秒，而这是个随手打开
看一眼的工具。

    .venv\\Scripts\\python -m PyInstaller packaging/app.spec --noconfirm

产物在 ``dist/ChuniOptionManager/``：exe 在顶层，依赖在 ``_internal/`` 里。
``ui.theme.resource_dir()`` 冻结后指向 ``_internal``，所以 datas 的目标目录
必须和它对得上——改成别的名字，标题栏图标就会变回 Qt 默认那个。
"""

import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = Path(SPECPATH)
sys.path.insert(0, str(ROOT))

VERSION = re.search(
    r'__version__ = "([^"]+)"',
    (ROOT / "core" / "version.py").read_text(encoding="utf-8"),
).group(1)
VERSION_TUPLE = tuple(int(part) for part in (VERSION.split(".") + ["0", "0", "0"])[:3]) + (0,)

# exe 属性里的版本信息。写进 build/ 而不是源码树，免得每次打包都多出一个改动
_version_resource = Path(workpath) / "version_info.txt"
_version_resource.parent.mkdir(parents=True, exist_ok=True)
_version_resource.write_text(
    """VSVersionInfo(
  ffi=FixedFileInfo(filevers={version_tuple}, prodvers={version_tuple}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404B0', [
      StringStruct('CompanyName', 'ErikaAlk'),
      StringStruct('FileDescription', 'CHUNITHM Option Manager'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'ChuniOptionManager'),
      StringStruct('LegalCopyright', 'MIT'),
      StringStruct('OriginalFilename', 'ChuniOptionManager.exe'),
      StringStruct('ProductName', 'CHUNITHM Option Manager'),
      StringStruct('ProductVersion', '{version}'),
    ])]),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])]),
  ]
)
""".format(version=VERSION, version_tuple=VERSION_TUPLE),
    encoding="utf-8",
)

datas = [
    # 窗口图标。exe 自己的图标资源只管文件浏览器和任务栏，标题栏那个是窗口
    # setWindowIcon 画的，得能在运行时读到这个文件
    (str(PKG / "app.ico"), "packaging"),
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # 界面模块是运行时按需 import 的，静态分析看不全
        "ui.main_window",
        "ui.add_character",
        "ui.crop_window",
        "ui.works_dialogs",
        "ui.first_run",
        "ui.editors",
        "ui.cards",
        "ui.imagecache",
        # Pillow 的 DDS 插件是靠插件注册机制加载的，不写进来打包后解不了 DDS
        "PIL.DdsImagePlugin",
        "PIL.PngImagePlugin",
        "PIL.JpegImagePlugin",
        "PIL.BmpImagePlugin",
        "PIL.WebPImagePlugin",
    ],
    hookspath=[],
    runtime_hooks=[],
    # 这些一个都用不上，去掉能省下几十 MB 和一堆无谓的 DLL
    excludes=[
        "tkinter",
        "unittest",
        "pydoc_data",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtNetwork",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtDesigner",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "matplotlib",
        "scipy",
        "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChuniOptionManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压过的 Qt 二进制在部分机器上会加载失败，而省下的体积换不来什么
    upx=False,
    console=False,
    icon=str(PKG / "app.ico"),
    version=str(_version_resource),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ChuniOptionManager",
)
