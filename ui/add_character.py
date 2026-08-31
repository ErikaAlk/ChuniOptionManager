# -*- coding: utf-8 -*-
"""
新增角色 / Creating a character.

克隆 AZUR 包里的模板（``chara114514`` / ``ddsImage114514``），填好 ID、名字、
作品和贴图之后写进 option。真正落盘的活在
:func:`core.repository.add_character`，这里只负责问清楚。

角色 ID 分成「基 ID」和「皮肤 ID」两格填，是因为游戏的编号规则就是
**最终 ID = 基 ID × 10 + 皮肤 ID**（皮肤是个位 0–9，0 即默认皮肤）。分开填之后
不会有人把 ``24690`` 写成 ``2469``，最终 ID 也当场回显出来。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
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
from core.repository import AddCharacterRequest, CropSettings
from ui import theme, tokens
from ui.crop_window import PANES, CropDialog
from ui.works_dialogs import AddWorksDialog, ManageWorksDialog


class AddCharacterDialog(QDialog):
    """
    「新增角色」窗口 / The add-character dialog.

    ``accept()`` 之后从 :meth:`request` 取表单结果；调用方负责真正写盘，
    这样失败提示能和主窗口的状态条走同一条路。
    """

    def __init__(self, option_root: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增角色")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)
        self.resize(720, 780)

        self._option_root = option_root
        self._source_image = ""
        self._crops: Dict[str, CropSettings] = {
            key: CropSettings(default.zoom, default.offset_x, default.offset_y)
            for key, _label, _file, _size, default in PANES
        }
        self._works: List[WorksItem] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y,
                                 tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y)
        outer.setSpacing(tokens.GAP_GROUP)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        # 左边留出焦点环的 4px，右边给滚动条让位
        layout.setContentsMargins(tokens.FOCUS_RING_OFFSET + tokens.FOCUS_RING_WIDTH, 0,
                                  tokens.GAP_CONTROL, 0)
        layout.setSpacing(tokens.GAP_SECTION)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        identity = theme.Section("ID 与名称")

        self._base_id = QLineEdit()
        self._base_id.setPlaceholderText("留空＝自动分配下一个空闲号（≥114514）")
        self._base_id.textChanged.connect(self._update_final_id)
        identity.add_layout(_row("基 ID", self._base_id))

        self._skin_id = QLineEdit("0")
        self._skin_id.setPlaceholderText("0–9，0 即默认皮肤")
        self._skin_id.textChanged.connect(self._update_final_id)
        identity.add_layout(_row("皮肤 ID", self._skin_id))

        self._final_id = QLineEdit()
        self._final_id.setReadOnly(True)
        self._final_id.setPlaceholderText("基 ID × 10 + 皮肤 ID")
        identity.add_layout(_row("最终 ID", self._final_id))

        self._name = QLineEdit()
        self._name.setPlaceholderText("游戏内显示的角色名")
        identity.add_layout(_row("角色名", self._name))

        self._illustrator = QLineEdit()
        self._illustrator.setPlaceholderText("可选，留空写 Invalid")
        identity.add_layout(_row("绘师", self._illustrator))
        identity.add_block(_warning(
            "角色名尽量用日语字库里有的字。超出字库的汉字在游戏内会显示成方块。"))
        layout.addWidget(identity)

        works_section = theme.Section("作品（works）")
        works_row = QHBoxLayout()
        works_row.setSpacing(tokens.GAP_CONTROL)
        self._works_box = QComboBox()
        self._works_box.setAccessibleName("作品")
        works_row.addWidget(self._works_box, 1)
        new_works = QPushButton("新建…")
        new_works.clicked.connect(self._add_works)
        works_row.addWidget(new_works)
        manage_works = QPushButton("管理库…")
        manage_works.clicked.connect(self._manage_works)
        works_row.addWidget(manage_works)
        works_section.add_layout(works_row)
        works_section.add_block(_warning(
            "不填有效作品的话，游戏内选角界面按作品分类检索不到这个角色，"
            "多半只能在「最近使用」里出现，长时间不用就翻不出来了。"))
        layout.addWidget(works_section)

        textures = theme.Section("贴图（全身 / 半身 / 大头）")
        quick = QPushButton("单图快速生成三张贴图…")
        quick.clicked.connect(self._open_crop)
        textures.add_block(quick)
        self._texture_labels: Dict[str, QLabel] = {}
        for key, label, file_name, size, _default in PANES:
            row = theme.label("", "caption")
            row.hide()
            self._texture_labels[key] = row
            textures.add_block(row)
        self._texture_hint = theme.wrapped_label(
            "不生成也能建角色，只是这个角色没有立绘。不会套用模板的乳蛙贴图。", "secondary")
        textures.add_block(self._texture_hint)
        layout.addWidget(textures)
        layout.addStretch(1)

        self._error = theme.wrapped_label("", "secondary")
        self._error.hide()
        outer.addWidget(self._error)

        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.GAP_CONTROL)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        confirm = QPushButton("生成并写入 AZUR")
        confirm.setObjectName("Primary")
        confirm.setDefault(True)
        confirm.clicked.connect(self._confirm)
        buttons.addWidget(confirm)
        outer.addLayout(buttons)

        self._reload_works(repository.DEFAULT_AZUR_WORKS_ID)
        self._update_final_id()
        theme.apply_titlebar(self)

    # -- 作品下拉 ---------------------------------------------------------

    def _reload_works(self, select_id: int) -> None:
        """重建作品下拉 / Rebuild the works combo, keeping the selection."""
        try:
            found = repository.list_works(self._option_root)
        except OSError:
            found = []

        # 同一个作品可能在多个包里各有一份定义，下拉里只留第一条，
        # 否则一个作品会出现好几行，选哪一行都一样
        seen = set()
        self._works = []
        for works in found:
            if works.works_id in seen:
                continue
            seen.add(works.works_id)
            self._works.append(works)

        self._works_box.clear()
        for works in self._works:
            self._works_box.addItem(works.display, works)
        self._works_box.addItem("（不填）Invalid — 检索会受限", None)

        for row, works in enumerate(self._works):
            if works.works_id == select_id:
                self._works_box.setCurrentIndex(row)
                return
        if self._works:
            self._works_box.setCurrentIndex(0)

    def _selected_works(self) -> Optional[WorksItem]:
        """当前选中的作品 / The chosen works entry, or ``None`` for Invalid."""
        return self._works_box.currentData()

    def _add_works(self) -> None:
        """新建作品 / Create a works entry without leaving this dialog."""
        dialog = AddWorksDialog(self._option_root, self)
        if dialog.exec() == QDialog.Accepted and dialog.created:
            self._reload_works(dialog.created.works_id)

    def _manage_works(self) -> None:
        """打开作品库管理 / Open the works manager."""
        current = self._selected_works()
        dialog = ManageWorksDialog(self._option_root, self)
        dialog.exec()
        self._reload_works(current.works_id if current else repository.DEFAULT_AZUR_WORKS_ID)

    # -- 贴图 -------------------------------------------------------------

    def _template_dir(self) -> Optional[Path]:
        """模板贴图目录 / Where the reference textures live."""
        candidate = (Path(self._option_root) / repository.TEMPLATE_PACKAGE / "ddsImage"
                     / "ddsImage{}".format(repository.TEMPLATE_CHARACTER_ID))
        return candidate if candidate.is_dir() else None

    def _open_crop(self) -> None:
        """打开单图快速生成 / Open the quick-crop window."""
        dialog = CropDialog(self._crops, self._source_image, self._template_dir(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._source_image, self._crops = dialog.result_data()
        self._refresh_texture_rows()

    def _refresh_texture_rows(self) -> None:
        """把选好的图回填到三行说明上 / Reflect the chosen image in the rows."""
        if not self._source_image:
            for row in self._texture_labels.values():
                row.hide()
            self._texture_hint.show()
            return

        name = Path(self._source_image).name
        for key, _label, file_name, size, _default in PANES:
            row = self._texture_labels[key]
            row.setText("{} → {}（{}x{}）".format(name, file_name, size, size))
            row.show()
        self._texture_hint.hide()

    def _failed(self) -> bool:
        """现在是不是正显示着一条错误 / Whether an error is on screen."""
        return self._error.isVisible()

    # -- 提交 -------------------------------------------------------------

    def _update_final_id(self) -> None:
        """实时回显最终 ID / Echo the composed id as it is typed."""
        if not self._base_id.text().strip():
            self._final_id.setText("")
            self._final_id.setPlaceholderText("留空＝自动分配")
            return
        composed = repository.compose_character_id(self._base_id.text(), self._skin_id.text())
        self._final_id.setText(str(composed) if composed else "无效")

    def _confirm(self) -> None:
        """校验表单 / Validate before handing the request back."""
        if not self._name.text().strip():
            self._fail("角色名不能为空。")
            return

        if self._base_id.text().strip():
            composed = repository.compose_character_id(self._base_id.text(), self._skin_id.text())
            if composed is None:
                self._fail("基 ID 要是正整数、皮肤 ID 要在 0–9 之间；或者清空基 ID 让程序自动分配。")
                return
        self.accept()

    def _fail(self, message: str) -> None:
        """把错误摆在按钮上方 / Show the error next to the button that failed."""
        theme.set_wrapped_text(self._error, message)
        self._error.setStyleSheet("color: {};".format(theme.palette().error.text))
        self._error.show()

    def request(self) -> AddCharacterRequest:
        """
        表单填出来的东西 / The request this dialog composed.

        返回 / Returns:
            AddCharacterRequest: 直接喂给 :func:`core.repository.add_character`。
        """
        works = self._selected_works()
        composed = 0
        if self._base_id.text().strip():
            composed = repository.compose_character_id(
                self._base_id.text(), self._skin_id.text()) or 0

        name = self._name.text().strip()
        return AddCharacterRequest(
            character_id=composed,
            name=name,
            sort_name=name,
            illustrator_name=self._illustrator.text().strip(),
            works_id=works.works_id if works else 0,
            works_name=works.name if works else "",
            source_image_path=self._source_image,
            crops=self._crops,
        )


def _row(label: str, widget: QWidget) -> QHBoxLayout:
    """
    一行「标签 + 控件」/ One label-and-control row.

    标签是 ``body`` 加 ``text.primary``：规范 3.4 禁止把正常的行标题渲染成
    小号灰字。
    """
    row = QHBoxLayout()
    row.setSpacing(tokens.GAP_CONTROL)
    caption = theme.label(label, "body")
    caption.setFixedWidth(96)
    caption.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    caption.setBuddy(widget)
    row.addWidget(caption)
    widget.setAccessibleName(label)
    row.addWidget(widget, 1)
    return row


def _warning(text: str) -> QLabel:
    """
    组下面那句后果说明 / The consequence note below a section.

    这些不是装饰性说明，是「不这么做会怎样」——规范 7.2 的安全信息例外要求
    把后果写足，不能为了简洁删掉。
    """
    label = theme.wrapped_label(text, "secondary")
    label.setStyleSheet("color: {};".format(theme.palette().warning.text))
    return label
