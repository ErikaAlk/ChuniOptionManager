# -*- coding: utf-8 -*-
"""
选 option 文件夹 / Choosing the option folder.

程序装在 ``%LOCALAPPDATA%\\Programs`` 下，和游戏目录没有位置关系，所以它必须
被告知 option 在哪。正常情况下安装程序那一页已经问过了，这个窗口是三种情况的
兜底：安装时跳过了、游戏搬了家、或者想换一个 option 目录看。

选中游戏根目录、``bin``、``option`` 本身，甚至直接选 ``chusanApp.exe``，都能
认出来（:func:`core.paths.normalise_option_root` 负责修正），不必精确点中。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import paths
from ui import theme


class OptionRootDialog(QDialog):
    """
    选 option 根目录 / Ask for the option root.

    ``accept()`` 之后 :attr:`chosen` 就是修正过的绝对路径。
    """

    def __init__(self, current: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择 option 文件夹")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)
        self.setMinimumWidth(620)

        self.chosen = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_WINDOW, theme.SPACE_WINDOW,
                                  theme.SPACE_WINDOW, theme.SPACE_WINDOW)
        layout.setSpacing(theme.SPACE_GROUP)

        title = QLabel("option 文件夹在哪")
        title.setObjectName("Title")
        layout.addWidget(title)

        intro = theme.secondary_label(
            "就是 CHUNITHM 的 bin\\option，底下是 A001、A300、AXVX 这些包。"
            "选游戏根目录或 bin 也行，会自动往下找。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        group = theme.Group()
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_ROW)
        self._path = QLineEdit(current)
        self._path.setPlaceholderText(r"例如 C:\CHUNITHM\bin\option")
        self._path.textChanged.connect(self._validate)
        row.addWidget(self._path, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        group.add_layout(row)
        layout.addWidget(group)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("退出")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._confirm = QPushButton("就用这个")
        self._confirm.setObjectName("Primary")
        self._confirm.clicked.connect(self._accept)
        buttons.addWidget(self._confirm)
        layout.addLayout(buttons)

        if not current:
            detected = paths.auto_detect_option_root()
            if detected:
                self._path.setText(str(detected))
        self._validate()
        theme.apply_mica(self)

    def _browse(self) -> None:
        """开文件夹对话框 / Open the folder picker."""
        start = self._path.text().strip() or ""
        picked = QFileDialog.getExistingDirectory(self, "选择 option 文件夹", start)
        if picked:
            self._path.setText(picked)

    def _validate(self) -> None:
        """
        当场判断这个目录行不行 / Say right away whether the folder will work.

        写在按钮上方而不是等点了「确定」再报错：让人在点之前就知道结果。
        """
        resolved = paths.normalise_option_root(self._path.text().strip())
        if resolved:
            self.chosen = str(resolved)
            self._status.setText("认出来了：{}".format(resolved))
            self._status.setStyleSheet("color: {};".format(theme.SYSTEM["green"]))
            self._confirm.setEnabled(True)
        else:
            self.chosen = ""
            self._status.setText("这里面找不到 option 包（A001 / A300 / AXVX）和 Music.xml。")
            self._status.setStyleSheet("color: {};".format(theme.SYSTEM["orange"]))
            self._confirm.setEnabled(False)

    def _accept(self) -> None:
        """记下来并关窗 / Remember the choice and close."""
        if not self.chosen:
            return
        paths.remember_option_root(self.chosen)
        self.accept()
