# -*- coding: utf-8 -*-
"""
列表怎么画 / How the lists draw themselves.

歌曲、角色、排查项都用 ``QStyledItemDelegate`` 自绘，而不是「一个条目一个
QWidget」：730 首歌各建一棵控件树，滚动会明显发涩，内存也不好看。自绘之后
只有可见的那十几行在画。

**歌曲和排查是长列表，画成行；角色是网格，画成 Card。** 规范 2.5 的判断框架里，
「高密度、需要快速纵向扫描的长列表」倾向直接布局，「可整体点击、选择的对象」
倾向 Card——这两条正好把三个列表分成了两种画法。

歌曲行左边那张仿游戏内选曲画面的卡片是**内容**不是 UI：颜色和字号走
``tokens.GAME_CARD``，不跟着亮暗模式变。跟着变反而认不出来了。
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
from ui import imagecache, theme, tokens

#: 条目对象挂在这个 role 上。
OBJECT_ROLE = Qt.UserRole + 1

#: 歌曲行、角色格的尺寸。行高要装得下那张仿游戏卡面加上下的 gap.group。
SONG_ROW_HEIGHT = 196
CHARACTER_TILE = QSize(224, 312)
ISSUE_ROW_HEIGHT = 88

#: 曲绘和立绘各自要多大的预览。按实际显示尺寸的两倍取，高分屏放大也不糊。
JACKET_PREVIEW = 256
PORTRAIT_PREVIEW = 512


class ObjectListModel(QAbstractListModel):
    """
    把一串 Python 对象挂进 QListView / A list model over plain Python objects.

    展示逻辑全在 delegate 里，模型不掺和。但 ``DisplayRole`` 和
    ``AccessibleTextRole`` 必须给：自绘的 delegate 不产生任何可读文本，
    模型再不给的话，整个列表在读屏软件下就是空的。
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
        item = self._items[index.row()]
        if role in (OBJECT_ROLE, Qt.UserRole):
            return item
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
            return describe(item)
        return None

    def replace(self, items: Sequence[Any]) -> None:
        """整表换掉 / Swap the whole list."""
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def items(self) -> List[Any]:
        """当前这一串 / The current items."""
        return self._items


def describe(item: Any) -> str:
    """
    一条给读屏软件念的摘要 / One spoken summary of a row.

    参数 / Parameters:
        item (Any): 歌曲、角色或排查项。

    返回 / Returns:
        str: 把卡面上画出来的信息压成一行。画面上有什么，这里就得念到什么，
        否则用键盘和读屏走这个列表的人拿不到画上的内容。
    """
    if hasattr(item, "charts"):
        text = "{}，{} {}".format(item.title, item.primary_difficulty, item.primary_level)
        if item.card_sub_text:
            text += "，" + item.card_sub_text
        if item.has_missing_enabled_file:
            text += "，谱面文件缺失"
        return text
    if hasattr(item, "character_id"):
        return "{}，{}，ID {}，{}".format(
            item.name, item.works or "无作品", item.character_id, item.package)
    if hasattr(item, "severity"):
        return "{}：{}。{}".format(
            SEVERITY_NAMES.get(item.severity, item.severity), item.title, item.detail)
    return str(item)


#: 排查项严重程度到语义色族的映射。红只表示「会让游戏读不到东西」，别滥用。
SEVERITY_SEMANTICS = {"High": "error", "Medium": "warning", "Low": "info"}

#: 严重程度的中文说法。颜色不是唯一载体，这个词一定跟着色条一起出现。
SEVERITY_NAMES = {"High": "严重", "Medium": "注意", "Low": "提示", "Info": "信息"}


def severity_colours(severity: str) -> tuple:
    """
    一条排查项该用什么颜色 / The fill and border for one severity.

    参数 / Parameters:
        severity (str): ``High`` / ``Medium`` / ``Low`` / ``Info``。

    返回 / Returns:
        tuple: ``(文字色, 描边色)``。描边是给色条补对比度用的——浅色模式下的
        琥珀色块自己达不到 3:1，规范 2.1 要求用同族 border 补足，
        不靠放大面积或提高饱和度硬凑。
    """
    active = theme.palette()
    family = SEVERITY_SEMANTICS.get(severity)
    if family is None:
        return active.text_tertiary, active.separator_strong
    semantic = active.semantic(family)
    return semantic.text, semantic.border


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


def _game_font(size: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    """
    游戏卡面上的字 / One of the replica card's own sizes.

    这几档**不在字阶表里**，它们复刻的是游戏画面。字族仍然要显式设，
    否则自绘出来是一屏方框。
    """
    value = QFont()
    value.setFamilies([theme.font("body").families()[0]])
    value.setPixelSize(size)
    value.setWeight(weight)
    return value


def _elide(text: str, font: QFont, width: int) -> str:
    """放不下就省略 / Elide to fit."""
    return QFontMetrics(font).elidedText(text or "", Qt.ElideRight, max(8, width))


def _draw_text(painter: QPainter, rect: QRect, text: str, font: QFont,
               colour: str, align: int = Qt.AlignLeft | Qt.AlignVCenter) -> None:
    """画一行会自动省略的文字 / Draw one elided line."""
    painter.setFont(font)
    painter.setPen(QPen(QColor(colour)))
    painter.drawText(rect, align, _elide(text, font, rect.width()))


def _row_background(painter: QPainter, rect: QRectF, hovered: bool, selected: bool,
                    focused: bool) -> None:
    """
    长列表的一行 / One row of a long, scannable list.

    行背景加一条分隔线，不做圆角卡片——规范 2.5 把「高密度、需要快速纵向扫描的
    长列表」判给直接布局。选中态用 accent.subtle 加左侧一条 accent 竖条：
    颜色之外还有位置这个第二线索。
    """
    p = theme.palette()
    painter.setPen(Qt.NoPen)
    if selected:
        painter.setBrush(QColor(p.accent_subtle))
    elif hovered:
        painter.setBrush(QColor(p.fill_hover))
    else:
        painter.setBrush(Qt.NoBrush)
    if selected or hovered:
        painter.drawRect(rect)

    if selected:
        painter.setBrush(QColor(p.accent_primary))
        painter.drawRect(QRectF(rect.left(), rect.top(), 3, rect.height()))

    painter.setPen(QPen(QColor(p.separator_subtle), 1))
    painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

    if focused:
        theme.paint_focus_ring(painter, rect.adjusted(3, 3, -3, -3), tokens.RADIUS_SMALL)


def _text_colours(hovered: bool, selected: bool) -> tuple:
    """
    这一行的三档文字色 / The three text colours for one row.

    规范 2.1：``fill.hover`` 和 ``fill.pressed`` 不在文字承载面集合里，
    **整行 hover 或 pressed 时行内辅助文字要提升为** ``text.secondary``。
    """
    p = theme.palette()
    if hovered and not selected:
        return p.text_primary, p.text_secondary, p.text_secondary
    return p.text_primary, p.text_secondary, p.text_tertiary


def _draw_cover(painter: QPainter, rect: QRect, pixmap: Optional[QPixmap],
                placeholder: str = "无贴图") -> None:
    """
    画一张封面 / Draw a cover image, cropped to fill, or a placeholder.

    等比裁切填满而不是留黑边：曲绘和立绘都是方的，拉伸会让人一眼觉得不对。
    """
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(tokens.GAME_CARD["cover_backdrop"]))
    painter.drawRect(rect)

    if pixmap is None or pixmap.isNull():
        _draw_text(painter, rect, placeholder, theme.font("caption"),
                   theme.palette().text_tertiary, Qt.AlignCenter)
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
    font = theme.font("secondary")
    font.setWeight(QFont.Bold)
    width = QFontMetrics(font).horizontalAdvance(name) + 2 * tokens.PADDING_CONTROL_X
    rect = QRectF(x, y, width, height)
    painter.setBrush(difficulty_brush(rect, name))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(rect, tokens.RADIUS_SMALL, tokens.RADIUS_SMALL)
    painter.setFont(font)
    painter.setPen(QPen(QColor(difficulty.foreground(name))))
    painter.drawText(rect, Qt.AlignCenter, name)
    return int(x + width + tokens.GAP_RELATED)


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

        outer = QRectF(option.rect)
        hovered = bool(option.state & QStyle.State_MouseOver)
        selected = bool(option.state & QStyle.State_Selected)
        focused = bool(option.state & QStyle.State_HasFocus)
        _row_background(painter, outer, hovered, selected, focused)
        primary_text, secondary_text, tertiary_text = _text_colours(hovered, selected)

        body = outer.toRect().adjusted(tokens.PADDING_CONTAINER, tokens.GAP_GROUP,
                                       -tokens.PADDING_CONTAINER, -tokens.GAP_GROUP)
        primary = song.primary_difficulty

        # --- 左边那张仿游戏内的曲绘卡（内容复刻，不走 UI Token）---
        art = tokens.GAME_CARD_LAYOUT
        card = QRect(body.left(), body.center().y() - art["height"] // 2,
                     art["width"], art["height"])
        painter.setPen(QPen(QColor(tokens.GAME_CARD["frame"]), 2))
        painter.setBrush(difficulty_brush(QRectF(card), primary))
        painter.drawRoundedRect(QRectF(card).adjusted(1, 1, -1, -1),
                                tokens.RADIUS_SMALL, tokens.RADIUS_SMALL)

        pad = art["padding"]
        inner = card.adjusted(pad, pad, -pad, -pad)
        cover = QRect(inner.left(), inner.top(), inner.width(), art["cover_height"])
        _draw_cover(painter, cover.adjusted(2, 2, -2, -2),
                    imagecache.instance().pixmap(song.jacket_path, JACKET_PREVIEW))
        painter.setPen(QPen(QColor(tokens.GAME_CARD["cover_frame"]), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(cover).adjusted(1, 1, -1, -1))

        strip = QRect(inner.left(), cover.bottom() + 1, inner.width(), art["strip_height"])
        level_box = QRect(strip.left(), strip.top(), art["level_width"], strip.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tokens.GAME_CARD["level_box"]))
        painter.drawRect(level_box)
        _draw_text(painter, QRect(level_box.left(), level_box.top() + 2, level_box.width(), 9),
                   "LEVEL", _game_font(tokens.GAME_CARD_TYPE["level_caption"], QFont.Bold),
                   tokens.GAME_CARD["name_bar"], Qt.AlignCenter)
        _draw_text(painter, QRect(level_box.left(), level_box.top() + 11, level_box.width(), 15),
                   song.primary_level, _game_font(tokens.GAME_CARD_TYPE["level_value"], QFont.Black),
                   tokens.GAME_CARD["name_bar"], Qt.AlignCenter)

        badge = QRect(level_box.right() + 1, strip.top(),
                      strip.width() - art["level_width"] - 1, strip.height())
        painter.setBrush(difficulty_brush(QRectF(badge), primary))
        painter.drawRect(badge)
        _draw_text(painter, badge, primary,
                   _game_font(tokens.GAME_CARD_TYPE["difficulty"], QFont.Black),
                   difficulty.foreground(primary), Qt.AlignCenter)

        name_bar = QRect(inner.left(), strip.bottom() + 1,
                         inner.width(), inner.bottom() - strip.bottom() - 1)
        painter.setBrush(QColor(tokens.GAME_CARD["name_bar"]))
        painter.drawRect(name_bar)
        _draw_text(painter, name_bar.adjusted(4, 0, -4, 0), song.title,
                   _game_font(tokens.GAME_CARD_TYPE["title"], QFont.DemiBold),
                   tokens.GAME_CARD["name_text"], Qt.AlignCenter)

        # --- 中间的文字 ---
        right_width = 132
        text_left = card.right() + tokens.GAP_GROUP
        text_width = body.right() - right_width - text_left
        top = body.top() + tokens.GAP_CONTROL

        _draw_text(painter, QRect(text_left, top, text_width, theme.line_height("title")),
                   song.title, theme.font("title"), primary_text)
        _draw_text(painter, QRect(text_left, top + theme.line_height("title") + tokens.GAP_RELATED,
                                  text_width, theme.line_height("body")),
                   song.card_sub_text, theme.font("body"), secondary_text)
        _draw_text(painter, QRect(text_left,
                                  top + theme.line_height("title")
                                  + theme.line_height("body") + 2 * tokens.GAP_RELATED,
                                  text_width, theme.line_height("mono")),
                   song.relative_path, theme.font("mono"), tertiary_text)

        chip_x = text_left
        chip_limit = text_left + text_width
        for chart in song.enabled_charts:
            if chip_x > chip_limit - 40:
                break
            chip_x = _draw_chip(painter, chip_x, body.bottom() - 30, chart.difficulty)

        # --- 右边的难度和定数 ---
        right = QRect(body.right() - right_width, body.top() + tokens.GAP_CONTROL,
                      right_width, body.height() - 2 * tokens.GAP_CONTROL)
        difficulty_colour = (primary_text if difficulty.is_worlds_end(primary)
                             else difficulty.colour(primary))
        chart_font = theme.font("body")
        chart_font.setWeight(QFont.Bold)
        _draw_text(painter, QRect(right.left(), right.top(), right.width(),
                                  theme.line_height("body")),
                   primary, chart_font, difficulty_colour, Qt.AlignRight | Qt.AlignVCenter)
        _draw_text(painter, QRect(right.left(), right.top() + theme.line_height("body"),
                                  right.width(), theme.line_height("metric")),
                   song.primary_level, theme.font("metric"), primary_text,
                   Qt.AlignRight | Qt.AlignVCenter)
        if song.has_missing_enabled_file:
            warn_font = theme.font("secondary")
            warn_font.setWeight(QFont.DemiBold)
            _draw_text(painter, QRect(right.left(),
                                      right.top() + theme.line_height("body")
                                      + theme.line_height("metric") + tokens.GAP_RELATED,
                                      right.width(), theme.line_height("secondary")),
                       "谱面文件缺失", warn_font, theme.palette().error.text,
                       Qt.AlignRight | Qt.AlignVCenter)

        painter.restore()


class CharacterDelegate(QStyledItemDelegate):
    """
    一个角色一格 / One card per character.

    这个用 Card：一格就是一个可以整体点选的对象，规范 2.5 判断框架里明确
    倾向 Card 的那一类。起点是 ``surface + radius.large + 无阴影``，
    实测 surface 与 canvas 的对比度只有 1.04 / 1.07，低于 1.1:1，
    所以补一条 ``separator.subtle`` 的边。
    """

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        """格子固定大小 / Fixed tile size."""
        return CHARACTER_TILE

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """画一格 / Paint one character card."""
        character = index.data(OBJECT_ROLE)
        if character is None:
            return

        p = theme.palette()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        margin = tokens.GAP_CONTROL
        outer = QRectF(option.rect).adjusted(margin, margin, -margin, -margin)
        hovered = bool(option.state & QStyle.State_MouseOver)
        selected = bool(option.state & QStyle.State_Selected)
        focused = bool(option.state & QStyle.State_HasFocus)

        if selected:
            fill, border, width = p.accent_subtle, p.accent_primary, 2
        elif hovered:
            fill, border, width = p.fill_hover, p.separator_strong, 1
        else:
            fill, border, width = p.surface, p.separator_subtle, 1
        painter.setBrush(QColor(fill))
        painter.setPen(QPen(QColor(border), width))
        painter.drawRoundedRect(outer.adjusted(width / 2, width / 2, -width / 2, -width / 2),
                                tokens.RADIUS_LARGE, tokens.RADIUS_LARGE)

        body = outer.toRect().adjusted(tokens.PADDING_CONTAINER, tokens.PADDING_CONTAINER,
                                       -tokens.PADDING_CONTAINER, -tokens.PADDING_CONTAINER)
        cover = QRect(body.left(), body.top(), body.width(), 190)
        painter.save()
        # 内层圆角比外层小一档（规范 2.4）
        painter.setClipPath(theme.rounded_path(QRectF(cover), tokens.RADIUS_MEDIUM))
        _draw_cover(painter, cover,
                    imagecache.instance().pixmap(character.big_image_path, PORTRAIT_PREVIEW))
        painter.restore()

        primary_text, secondary_text, tertiary_text = _text_colours(hovered, selected)
        cursor = cover.bottom() + tokens.GAP_GROUP
        _draw_text(painter, QRect(body.left(), cursor, body.width(), theme.line_height("title")),
                   character.name, theme.font("title"), primary_text)
        cursor += theme.line_height("title") + tokens.GAP_RELATED
        _draw_text(painter, QRect(body.left(), cursor, body.width(), theme.line_height("body")),
                   character.works or "无作品", theme.font("body"), secondary_text)
        cursor += theme.line_height("body") + tokens.GAP_RELATED
        _draw_text(painter, QRect(body.left(), cursor, body.width(), theme.line_height("caption")),
                   "ID {} · {}".format(character.character_id, character.package),
                   theme.font("caption"), tertiary_text)

        if focused:
            theme.paint_focus_ring(painter, outer, tokens.RADIUS_LARGE)

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

        outer = QRectF(option.rect)
        hovered = bool(option.state & QStyle.State_MouseOver)
        _row_background(painter, outer, hovered, False, False)
        primary_text, secondary_text, tertiary_text = _text_colours(hovered, False)

        body = outer.toRect().adjusted(tokens.PADDING_CONTAINER, tokens.GAP_CONTROL,
                                       -tokens.PADDING_CONTAINER, -tokens.GAP_CONTROL)
        text_colour, border_colour = severity_colours(issue.severity)
        name = SEVERITY_NAMES.get(issue.severity, issue.severity)

        # 左边一条竖色条 + 一个词。色条自己在浅色模式下达不到 3:1，
        # 按规范 2.1 用同族 border 描边补足；颜色之外还有那个词兜底。
        bar = QRectF(body.left(), body.top(), 4, body.height())
        painter.setPen(QPen(QColor(border_colour), 1))
        painter.setBrush(QColor(text_colour))
        painter.drawRoundedRect(bar, 2, 2)

        label_font = theme.font("body")
        label_font.setWeight(QFont.DemiBold)
        _draw_text(painter, QRect(body.left() + 14, body.top(), 52, theme.line_height("body")),
                   name, label_font, text_colour)

        text_left = body.left() + 72
        text_width = body.width() - 72
        cursor = body.top()
        title_font = theme.font("body")
        title_font.setWeight(QFont.DemiBold)
        _draw_text(painter, QRect(text_left, cursor, text_width, theme.line_height("body")),
                   issue.title, title_font, primary_text)
        cursor += theme.line_height("body") + tokens.GAP_RELATED
        _draw_text(painter, QRect(text_left, cursor, text_width, theme.line_height("secondary")),
                   issue.detail, theme.font("secondary"), secondary_text)
        cursor += theme.line_height("secondary") + tokens.GAP_RELATED
        _draw_text(painter, QRect(text_left, cursor, text_width, theme.line_height("mono")),
                   issue.path, theme.font("mono"), tertiary_text)

        painter.restore()
