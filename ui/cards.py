# -*- coding: utf-8 -*-
"""
列表怎么画 / How the lists draw themselves.

歌曲、角色、排查项都用 ``QStyledItemDelegate`` 自绘，而不是「一个条目一个
QWidget」：730 首歌各建一棵控件树，滚动会明显发涩，内存也不好看。自绘之后
只有可见的那十几行在画。

歌曲卡面刻意做成游戏内选曲画面的样子——难度色边框、LEVEL 小格、米白色曲名条。
认这个形状比认文字快。
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from core import difficulty
from ui import imagecache, theme

#: 条目对象挂在这个 role 上。
OBJECT_ROLE = Qt.UserRole + 1

#: 歌曲行、角色格的尺寸。
SONG_ROW_HEIGHT = 182
CHARACTER_TILE = QSize(224, 308)
ISSUE_ROW_HEIGHT = 96

#: 曲绘和立绘各自要多大的预览。按实际显示尺寸的两倍取，高分屏放大也不糊。
JACKET_PREVIEW = 256
PORTRAIT_PREVIEW = 512


class ObjectListModel(QAbstractListModel):
    """
    把一串 Python 对象挂进 QListView / A list model over plain Python objects.

    只提供一个 role：:data:`OBJECT_ROLE`，取出来就是原对象。展示逻辑全在
    delegate 里，模型不掺和。
    """

    def __init__(self, items: Optional[Sequence[Any]] = None, parent=None) -> None:
        super().__init__(parent)
        self._items: List[Any] = list(items or [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt 接口
        """行数 / Row count."""
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """取数据 / Fetch one item."""
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        if role in (OBJECT_ROLE, Qt.UserRole):
            return self._items[index.row()]
        return None

    def replace(self, items: Sequence[Any]) -> None:
        """整表换掉 / Swap the whole list."""
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def items(self) -> List[Any]:
        """当前这一串 / The current items."""
        return self._items

def difficulty_brush(rect: QRectF, name: str) -> QBrush:
    """
    难度色刷 / The fill for one difficulty.

    WORLD'S END 是彩虹渐变，其余是纯色——这是游戏里的约定，别改成纯色省事。
    """
    if difficulty.is_worlds_end(name):
        gradient = QLinearGradient(rect.left(), rect.center().y(), rect.right(), rect.center().y())
        for position, colour in difficulty.WORLDS_END_GRADIENT:
            gradient.setColorAt(position, QColor(colour))
        return QBrush(gradient)
    return QBrush(QColor(difficulty.colour(name)))


def _font(size: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    """按字体样式表取一档字 / One step of the type scale."""
    return theme.font(size, weight)


def _elide(text: str, font: QFont, width: int) -> str:
    """放不下就省略 / Elide to fit."""
    return QFontMetrics(font).elidedText(text or "", Qt.ElideRight, max(8, width))


def _draw_text(painter: QPainter, rect: QRect, text: str, font: QFont,
               colour: str, align: int = Qt.AlignLeft | Qt.AlignVCenter) -> None:
    """画一行会自动省略的文字 / Draw one elided line."""
    painter.setFont(font)
    painter.setPen(QPen(QColor(colour)))
    painter.drawText(rect, align, _elide(text, font, rect.width()))


def _draw_card(painter: QPainter, rect: QRectF, hovered: bool, selected: bool) -> None:
    """
    画卡片底 / The card background every row sits on.

    选中用主题色描边而不是刷满：一屏十几张卡，刷满会盖掉卡面本身的信息。
    """
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(theme.FILL if hovered else theme.BG_GROUP))
    painter.drawRoundedRect(rect, theme.RADIUS_GROUP, theme.RADIUS_GROUP)
    if selected:
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(theme.ACCENT), 2))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1),
                                theme.RADIUS_GROUP, theme.RADIUS_GROUP)


def _draw_cover(painter: QPainter, rect: QRect, pixmap: Optional[QPixmap],
                placeholder: str = "NO IMAGE") -> None:
    """
    画一张封面 / Draw a cover image, cropped to fill, or a placeholder.

    等比裁切填满而不是留黑边：曲绘和立绘都是方的，拉伸会让人一眼觉得不对。
    """
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#111827"))
    painter.drawRect(rect)

    if pixmap is None or pixmap.isNull():
        _draw_text(painter, rect, placeholder, _font(theme.TYPE_FOOTNOTE, QFont.DemiBold),
                   theme.LABEL_3, Qt.AlignCenter)
        return

    scale = max(rect.width() / pixmap.width(), rect.height() / pixmap.height())
    width = pixmap.width() * scale
    height = pixmap.height() * scale
    target = QRectF(rect.center().x() - width / 2, rect.center().y() - height / 2, width, height)
    painter.save()
    painter.setClipRect(rect)
    painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
    painter.restore()


def _draw_chip(painter: QPainter, x: int, y: int, name: str, height: int = 22) -> int:
    """
    画一个难度小标签 / Draw one difficulty chip; 返回它的右边界。
    """
    font = _font(theme.TYPE_CALLOUT, QFont.Bold)
    width = QFontMetrics(font).horizontalAdvance(name) + 16
    rect = QRectF(x, y, width, height)
    painter.setBrush(difficulty_brush(rect, name))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(rect, 4, 4)
    painter.setFont(font)
    painter.setPen(QPen(QColor(difficulty.foreground(name))))
    painter.drawText(rect, Qt.AlignCenter, name)
    return x + width + 6


class SongDelegate(QStyledItemDelegate):
    """一首歌一行 / One row per song."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        """行高固定 / Fixed row height."""
        return QSize(option.rect.width(), SONG_ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """画一行 / Paint one song row."""
        song = index.data(OBJECT_ROLE)
        if song is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        outer = QRectF(option.rect).adjusted(0, 0, -8, -10)
        hovered = bool(option.state & QStyle.State_MouseOver)
        selected = bool(option.state & QStyle.State_Selected)
        _draw_card(painter, outer, hovered, selected)

        body = outer.toRect().adjusted(14, 14, -14, -14)
        primary = song.primary_difficulty

        # --- 左边那张仿游戏内的曲绘卡 ---
        card = QRect(body.left(), body.center().y() - 77, 108, 154)
        painter.setPen(QPen(QColor("#CCFFFFFF"), 2))
        painter.setBrush(difficulty_brush(QRectF(card), primary))
        painter.drawRoundedRect(QRectF(card).adjusted(1, 1, -1, -1), 6, 6)

        inner = card.adjusted(6, 6, -6, -6)
        cover = QRect(inner.left(), inner.top(), inner.width(), 92)
        _draw_cover(painter, cover.adjusted(2, 2, -2, -2),
                    imagecache.instance().pixmap(song.jacket_path, JACKET_PREVIEW))
        painter.setPen(QPen(QColor("#F2FFFFFF"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(cover).adjusted(1, 1, -1, -1))

        strip = QRect(inner.left(), cover.bottom() + 1, inner.width(), 30)
        level_box = QRect(strip.left(), strip.top(), 32, strip.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#222B36"))
        painter.drawRect(level_box)
        _draw_text(painter, QRect(level_box.left(), level_box.top() + 2, level_box.width(), 10),
                   "LEVEL", _font(7, QFont.Bold), theme.LABEL_2, Qt.AlignCenter)
        _draw_text(painter, QRect(level_box.left(), level_box.top() + 10, level_box.width(), 18),
                   song.primary_level, _font(16, QFont.Black), theme.LABEL, Qt.AlignCenter)

        badge = QRect(level_box.right() + 1, strip.top(), strip.width() - 33, strip.height())
        painter.setBrush(difficulty_brush(QRectF(badge), primary))
        painter.drawRect(badge)
        _draw_text(painter, badge, primary, _font(theme.TYPE_CALLOUT, QFont.Black),
                   difficulty.foreground(primary), Qt.AlignCenter)

        name_bar = QRect(inner.left(), strip.bottom() + 1,
                         inner.width(), inner.bottom() - strip.bottom() - 1)
        painter.setBrush(QColor("#F8F5EA"))
        painter.drawRect(name_bar)
        _draw_text(painter, name_bar.adjusted(4, 0, -4, 0), song.title,
                   _font(theme.TYPE_FOOTNOTE, QFont.DemiBold), "#1A1A1A", Qt.AlignCenter)

        # --- 中间的文字 ---
        right_width = 130
        text_left = card.right() + 18
        text_width = body.right() - right_width - text_left
        top = body.top() + 18

        _draw_text(painter, QRect(text_left, top, text_width, 30), song.title,
                   _font(theme.TYPE_TITLE1, QFont.DemiBold), theme.LABEL)
        _draw_text(painter, QRect(text_left, top + 34, text_width, 20), song.card_sub_text,
                   _font(theme.TYPE_BODY), theme.LABEL_2)
        _draw_text(painter, QRect(text_left, top + 56, text_width, 18), song.relative_path,
                   _font(theme.TYPE_CALLOUT), theme.LABEL_3)

        chip_x = text_left
        chip_limit = text_left + text_width
        for chart in song.enabled_charts:
            if chip_x > chip_limit - 40:
                break
            chip_x = _draw_chip(painter, chip_x, top + 82, chart.difficulty)

        # --- 右边的难度和定数 ---
        right = QRect(body.right() - right_width, body.top() + 24, right_width, body.height() - 48)
        _draw_text(painter, QRect(right.left(), right.top(), right.width(), 20), primary,
                   _font(theme.TYPE_BODY, QFont.Bold), difficulty.colour(primary)
                   if not difficulty.is_worlds_end(primary) else theme.LABEL,
                   Qt.AlignRight | Qt.AlignVCenter)
        _draw_text(painter, QRect(right.left(), right.top() + 22, right.width(), 44),
                   song.primary_level, _font(34, QFont.Black), theme.LABEL,
                   Qt.AlignRight | Qt.AlignVCenter)
        if song.has_missing_enabled_file:
            _draw_text(painter, QRect(right.left(), right.top() + 70, right.width(), 18),
                       "谱面文件缺失", _font(theme.TYPE_CALLOUT, QFont.DemiBold),
                       theme.SYSTEM["red"], Qt.AlignRight | Qt.AlignVCenter)

        painter.restore()


class CharacterDelegate(QStyledItemDelegate):
    """一个角色一格 / One tile per character."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        """格子固定大小 / Fixed tile size."""
        return CHARACTER_TILE

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """画一格 / Paint one character tile."""
        character = index.data(OBJECT_ROLE)
        if character is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        outer = QRectF(option.rect).adjusted(6, 6, -6, -6)
        hovered = bool(option.state & QStyle.State_MouseOver)
        selected = bool(option.state & QStyle.State_Selected)
        _draw_card(painter, outer, hovered, selected)

        body = outer.toRect().adjusted(10, 10, -10, -10)
        cover = QRect(body.left(), body.top(), body.width(), 200)
        painter.save()
        painter.setClipPath(theme.rounded_path(QRectF(cover), theme.RADIUS_CONTROL))
        _draw_cover(painter, cover,
                    imagecache.instance().pixmap(character.big_image_path, PORTRAIT_PREVIEW))
        painter.restore()

        _draw_text(painter, QRect(body.left(), cover.bottom() + 10, body.width(), 24),
                   character.name, _font(theme.TYPE_TITLE2, QFont.DemiBold), theme.LABEL)
        _draw_text(painter, QRect(body.left(), cover.bottom() + 34, body.width(), 20),
                   character.works or "（无作品）", _font(theme.TYPE_BODY), theme.LABEL_2)
        _draw_text(painter, QRect(body.left(), cover.bottom() + 54, body.width(), 18),
                   "ID {} · {}".format(character.character_id, character.package),
                   _font(theme.TYPE_FOOTNOTE), theme.LABEL_3)

        painter.restore()


class IssueDelegate(QStyledItemDelegate):
    """一条排查项一行 / One row per issue."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        """行高固定 / Fixed row height."""
        return QSize(option.rect.width(), ISSUE_ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """画一行 / Paint one issue row."""
        issue = index.data(OBJECT_ROLE)
        if issue is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        outer = QRectF(option.rect).adjusted(0, 0, -8, -8)
        hovered = bool(option.state & QStyle.State_MouseOver)
        _draw_card(painter, outer, hovered, False)

        body = outer.toRect().adjusted(14, 12, -14, -12)
        colour = theme.SEVERITY_COLOURS.get(issue.severity, theme.SYSTEM["gray"])
        name = theme.SEVERITY_NAMES.get(issue.severity, issue.severity)

        # 左边一条竖色条 + 一个词。颜色单独用不行，色盲看不出，所以字也写上
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colour))
        painter.drawRoundedRect(QRectF(body.left(), body.top(), 3, body.height()), 1.5, 1.5)
        _draw_text(painter, QRect(body.left() + 12, body.top(), 52, 20), name,
                   _font(theme.TYPE_BODY, QFont.Bold), colour)

        text_left = body.left() + 74
        text_width = body.width() - 74
        _draw_text(painter, QRect(text_left, body.top(), text_width, 22), issue.title,
                   _font(theme.TYPE_BODY, QFont.DemiBold), theme.LABEL)
        _draw_text(painter, QRect(text_left, body.top() + 24, text_width, 20), issue.detail,
                   _font(theme.TYPE_CALLOUT), theme.LABEL_2)
        _draw_text(painter, QRect(text_left, body.top() + 46, text_width, 18), issue.path,
                   _font(theme.TYPE_FOOTNOTE), theme.LABEL_3)

        painter.restore()
