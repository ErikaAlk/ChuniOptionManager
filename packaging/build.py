#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一条命令出安装包 / One command, one installer.

    .venv\\Scripts\\python packaging\\build.py
    .venv\\Scripts\\python packaging\\build.py --skip-tests
    .venv\\Scripts\\python packaging\\build.py --no-installer

四步：**跑测试 → PyInstaller 打 exe → 启动冒烟 → Inno Setup 出安装包。**

冒烟那步不能省：**打包成功不等于跑得起来**。少一个隐藏依赖、少一个 Qt 平台
插件，表现都是双击没反应——而这种问题只有真的把 exe 拉起来、看见窗口才发现
得了。这里用 EnumWindows 查「这个进程有没有可见的顶层窗口」，比等进程对象的
标题可靠，也不需要额外依赖。

版本号的唯一真源是 ``core/version.py``：exe 的版本资源、安装包文件名、控制面板
里显示的版本全从那里读。
"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
DIST = ROOT / "dist" / "ChuniOptionManager"
EXE = DIST / "ChuniOptionManager.exe"
INSTALLER_DIR = ROOT / "dist_installer"

#: 冒烟测试认这些窗口标题。主窗口起来了算过，第一次运行的选目录向导也算过——
#: 那同样证明 Qt 起来了、Python 侧没抛异常。
WINDOW_TITLES = ("CHUNITHM Option Manager", "选择 option 文件夹")


def step(message: str) -> None:
    """打一行阶段标题 / Print a step header."""
    print("\n=== {} ===".format(message), flush=True)


def read_version() -> str:
    """
    从 core/version.py 读版本号 / Read the single-source version.

    异常 / Raises:
        RuntimeError: 文件里找不到 ``__version__``。
    """
    text = (ROOT / "core" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    if not match:
        raise RuntimeError("core/version.py 里读不出 __version__")
    return match.group(1)


def run(command: List[str], env: Optional[dict] = None) -> None:
    """
    跑一条命令，失败就抛 / Run a command, raise on a non-zero exit.

    异常 / Raises:
        RuntimeError: 退出码非 0。
    """
    merged = {**os.environ, **(env or {})}
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(command, cwd=str(ROOT), env=merged)
    if result.returncode != 0:
        raise RuntimeError("失败（退出码 {}）：{}".format(result.returncode, " ".join(command)))


def directory_size_mb(path: Path) -> float:
    """目录总大小（MB）/ Total size of a directory in MB."""
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) / 1024 / 1024


def find_window_title(pid: int) -> Optional[str]:
    """
    找出属于这个进程的可见顶层窗口标题 / A visible top-level window title of *pid*.

    参数 / Parameters:
        pid (int): 进程号。

    返回 / Returns:
        Optional[str]: 第一个非空标题；一个都没有就是 ``None``。
    """
    user32 = ctypes.windll.user32
    found: List[str] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(handle: int, _param: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        if buffer.value.strip():
            found.append(buffer.value)
            return False
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return found[0] if found else None


def smoke_test(timeout: float = 60.0) -> None:
    """
    把打好的 exe 真拉起来看一眼 / Actually launch the built exe.

    参数 / Parameters:
        timeout (float): 最多等多久（秒）。

    异常 / Raises:
        RuntimeError: 进程自己退了，或者等到超时也没有窗口。
    """
    process = subprocess.Popen([str(EXE)], cwd=str(DIST))
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "exe 启动后自己退了（退出码 {}）。看 %APPDATA%\\ChuniOptionManager\\"
                    "startup.log".format(process.returncode))
            title = find_window_title(process.pid)
            if title and any(mark in title for mark in WINDOW_TITLES):
                print("窗口起来了：{}".format(title), flush=True)
                return
            time.sleep(0.5)
        raise RuntimeError("等了 {:.0f} 秒也没等到窗口，打包版起不来。".format(timeout))
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def find_iscc() -> Path:
    """
    找 Inno Setup 的命令行编译器 / Locate ISCC.exe.

    异常 / Raises:
        RuntimeError: 三个常见位置都没有。
    """
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("找不到 ISCC.exe。装一下：winget install --id JRSoftware.InnoSetup")


def main(argv: Optional[List[str]] = None) -> int:
    """打包 / Build. 返回进程退出码。"""
    parser = argparse.ArgumentParser(description="打出 exe 和安装包")
    parser.add_argument("--skip-tests", action="store_true", help="跳过测试")
    parser.add_argument("--no-installer", action="store_true", help="只打 exe，不出安装包")
    parser.add_argument("--skip-smoke", action="store_true",
                        help="跳过启动冒烟（无人值守环境用；平时别加）")
    args = parser.parse_args(argv)

    version = read_version()
    print("版本 {}".format(version), flush=True)

    if not args.skip_tests:
        step("跑测试")
        run([sys.executable, "-m", "pytest", "tests", "-q"],
            env={"QT_QPA_PLATFORM": "offscreen"})

    step("PyInstaller 打 exe")
    if DIST.exists():
        shutil.rmtree(DIST)
    run([sys.executable, "-m", "PyInstaller", str(PKG / "app.spec"), "--noconfirm"])
    if not EXE.is_file():
        raise RuntimeError("没找到打好的 exe：{}".format(EXE))
    print("产物 {:.1f} MB".format(directory_size_mb(DIST)), flush=True)

    if not args.skip_smoke:
        step("启动冒烟")
        smoke_test()

    if args.no_installer:
        print("\n只打了 exe：{}".format(EXE))
        return 0

    step("Inno Setup 出安装包")
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    run([str(find_iscc()), "/DAppVersion={}".format(version), str(PKG / "installer.iss")])

    installer = INSTALLER_DIR / "ChuniOptionManager-{}-安装程序.exe".format(version)
    if not installer.is_file():
        raise RuntimeError("安装包没出来：{}".format(installer))
    print("\n安装包 {}（{:.1f} MB）".format(installer, installer.stat().st_size / 1024 / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
