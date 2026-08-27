# -*- coding: utf-8 -*-
"""
作品库 / The works library dialogs.

作品（works）是角色在游戏内选角界面的分类依据。没有有效作品的角色只能从
「最近使用」这类分类里找到，长时间不用就翻不出来了——所以新增角色时选一个
作品是重要的，这两个窗口就是为了让人当场能建、能改。

**删除作品会连带删掉属于它的角色**，所以删除做成两次点击的就地确认，
不再套一层确认对话框。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import repository
from core.models import WorksItem
from ui import theme


class AddWorksDialog(QDialog):
    """新建作品 / Create one works entry."""

    def __init__(self, option_root: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建作品")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)
        self.setMinimumWidth(520)

        self._option_root = option_root
        self.created: Optional[WorksItem] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_WINDOW, theme.SPACE_WINDOW,
                                  theme.SPACE_WINDOW, theme.SPACE_WINDOW)
        layout.setSpacing(theme.SPACE_GROUP)

        group = theme.Group()
        self._package = QComboBox()
        self._package.addItems(repository.list_packages(option_root))
        group.add_layout(_field("写入包（文件夹）", self._package))
        group.add_separator()

        self._works_id = QLineEdit()
        self._works_id.setPlaceholderText("正整数，不能和已有的重复")
        group.add_layout(_field("作品 ID", self._works_id))
        group.add_separator()

        self._name = QLineEdit()
        self._name.setPlaceholderText("游戏内显示的名字，如 アズールレーン")
        group.add_layout(_field("作品名", self._name))
        group.add_separator()

        self._sort_name = QLineEdit()
        self._sort_name.setPlaceholderText("留空就用作品名")
        group.add_layout(_field("排序名", self._sort_name))
        layout.addWidget(group)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color: {};".format(theme.SYSTEM["orange"]))
        self._error.hide()
        layout.addWidget(self._error)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        create = QPushButton("创建")
        create.setObjectName("Primary")
        create.clicked.connect(self._create)
        buttons.addWidget(create)
        layout.addLayout(buttons)

        theme.apply_dark_titlebar(self)

    def _create(self) -> None:
        """校验并写盘 / Validate, then write."""
        try:
            works_id = int(self._works_id.text().strip())
        except ValueError:
            self._fail("作品 ID 必须是正整数。")
            return

        try:
            self.created = repository.add_works(
                self._option_root,
                self._package.currentText(),
                works_id,
                self._name.text(),
                self._sort_name.text(),
            )
        except (ValueError, OSError) as error:
            self._fail(str(error))
            return
        self.accept()

    def _fail(self, message: str) -> None:
        """把错误摆在按钮上方 / Show the error where the eye already is."""
        self._error.setText(message)
        self._error.show()


class ManageWorksDialog(QDialog):
    """
    作品库管理 / Edit and delete works entries.

    信号量级的状态就一个：:attr:`changed`，删过东西时为真，主窗口据此决定
    要不要重新扫描目录（连带删角色之后，歌曲和角色列表都会变）。
    """

    def __init__(self, option_root: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("作品库管理")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)
        self.resize(760, 620)

        self._option_root = option_root
        self.changed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_WINDOW, theme.SPACE_WINDOW,
                                  theme.SPACE_WINDOW, theme.SPACE_WINDOW)
        layout.setSpacing(theme.SPACE_ROW)

        warning = QLabel("删除作品会连带删除属于它的角色，需要点两次确认。删掉的东西移进 _deleted，没有真删。")
        warning.setWordWrap(True)
        warning.setStyleSheet("color: {};".format(theme.SYSTEM["orange"]))
        layout.addWidget(warning)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 8, 0)
        self._rows.setSpacing(theme.SPACE_ROW)
        self._scroll.setWidget(self._rows_host)
        layout.addWidget(self._scroll, 1)

        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close)
        layout.addLayout(footer)

        self._reload()
        theme.apply_dark_titlebar(self)

    def _reload(self) -> None:
        """重建列表 / Rebuild the rows from disk."""
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        try:
            works_list: List[WorksItem] = repository.list_works(self._option_root)
        except OSError:
            works_list = []

        if not works_list:
            self._rows.addWidget(theme.secondary_label("作品库是空的（option 内没有 CharaWorks.xml）。"))
        for works in works_list:
            self._rows.addWidget(self._build_row(works))
        self._rows.addStretch(1)

    def _build_row(self, works: WorksItem) -> QWidget:
        """一个作品一行 / One editable row."""
        group = theme.Group()

        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_ROW)
        name = QLineEdit(works.name)
        sort_name = QLineEdit(works.sort_name)
        top.addLayout(_field("名称", name), 1)
        top.addLayout(_field("排序名", sort_name), 1)
        group.add_layout(top)

        meta = theme.footnote_label("ID {} · {} · priority {}".format(
            works.works_id, works.package, works.priority))
        group.add(meta)

        actions = QHBoxLayout()
        actions.addStretch(1)

        save = QPushButton("保存")

        def do_save() -> None:
            works.name = name.text().strip()
            works.sort_name = sort_name.text().strip()
            try:
                repository.update_works(works)
                meta.setText("ID {} · {} · priority {} · 已保存".format(
                    works.works_id, works.package, works.priority))
            except (OSError, ValueError) as error:
                meta.setText(str(error))

        save.clicked.connect(do_save)
        actions.addWidget(save)

        delete = QPushButton("删除")
        delete.setObjectName("Destructive")
        armed = {"value": False}

        def do_delete() -> None:
            if not armed["value"]:
                armed["value"] = True
                delete.setText("再点一次：连角色一起删")
                return
            try:
                repository.delete_works(self._option_root, works)
                self.changed = True
                self._reload()
            except (OSError, ValueError) as error:
                meta.setText(str(error))

        delete.clicked.connect(do_delete)
        actions.addWidget(delete)
        group.add_layout(actions)

        return group


def _field(label: str, widget: QWidget) -> QVBoxLayout:
    """一个带小标签的输入框 / A captioned input."""
    column = QVBoxLayout()
    column.setSpacing(4)
    column.addWidget(theme.field_label(label))
    column.addWidget(widget)
    return column
