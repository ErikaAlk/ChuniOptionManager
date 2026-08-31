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
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import paths
from ui import theme, tokens


class OptionRootDialog(QDialog):
    """
    选 option 根目录 / Ask for the option root.

    ``accept()`` 之后 :attr:`chosen` 就是修正过的绝对路径。

    校验一直在跑（按钮的可用状态跟着它走），但**报错要等用户先动过**：
    规范 4.3 不许在用户还没交互时就抢先甩一条红字。认出来了是好消息，
    那个随时可以显示。
    """

    def __init__(self, current: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择 option 文件夹")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)
        self.setMinimumWidth(620)

        self.chosen = ""
        self._touched = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y,
                                  tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y)
        layout.setSpacing(tokens.GAP_GROUP)

        layout.addWidget(theme.label("option 文件夹在哪", "pageTitle"))

        layout.addWidget(theme.wrapped_label(
            "就是 CHUNITHM 的 bin\\option，底下是 A001、A300、AXVX 这些包。"
            "选游戏根目录或 bin 也行，会自动往下找。", "secondary"))

        row = QHBoxLayout()
        row.setSpacing(tokens.GAP_CONTROL)
        self._path = QLineEdit(current)
        self._path.setPlaceholderText(r"例如 C:\CHUNITHM\bin\option")
        self._path.setAccessibleName("option 文件夹路径")
        self._path.textChanged.connect(self._validate)
        self._path.editingFinished.connect(self._touch)
        row.addWidget(self._path, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)

        self._status = theme.wrapped_label("", "secondary")
        layout.addWidget(self._status)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.GAP_CONTROL)
        buttons.addStretch(1)
        cancel = QPushButton("退出")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._confirm = QPushButton("就用这个")
        self._confirm.setObjectName("Primary")
        self._confirm.setDefault(True)
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
            self._touched = True
            self._path.setText(picked)

    def _touch(self) -> None:
        """用户动过了，从现在起可以报错 / The user has interacted; errors may show."""
        self._touched = True
        self._validate()

    def _validate(self) -> None:
        """
        判断这个目录行不行 / Say whether the folder will work.

        认出来了当场就说，这是好消息；认不出来的那句要等用户先动过——
        窗口一打开就甩一条红字，是在骂一个还没开始操作的人。
        """
        resolved = paths.normalise_option_root(self._path.text().strip())
        colour = theme.palette()
        if resolved:
            self.chosen = str(resolved)
            theme.set_wrapped_text(self._status, "认出来了：{}".format(resolved))
            self._status.setStyleSheet("color: {};".format(colour.success.text))
            self._confirm.setEnabled(True)
            return

        self.chosen = ""
        self._confirm.setEnabled(False)
        if not self._touched:
            theme.set_wrapped_text(self._status, "")
            self._status.setStyleSheet("")
            return
        theme.set_wrapped_text(
            self._status, "这里面找不到 option 包（A001 / A300 / AXVX）和 Music.xml。")
        self._status.setStyleSheet("color: {};".format(colour.warning.text))

    def _accept(self) -> None:
        """记下来并关窗 / Remember the choice and close."""
        self._touched = True
        self._validate()
        if not self.chosen:
            return
        paths.remember_option_root(self.chosen)
        self.accept()
