# -*- coding: utf-8 -*-
"""
右侧的检查器面板 / The inspector panels on the right.

选中一首歌或一个角色，右边就展开对应的编辑面板。老版本（WinUI）用的是压着
半透明黑底的浮层，这里改成常驻的检查器——浮层会把整个列表压暗，而编辑的时候
恰恰要能同时看见列表。

**面板本身是一层 Surface，里面不再套 Card。** 规范 3.4 的 Desktop 设置版式是
「Section 标题 + 行」，2.5 又说外层 Surface 已经提供清晰边界时再加 Card 只是
重复包裹——这个面板两条都占。

面板只发信号，不自己写盘：保存、删除、打开目录全部回到主窗口去做，错误提示
才能走同一条状态条。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import ddspreview, difficulty
from core.models import CharacterItem, MusicItem
from ui import cards, theme, tokens

#: 角色贴图预览的边长。
PREVIEW_SIZE = 240


class _Inspector(QWidget):
    """两个面板的共同骨架 / The shell both panels share."""

    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._panel = theme.panel()
        outer.addWidget(self._panel)

        self._layout = QVBoxLayout(self._panel)
        self._layout.setContentsMargins(
            tokens.PADDING_CONTAINER, tokens.PADDING_CONTAINER,
            tokens.PADDING_CONTAINER, tokens.PADDING_CONTAINER)
        self._layout.setSpacing(tokens.GAP_GROUP)

        header = QHBoxLayout()
        header.setSpacing(tokens.GAP_INLINE)
        titles = QVBoxLayout()
        titles.setSpacing(tokens.GAP_RELATED)
        self.title = theme.wrapped_label("", "title")
        titles.addWidget(self.title)
        self.meta = theme.wrapped_label("", "secondary")
        titles.addWidget(self.meta)
        self.path = theme.wrapped_label("", "mono")
        titles.addWidget(self.path)
        header.addLayout(titles, 1)

        close = theme.CloseButton()
        close.clicked.connect(self.closed.emit)
        header.addWidget(close, 0, Qt.AlignTop)
        self._layout.addLayout(header)

    def body(self) -> QVBoxLayout:
        """面板正文的布局 / The layout the subclass fills."""
        return self._layout

    def set_header(self, title: str, meta: str, path: str) -> None:
        """换一遍抬头 / Replace the three header lines."""
        theme.set_wrapped_text(self.title, title)
        theme.set_wrapped_text(self.meta, meta)
        theme.set_wrapped_text(self.path, path)


def _scroll_host() -> tuple:
    """
    一个可滚动的表单容器 / A scrollable form host.

    返回 / Returns:
        tuple: ``(QScrollArea, 里面那个 QVBoxLayout)``。Section 之间用
        ``gap.section`` 隔开，这是规范 3.4 定的距离。
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    host = QWidget()
    form = QVBoxLayout(host)
    # 右边留出焦点环的 4px，否则贴着滚动条的那一列控件焦点环会被裁掉
    form.setContentsMargins(tokens.FOCUS_RING_OFFSET + tokens.FOCUS_RING_WIDTH, 0,
                            tokens.GAP_CONTROL, 0)
    form.setSpacing(tokens.GAP_SECTION)
    scroll.setWidget(host)
    return scroll, form


def _actions_row(save_text: str, on_save, on_open, on_delete) -> QHBoxLayout:
    """
    面板顶上那排动作 / The action row every inspector shares.

    保存是这个面板唯一的 Primary。删除是破坏性动作：红字加红边，
    真正的后果说明在确认框里（规范 4.2 明确要求不能只靠颜色）。
    """
    row = QHBoxLayout()
    row.setSpacing(tokens.GAP_CONTROL)
    save = QPushButton(save_text)
    save.setObjectName("Primary")
    save.clicked.connect(on_save)
    row.addWidget(save, 1)
    open_folder = QPushButton("打开目录")
    open_folder.clicked.connect(on_open)
    row.addWidget(open_folder)
    delete = QPushButton("删除")
    delete.setObjectName("Destructive")
    delete.clicked.connect(on_delete)
    row.addWidget(delete)
    return row


class SongInspector(_Inspector):
    """
    歌曲的谱面开关 / Per-chart enable toggles for one song.

    开关改完要点保存才写盘。规范 5.2 说 Toggle 默认即时生效，但同一条也写着
    「会触发外部副作用的编辑使用明确提交」——这里每次保存都在改游戏自己的
    ``Music.xml`` 并留一份 ``.bak``，属于后者。

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

        self.body().addLayout(_actions_row(
            "保存谱面开关", self.save_requested.emit,
            self.open_requested.emit, self.delete_requested.emit))

        hint = theme.wrapped_label("开关改完要点保存才会写回 Music.xml。", "secondary")
        self.body().addWidget(hint)

        section = theme.Section("谱面")
        self.body().addWidget(section)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(tokens.FOCUS_RING_OFFSET + tokens.FOCUS_RING_WIDTH, 0,
                                      tokens.GAP_CONTROL, 0)
        self._rows.setSpacing(0)
        scroll.setWidget(self._rows_host)
        self.body().addWidget(scroll, 1)

    def show_song(self, song: MusicItem) -> None:
        """摆一首歌进来 / Load one song into the panel."""
        self.song = song
        self.set_header(song.title, "ID {} · {} · {} · {}".format(
            song.song_id, song.package, song.genre or "无分类", song.artist or "无曲师"),
            song.relative_path)

        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for index, chart in enumerate(song.charts):
            if index:
                self._rows.addWidget(theme.separator())
            self._rows.addWidget(self._build_row(chart))
        self._rows.addStretch(1)

    def _build_row(self, chart) -> QWidget:
        """一个难度一行 / One row per chart."""
        row = QWidget()
        row.setMinimumHeight(tokens.ROW_WITH_CAPTION_MIN_HEIGHT)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, tokens.GAP_RELATED, 0, tokens.GAP_RELATED)
        layout.setSpacing(tokens.GAP_CONTROL)

        layout.addWidget(_DifficultyChip(chart.difficulty))

        level = theme.label(chart.level_text, "sectionTitle")
        level.setFixedWidth(46)
        level.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(level)

        texts = QVBoxLayout()
        texts.setSpacing(tokens.GAP_RELATED)
        name = theme.label(chart.file_name or "未填写文件名", "body")
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        texts.addWidget(name)
        problem = theme.label(chart.problem_text, "secondary")
        if chart.enabled and not chart.file_exists:
            problem.setObjectName("")
            problem.setStyleSheet("color: {}; font-size: {}px;".format(
                theme.palette().error.text, theme.font_size("secondary")))
        texts.addWidget(problem)
        layout.addLayout(texts, 1)

        switch = theme.Switch()
        switch.setChecked(chart.enabled)
        switch.setAccessibleName("{} 谱面开关".format(chart.difficulty))
        switch.setToolTip("在游戏里显示这个难度")
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
        self.setAccessibleName("难度 {}".format(name or "未知"))

    def paintEvent(self, event) -> None:  # noqa: D102 - Qt 的绘制回调
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(cards.difficulty_brush(rect, self._name))
        painter.drawRoundedRect(rect, tokens.RADIUS_SMALL, tokens.RADIUS_SMALL)
        painter.setPen(QPen(QColor(difficulty.foreground(self._name))))
        font = theme.font("secondary")
        font.setWeight(QFont.Bold)
        painter.setFont(font)
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

        self.body().addLayout(_actions_row(
            "保存角色设置", self.save_requested.emit,
            self.open_requested.emit, self.delete_requested.emit))

        scroll, form = _scroll_host()
        self.body().addWidget(scroll, 1)

        picture = theme.Section("贴图")
        self._kind = theme.SegmentedControl()
        self._kind.add_item("全身", "big")
        self._kind.add_item("半身", "small")
        self._kind.add_item("大头", "thumb")
        self._kind.changed.connect(lambda _index: self._refresh_preview())
        picture.add_block(self._kind)

        self._preview = _TexturePreview()
        picture.add_block(self._preview)

        self._image_key = theme.wrapped_label("", "caption")
        picture.add_block(self._image_key)
        form.addWidget(picture)

        fields = theme.Section("字段")
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

        switches = theme.Section("开关")
        self._default_have = _add_switch(switches, "defaultHave")
        self._disable_flag = _add_switch(switches, "disableFlag")
        form.addWidget(switches)

        explain = theme.Section("explainText")
        self._explain = QPlainTextEdit()
        self._explain.setFixedHeight(90)
        explain.add_block(self._explain)
        form.addWidget(explain)
        form.addStretch(1)

    def show_character(self, character: CharacterItem) -> None:
        """摆一个角色进来 / Load one character into the form."""
        self.character = character
        self.set_header(character.name, "ID {} · {} · priority {}".format(
            character.character_id, character.package, character.priority),
            character.relative_path)

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
        self._clear_errors()

        theme.set_wrapped_text(self._image_key, "defaultImages={}\nDDSImage={}".format(
            character.image_key or "空", character.dds_relative_path or "未匹配"))
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """换一张贴图预览 / Swap the preview to the chosen texture."""
        if self.character is None:
            return
        path = self.character.image_path(self._kind.current_data())
        preview = ddspreview.preview_path(path, PREVIEW_SIZE * 2) if path else None
        pixmap = QPixmap(preview) if preview else QPixmap()
        self._preview.show_texture(None if pixmap.isNull() else pixmap)

    def _clear_errors(self) -> None:
        """把所有字段的报错状态收掉 / Drop every field's error state."""
        for widget in (self._works_id, self._priority, self._rare_type,
                       self._release_tag_id, self._net_open_id,
                       self._illustrator_id, self._name):
            _mark_invalid(widget, False)

    def collect(self) -> Optional[str]:
        """
        把表单写回角色对象 / Push the form back into the character.

        返回 / Returns:
            Optional[str]: 有问题就是那条错误信息，一切正常是 ``None``。
            **写回是全有或全无的**：任何一个整数字段解析失败就整条放弃，
            不会留下改了一半的角色。出问题的那个字段会被标红，
            这样错误信息和字段之间有对应关系，不只是一句话飘在别处。
        """
        character = self.character
        if character is None:
            return "没有选中角色。"
        self._clear_errors()

        if not self._name.text().strip():
            _mark_invalid(self._name, True)
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
                _mark_invalid(widget, True)
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


class _TexturePreview(QWidget):
    """
    贴图预览 / The texture preview.

    底是纯黑而不是 ``surfaceSunken``：判断贴图的透明边缘需要一个确定的深底，
    周围有底色会干扰判断，所以**浅色模式下它也是黑的**。这是内容不是 Surface，
    记在 ``tokens.IMAGE_BACKDROP``。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(PREVIEW_SIZE)
        self._pixmap: Optional[QPixmap] = None
        self.setAccessibleName("贴图预览")

    def show_texture(self, pixmap: Optional[QPixmap]) -> None:
        """换一张图 / Swap the shown texture, or clear it."""
        self._pixmap = pixmap
        self.setAccessibleDescription("无贴图" if pixmap is None else "已解码的贴图")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D102 - Qt 的绘制回调
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        body = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tokens.IMAGE_BACKDROP))
        painter.drawRoundedRect(body, tokens.RADIUS_SMALL, tokens.RADIUS_SMALL)

        if self._pixmap is None:
            painter.setPen(QPen(QColor(theme.palette().text_tertiary)))
            painter.setFont(theme.font("secondary"))
            painter.drawText(body, Qt.AlignCenter, "无贴图")
            return

        scaled = self._pixmap.scaled(self.width(), self.height(),
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(int((self.width() - scaled.width()) / 2),
                           int((self.height() - scaled.height()) / 2), scaled)


def _mark_invalid(widget: QLineEdit, invalid: bool) -> None:
    """
    把一个字段标成出错 / Flag one field as invalid.

    走属性选择器而不是直接 ``setStyleSheet``：内联样式表会把这个控件从主题里
    摘出去，换亮暗模式时它不跟着变。
    """
    widget.setProperty("invalid", "true" if invalid else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _add_field(section: theme.Section, label: str) -> QLineEdit:
    """
    往组里加一行输入框 / Append a labelled input to a section.

    标签用 ``body`` 加 ``text.primary``，不是小号灰字——规范 3.4 明确禁止用
    ``secondary`` / ``caption`` / 停用色渲染正常的行标题。
    """
    row = QHBoxLayout()
    row.setSpacing(tokens.GAP_CONTROL)
    caption = theme.label(label, "body")
    caption.setFixedWidth(136)
    row.addWidget(caption)
    widget = QLineEdit()
    widget.setAccessibleName(label)
    caption.setBuddy(widget)
    row.addWidget(widget, 1)
    section.add_layout(row)
    return widget


def _add_switch(section: theme.Section, label: str) -> theme.Switch:
    """往组里加一行开关 / Append a switch row to a section."""
    row = QHBoxLayout()
    row.setSpacing(tokens.GAP_CONTROL)
    row.addWidget(theme.label(label, "body"), 1)
    switch = theme.Switch()
    switch.setAccessibleName(label)
    row.addWidget(switch)
    section.add_layout(row)
    return switch
