# -*- coding: utf-8 -*-
r"""
找到 option 根目录，并把它记下来 / Locating and remembering the option root.

老版本（WinUI 那版）把自己装在 ``option\ChuniOptionManager`` 里，靠"我在哪"
反推 option 根目录。现在程序装在 ``%LOCALAPPDATA%\Programs`` 下，和游戏目录
再无位置关系，于是路径必须显式记下来：

1. 安装程序在「选择 option 文件夹」那一页把结果写进 ``option-root.txt``；
2. 应用启动先读自己的 ``config.json``，没有就读那个种子，再没有就自己探一遍
   （见 :func:`auto_detect_option_root`）；
3. 还是探不到就弹首次运行向导，让人手动选。

两个文件都在 ``%APPDATA%\ChuniOptionManager\`` 下，安装目录只放程序，
卸载不会带走用户设置。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 应用名。配置目录、安装目录、注册表项都用它。
APP_NAME = "ChuniOptionManager"

#: 判断「这是不是一个 option 根目录」用的包名。三个里出现两个才算数——
#: 只认一个的话，随便一个叫 A001 的文件夹都会被误判。
MARKER_PACKAGES = ("A001", "A300", "AXVX")

#: 软删除的回收区。扫描要跳过它，判断根目录时也不该在里面找 Music.xml。
DELETED_DIR = "_deleted"

#: 环境变量兜底，给命令行和自动化用。
ENV_OPTION_ROOT = "CHUNI_OPTION_ROOT"

#: 安装程序留下的种子文件。**安装程序只写这一个文件，从不碰 config.json**——
#: 用户在应用里改过的设置不该被一次升级安装悄悄盖掉，而在 Inno 的 Pascal 里
#: 合并 JSON 又只会写出一个更容易出错的东西。第一次读到它就转存进 config.json。
INSTALLER_SEED = "option-root.txt"


def config_dir() -> Path:
    r"""配置目录 / Where settings live. ``%APPDATA%\ChuniOptionManager``。"""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / APP_NAME


def config_path() -> Path:
    """配置文件路径 / The settings file itself."""
    return config_dir() / "config.json"


def log_path() -> Path:
    """
    崩溃日志的落点 / Where crash traces are appended.

    放配置目录而不是 exe 旁边：安装目录可能是只读的，写不进去就等于没有日志。
    """
    return config_dir() / "startup.log"


def load_config() -> Dict[str, Any]:
    """
    读配置 / Read the settings file.

    返回 / Returns:
        Dict[str, Any]: 读不到或读坏了都返回空字典——配置损坏不该拦住启动。
    """
    try:
        with open(config_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data: Dict[str, Any]) -> None:
    """
    写配置 / Write the settings file.

    先写临时文件再 ``os.replace``：中途断电只会留下临时文件，不会留下一个
    截断的 ``config.json`` 让下次启动读到一半。
    """
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = config_path()
    temp = target.with_suffix(".json.tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temp, target)


def looks_like_option_root(path: Any) -> bool:
    """
    这个文件夹像不像 option 根目录 / Does this folder look like an option root?

    判据和老版本一致：``A001`` / ``A300`` / ``AXVX`` 至少出现两个，
    并且底下真的找得到 ``Music.xml``。前一半挡住空壳目录，后一半挡住
    「只是同名文件夹」。

    参数 / Parameters:
        path (Any): 待判断的路径。

    返回 / Returns:
        bool: 像就是 ``True``。
    """
    if not path:
        return False
    root = Path(path)
    if not root.is_dir():
        return False

    markers = sum(1 for name in MARKER_PACKAGES if (root / name).is_dir())
    if markers < 2:
        return False

    return _has_any_music_xml(root)


def _has_any_music_xml(root: Path) -> bool:
    """
    底下有没有 Music.xml / Is there a Music.xml anywhere below?

    先按 ``<包>/music/<歌>/Music.xml`` 这个真实结构直接命中，命中不了再退回
    整棵树遍历。区别在耗时：命中路径是几十次 stat，遍历是一万多个文件。
    """
    for name in MARKER_PACKAGES:
        music_dir = root / name / "music"
        if not music_dir.is_dir():
            continue
        try:
            for entry in music_dir.iterdir():
                if (entry / "Music.xml").is_file():
                    return True
        except OSError:
            continue

    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() != DELETED_DIR]
        if "Music.xml" in files:
            return True
    return False


def normalise_option_root(path: Any) -> Optional[Path]:
    """
    把用户选的路径修正成真正的 option 根目录 / Coax a user's pick into the root.

    选中游戏根目录、``bin``、``option`` 本身，甚至直接选 ``chusanApp.exe``，
    都应该能认出来——让人在文件对话框里精确点中 ``option`` 才算数，是没必要的刁难。

    参数 / Parameters:
        path (Any): 用户选的路径，文件或目录都行。

    返回 / Returns:
        Optional[Path]: 修正后的 option 根目录；实在不像就是 ``None``。
    """
    if not path:
        return None
    picked = Path(path)
    if picked.is_file():
        picked = picked.parent

    for candidate in (picked, picked / "option", picked / "bin" / "option"):
        if looks_like_option_root(candidate):
            return candidate.resolve()
    return None


def stored_option_root() -> Optional[Path]:
    """配置里记着的 option 根目录，且现在仍然成立 / The remembered root, if still valid."""
    remembered = load_config().get("option_root")
    if remembered and looks_like_option_root(remembered):
        return Path(remembered).resolve()
    return None


def remember_option_root(path: Any) -> None:
    """把 option 根目录记进配置 / Persist the chosen root."""
    data = load_config()
    data["option_root"] = str(Path(path).resolve())
    save_config(data)


def installer_seed_root() -> Optional[Path]:
    """
    安装程序在向导里选的那个目录 / What the installer's wizard page picked.

    返回 / Returns:
        Optional[Path]: 种子文件里的路径，且现在仍然成立；没有就是 ``None``。
    """
    try:
        raw = (config_dir() / INSTALLER_SEED).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(raw).resolve() if looks_like_option_root(raw) else None


def _app_dir() -> Path:
    """程序所在目录 / Where this app lives, frozen or not."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _guessed_install_paths() -> List[Path]:
    """
    几个常见落点 / A handful of likely install paths.

    只做便宜的 stat，不扫盘：全盘搜 ``CHUNITHM`` 要几分钟，而探测失败的代价
    只是弹一次选目录向导，不值得。
    """
    guesses: List[Path] = []
    for letter in "CDEFG":
        drive = Path(f"{letter}:\\")
        if not drive.exists():
            continue
        for middle in ("CHUNITHM", "Chuni/CHUNITHM", "Games/CHUNITHM", "chunithm"):
            guesses.append(drive / middle / "bin" / "option")
    return guesses


def auto_detect_option_root() -> Optional[Path]:
    """
    尽力找出 option 根目录 / Best effort at locating the option root.

    顺序：配置 → 环境变量 → 安装程序留下的种子 → 程序自己所在的目录树
    （兼容老版本那种装在 ``option`` 里的用法）→ 几个常见安装路径。

    返回 / Returns:
        Optional[Path]: 找到就返回，找不到返回 ``None``，由调用方去问人。
    """
    remembered = stored_option_root()
    if remembered:
        return remembered

    from_env = normalise_option_root(os.environ.get(ENV_OPTION_ROOT))
    if from_env:
        return from_env

    seeded = installer_seed_root()
    if seeded:
        return seeded

    here = _app_dir()
    for candidate in (here, *here.parents):
        if looks_like_option_root(candidate):
            return candidate.resolve()

    for guess in _guessed_install_paths():
        if looks_like_option_root(guess):
            return guess.resolve()

    return None
