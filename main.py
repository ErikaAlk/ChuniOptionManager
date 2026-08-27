# -*- coding: utf-8 -*-
"""
入口 / Entry point.

    python main.py
    python main.py --option-root "D:\\CHUNITHM\\bin\\option"

启动顺序是「先确定 option 在哪，再开主窗口」：命令行参数 → 配置文件 →
自动探测 → 都不成就弹选目录向导。向导里点了退出就直接结束，没有 option
目录的话这个程序没有任何事可做。
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import Optional

from core import paths
from core.version import __version__


def _install_crash_logging() -> None:
    """
    没人接住的异常写进日志 / Log anything nobody caught.

    打包之后没有控制台，异常直接消失，用户只看到窗口没了。落到日志里才有得查。
    """
    def hook(kind, value, tb) -> None:
        try:
            target = paths.log_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as handle:
                handle.write("[unhandled]\n")
                handle.write("".join(traceback.format_exception(kind, value, tb)))
                handle.write("\n")
        except Exception:
            pass
        sys.__excepthook__(kind, value, tb)

    sys.excepthook = hook


def resolve_option_root(explicit: Optional[str]) -> Optional[str]:
    """
    确定 option 根目录 / Work out which option root to open.

    参数 / Parameters:
        explicit (Optional[str]): 命令行给的路径，优先于一切。

    返回 / Returns:
        Optional[str]: 路径；连向导都没选出来就是 ``None``。
    """
    if explicit:
        resolved = paths.normalise_option_root(explicit)
        if resolved:
            paths.remember_option_root(resolved)
            return str(resolved)

    detected = paths.auto_detect_option_root()
    if detected:
        # 探测出来的也记下来，下次不用再探
        paths.remember_option_root(detected)
        return str(detected)
    return None


def main(argv: Optional[list] = None) -> int:
    """
    起界面 / Start the app.

    返回 / Returns:
        int: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="CHUNITHM option 文件夹的浏览与编辑工具")
    parser.add_argument("--option-root", dest="option_root", default=None,
                        help="option 文件夹的路径；不给就按配置和自动探测来")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    _install_crash_logging()

    from PySide6.QtWidgets import QApplication

    from ui import theme
    from ui.first_run import OptionRootDialog
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("ChuniOptionManager")
    app.setApplicationDisplayName("CHUNITHM Option Manager")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(theme.app_icon())
    app.setFont(theme.font(theme.TYPE_BODY))
    app.setStyleSheet(theme.stylesheet())

    root = resolve_option_root(args.option_root)
    if not root:
        dialog = OptionRootDialog()
        if dialog.exec() != OptionRootDialog.Accepted or not dialog.chosen:
            return 0
        root = dialog.chosen

    window = MainWindow(root)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
