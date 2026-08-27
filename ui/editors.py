# -*- coding: utf-8 -*-
"""
右侧的检查器面板 / The inspector panels on the right.

选中一首歌或一个角色，右边就展开对应的编辑面板。老版本（WinUI）用的是压着
半透明黑底的浮层，这里改成常驻的检查器——浮层会把整个列表压暗，而编辑的时候
恰恰要能同时看见列表；「系统设置」和 Finder 的简介栏都是这个做法。

面板只发信号，不自己写盘：保存、删除、打开目录全部回到主窗口去做，错误提示
才能走同一条状态条。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import ddspreview
from core.models import CharacterItem, MusicItem
from ui import cards, theme

#: 角色贴图预览的边长。
PREVIEW_SIZE = 260


class _Inspector(QFrame):
    """两个面板的共同骨架 / The shell both panels share."""

    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Group")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(theme.SPACE_WINDOW, theme.SPACE_WINDOW,
                                        theme.SPACE_WINDOW, theme.SPACE_WINDOW)
        self._layout.setSpacing(theme.SPACE_ROW)

        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_ROW)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("SectionTitle")
        self.title.setWordWrap(True)
        titles.addWidget(self.title)
        self.meta = theme.secondary_label("")
        self.meta.setWordWrap(True)
        titles.addWidget(self.meta)
        self.path = theme.footnote_label("")
        self.path.setWordWrap(True)
        titles.addWidget(self.path)
        header.addLayout(titles, 1)

        close = QPushButton("✕")
        close.setObjectName("Quiet")
        close.setFixedWidth(30)
        close.clicked.connect(self.closed.emit)
        header.addWidget(close, 0, Qt.AlignTop)
        self._layout.addLayout(header)

    def body(self) -> QVBoxLayout:
        """面板正文的布局 / The layout the subclass fills."""
        return self._layout


class SongInspector(_Inspector):
    """
    歌曲的谱面开关 / Per-chart enable toggles for one song.

    信号 / Signals:
        save_requested: 点了保存。
        delete_requested: 点了删除。
        open_requested: 点了打开目录。
    """

    save_requested = Signal()
    delete_requested = Signal()
    open_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.song: Optional[MusicItem] = None

        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_ROW)
        save = QPushButton("保存谱面开关")
        save.setObjectName("Primary")
        save.clicked.connect(self.save_requested.emit)
        actions.addWidget(save, 1)
        open_folder = QPushButton("打开目录")
        open_folder.clicked.connect(self.open_requested.emit)
        actions.addWidget(open_folder)
        delete = QPushButton("删除")
        delete.setObjectName("Destructive")
        delete.clicked.connect(self.delete_requested.emit)
        actions.addWidget(delete)
        self.body().addLayout(actions)

        self.body().addWidget(theme.field_label("谱面"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 8, 0)
        self._rows.setSpacing(6)
        scroll.setWidget(self._rows_host)
        self.body().addWidget(scroll, 1)

    def show_song(self, song: MusicItem) -> None:
        """摆一首歌进来 / Load one song into the panel."""
        self.song = song
        self.title.setText(song.title)
        self.meta.setText("ID {} · {} · {} · {}".format(
            song.song_id, song.package, song.genre or "无分类", song.artist or "无曲师"))
        self.path.setText(song.relative_path)

        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for chart in song.charts:
            self._rows.addWidget(self._build_row(chart))
        self._rows.addStretch(1)

    def _build_row(self, chart) -> QWidget:
        """一个难度一行 / One row per chart."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_ROW)

        chip = _DifficultyChip(chart.difficulty)
        layout.addWidget(chip)

        level = QLabel(chart.level_text)
        level.setObjectName("SectionTitle")
        level.setFixedWidth(46)
        level.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(level)

        texts = QVBoxLayout()
        texts.setSpacing(0)
        name = QLabel(chart.file_name or "（未填写文件名）")
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        texts.addWidget(name)
        problem = theme.footnote_label(chart.problem_text)
        if chart.enabled and not chart.file_exists:
            problem.setStyleSheet("color: {};".format(theme.SYSTEM["red"]))
        texts.addWidget(problem)
        layout.addLayout(texts, 1)

        switch = theme.Switch()
        switch.setChecked(chart.enabled)
        switch.toggled.connect(lambda value, target=chart: setattr(target, "enabled", value))
        layout.addWidget(switch)
        return row


class _DifficultyChip(QLabel):
    """难度小标签 / A difficulty chip, painted with the difficulty's own fill."""

    def __init__(self, name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(name, parent)
        self._name = name
        self.setFixedSize(104, 28)
        self.setAlignment(Qt.AlignCenter)

    def paintEvent(self, event) -> None:  # noqa: D102 - Qt 的绘制回调
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QPainter, QPen

        from core import difficulty

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(cards.difficulty_brush(rect, self._name))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QPen(QColor(difficulty.foreground(self._name))))
        painter.setFont(theme.font(theme.TYPE_CALLOUT, QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, self._name or "—")


class CharacterInspector(_Inspector):
    """
    角色的元数据编辑 / The character metadata form.

    信号 / Signals:
        save_requested: 点了保存。
        delete_requested: 点了删除。
        open_requested: 点了打开目录。
    """

    save_requested = Signal()
    delete_requested = Signal()
    open_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.character: Optional[CharacterItem] = None

        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_ROW)
        save = QPushButton("保存角色设置")
        save.setObjectName("Primary")
        save.clicked.connect(self.save_requested.emit)
        actions.addWidget(save, 1)
        open_folder = QPushButton("打开目录")
        open_folder.clicked.connect(self.open_requested.emit)
        actions.addWidget(open_folder)
        delete = QPushButton("删除")
        delete.setObjectName("Destructive")
        delete.clicked.connect(self.delete_requested.emit)
        actions.addWidget(delete)
        self.body().addLayout(actions)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        form = QVBoxLayout(host)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(theme.SPACE_GROUP)
        scroll.setWidget(host)
        self.body().addWidget(scroll, 1)

        picture = theme.Group()
        kind_row = QHBoxLayout()
        kind_row.setSpacing(theme.SPACE_ROW)
        kind_row.addWidget(theme.field_label("贴图"))
        self._kind = QComboBox()
        self._kind.addItem("big.dds（全身）", "big")
        self._kind.addItem("small.dds（半身）", "small")
        self._kind.addItem("thumb.dds（大头）", "thumb")
        self._kind.currentIndexChanged.connect(self._refresh_preview)
        kind_row.addWidget(self._kind, 1)
        picture.add_layout(kind_row)

        self._preview = QLabel("NO IMAGE")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setFixedHeight(PREVIEW_SIZE)
        self._preview.setStyleSheet("background: {}; border-radius: {}px; color: {};".format(
            theme.BG_CANVAS, theme.RADIUS_CONTROL, theme.LABEL_3))
        picture.add(self._preview)

        self._image_key = theme.footnote_label("")
        self._image_key.setWordWrap(True)
        picture.add(self._image_key)
        form.addWidget(picture)

        fields = theme.Group()
        self._name = _add_field(fields, "name / str")
        self._sort_name = _add_field(fields, "sortName")
        self._works_id = _add_field(fields, "works / id")
        self._works = _add_field(fields, "works / str")
        self._priority = _add_field(fields, "priority")
        self._rare_type = _add_field(fields, "rareType")
        self._release_tag_id = _add_field(fields, "releaseTagName / id")
        self._release_tag = _add_field(fields, "releaseTagName / str")
        self._net_open_id = _add_field(fields, "netOpenName / id")
        self._net_open = _add_field(fields, "netOpenName / str")
        self._illustrator_id = _add_field(fields, "illustratorName / id")
        self._illustrator = _add_field(fields, "illustratorName / str")
        form.addWidget(fields)

        switches = theme.Group()
        self._default_have = _add_switch(switches, "defaultHave")
        switches.add_separator()
        self._disable_flag = _add_switch(switches, "disableFlag")
        form.addWidget(switches)

        explain_group = theme.Group()
        explain_group.add(theme.field_label("explainText"))
        self._explain = QPlainTextEdit()
        self._explain.setFixedHeight(90)
        explain_group.add(self._explain)
        form.addWidget(explain_group)
        form.addStretch(1)

    def show_character(self, character: CharacterItem) -> None:
        """摆一个角色进来 / Load one character into the form."""
        self.character = character
        self.title.setText(character.name)
        self.meta.setText("ID {} · {} · priority {}".format(
            character.character_id, character.package, character.priority))
        self.path.setText(character.relative_path)

        self._name.setText(character.name)
        self._sort_name.setText(character.sort_name)
        self._works_id.setText(str(character.works_id))
        self._works.setText(character.works)
        self._priority.setText(str(character.priority))
        self._rare_type.setText(str(character.rare_type))
        self._release_tag_id.setText(str(character.release_tag_id))
        self._release_tag.setText(character.release_tag)
        self._net_open_id.setText(str(character.net_open_id))
        self._net_open.setText(character.net_open_name)
        self._illustrator_id.setText(str(character.illustrator_id))
        self._illustrator.setText(character.illustrator_name)
        self._explain.setPlainText(character.explain_text)
        self._default_have.setChecked(character.default_have)
        self._disable_flag.setChecked(character.disable_flag)

        self._image_key.setText("defaultImages={}\nDDSImage={}".format(
            character.image_key or "（空）", character.dds_relative_path or "未匹配"))
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """换一张贴图预览 / Swap the preview to the chosen texture."""
        if self.character is None:
            return
        path = self.character.image_path(self._kind.currentData())
        preview = ddspreview.preview_path(path, PREVIEW_SIZE * 2) if path else None
        if not preview:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("NO IMAGE")
            return
        pixmap = QPixmap(preview)
        if pixmap.isNull():
            self._preview.setPixmap(QPixmap())
            self._preview.setText("NO IMAGE")
            return
        self._preview.setPixmap(pixmap.scaled(
            self._preview.width() or PREVIEW_SIZE, PREVIEW_SIZE,
            Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def collect(self) -> Optional[str]:
        """
        把表单写回角色对象 / Push the form back into the character.

        返回 / Returns:
            Optional[str]: 有问题就是那条错误信息，一切正常是 ``None``。
            **写回是全有或全无的**：任何一个整数字段解析失败就整条放弃，
            不会留下改了一半的角色。
        """
        character = self.character
        if character is None:
            return "没有选中角色。"
        if not self._name.text().strip():
            return "角色名不能为空。"

        numbers = {}
        for key, widget, label in (
            ("works_id", self._works_id, "works id"),
            ("priority", self._priority, "priority"),
            ("rare_type", self._rare_type, "rareType"),
            ("release_tag_id", self._release_tag_id, "releaseTagName id"),
            ("net_open_id", self._net_open_id, "netOpenName id"),
            ("illustrator_id", self._illustrator_id, "illustratorName id"),
        ):
            try:
                numbers[key] = int(widget.text().strip())
            except ValueError:
                return "{} 必须是整数。".format(label)

        character.name = self._name.text().strip()
        character.sort_name = self._sort_name.text().strip() or character.name
        character.works = self._works.text().strip()
        character.release_tag = self._release_tag.text().strip()
        character.net_open_name = self._net_open.text().strip()
        character.illustrator_name = self._illustrator.text().strip()
        character.explain_text = self._explain.toPlainText()
        character.default_have = self._default_have.isChecked()
        character.disable_flag = self._disable_flag.isChecked()
        for key, value in numbers.items():
            setattr(character, key, value)
        return None


def _add_field(group: theme.Group, label: str) -> QLineEdit:
    """往分组里加一行输入框 / Append a captioned input to a group."""
    if group.layout().count():
        group.add_separator()
    row = QHBoxLayout()
    row.setSpacing(theme.SPACE_ROW)
    caption = theme.field_label(label)
    caption.setFixedWidth(132)
    row.addWidget(caption)
    widget = QLineEdit()
    row.addWidget(widget, 1)
    group.add_layout(row)
    return widget


def _add_switch(group: theme.Group, label: str) -> theme.Switch:
    """往分组里加一行开关 / Append a switch row to a group."""
    row = QHBoxLayout()
    row.setSpacing(theme.SPACE_ROW)
    row.addWidget(theme.field_label(label), 1)
    switch = theme.Switch()
    row.addWidget(switch)
    group.add_layout(row)
    return switch
