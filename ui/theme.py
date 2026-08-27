# -*- coding: utf-8 -*-
"""
界面的外观 / Look and feel.

**照 Apple Human Interface Guidelines 做的深色界面**：系统语义色、macOS 的字体
样式表、inset grouped 版式、控件 6px / 容器 10px 的圆角、8pt 间距网格。
所有颜色和字号常量只在这个文件里出现一次，别处一律引用。

主题色是**紫罗兰 #B44BFF**，这个项目认领的那一支。写死的只有 :data:`ACCENT`
一行，hover / pressed / 半透明态全从它推导——换主色只改一行，不会漏掉某个
状态还留着上一版的颜色。

⚠️ **绝对不要写 ``QWidget { background: ... }``**。QSS 的类型选择器连子类一起
命中，那一条会把每个 QLabel 都刷上底色，在卡片上显示成一条条横杠。背景只画在
真正需要的容器上（窗口、分组框、卡片）。
"""

from __future__ import annotations

import os
import sys
from typing import Dict, Optional

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QVBoxLayout, QWidget


def mix(colour: str, other: str, ratio: float) -> str:
    """
    两个 ``#RRGGBB`` 按比例混合 / Blend two hex colours.

    参数 / Parameters:
        colour (str): 打底的颜色。
        other (str): 往里掺的颜色。
        ratio (float): 掺多少，0 到 1。

    返回 / Returns:
        str: ``#RRGGBB``（大写）。
    """
    base = [int(colour[index:index + 2], 16) for index in (1, 3, 5)]
    into = [int(other[index:index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join("{:02X}".format(round(a + (b - a) * ratio)) for a, b in zip(base, into))


def tint(colour: str, alpha: float) -> str:
    """
    ``#RRGGBB`` 变成 QSS 认的 ``rgba(...)`` / Hex to the rgba() form QSS wants.

    Qt 的 QSS 解析器对八位十六进制（``#RRGGBBAA``）不可靠，半透明一律写 rgba。
    """
    red, green, blue = (int(colour[index:index + 2], 16) for index in (1, 3, 5))
    return "rgba({}, {}, {}, {:.2f})".format(red, green, blue, alpha)


#: 系统语义色（Apple 深色模式取值）。按**用途**选，不按好看选：
#: 绿=成功、橙=注意、红=破坏性、灰=停用。
SYSTEM: Dict[str, str] = {
    "blue": "#0A84FF",
    "green": "#30D158",
    "orange": "#FF9F0A",
    "red": "#FF453A",
    "yellow": "#FFD60A",
    "gray": "#8E8E93",
}

#: 主题色。**一个项目一种**，本项目是紫罗兰（表在全局 CLAUDE.md 第 9 条）。
ACCENT = "#B44BFF"
ACCENT_HOVER = mix(ACCENT, "#FFFFFF", 0.14)
ACCENT_PRESSED = mix(ACCENT, "#000000", 0.14)
#: 选中态的淡底。筛选器、导航项这类可切换的东西用它——实心主题色留给
#: 「当前这一步的确认动作」，一屏上出现两个以上就没有重点了。
ACCENT_SOFT = tint(ACCENT, 0.22)
#: 主题色填充上的字。白字对这支紫 3.90:1，黑字 5.39:1，差不多，白的更像平台惯例。
ON_ACCENT = "#FFFFFF"

#: 背景三层：窗口底 → 分组框 → 框里凹进去的输入框。层级只有三档，多了分不清。
BG_WINDOW = "#1C1C1E"
BG_GROUP = "#2C2C2E"
BG_FIELD = "#1C1C1E"
#: 看图区。贴图必须落在纯黑上，周围有底色会干扰对透明边缘的判断。
BG_CANVAS = "#000000"

#: 填充色三档（HIG 的 systemFill），已经和分组框叠算成不透明值。
FILL = "#3A3A3C"
FILL_HOVER = "#48484A"
FILL_PRESSED = "#545456"
FILL_DISABLED = "#323234"

#: 分割线。Apple 的 separator 就是一条一像素的淡灰，不是描边。
SEPARATOR = "#3A3A3C"

#: 文字四档，对应 HIG 的 label…quaternaryLabel。
LABEL = "#FFFFFF"
LABEL_2 = "#98989F"
LABEL_3 = "#6C6C70"
LABEL_4 = "#48484A"

#: 字体。SF 在 macOS 上直接命中，Windows 退到 Segoe UI Variable，中文再退到
#: 苹方 / 微软雅黑。Qt 不认 CSS 的 ``-apple-system``，别写。
FONT_FAMILIES = ["SF Pro Text", "Segoe UI Variable Text", "Segoe UI",
                 "PingFang SC", "Microsoft YaHei"]
FONT_SANS = ", ".join('"{}"'.format(name) for name in FONT_FAMILIES) + ", sans-serif"

#: macOS 的字体样式表。别在别处随手写字号，从这张表里挑一档。
TYPE_TITLE1 = 22
TYPE_TITLE2 = 17
TYPE_TITLE3 = 15
TYPE_BODY = 13
TYPE_CALLOUT = 12
TYPE_SUBHEAD = 11
TYPE_FOOTNOTE = 10

#: 圆角：控件 6，容器 10。小控件用小圆角，容器才用大的。
RADIUS_CONTROL = 6
RADIUS_GROUP = 10

#: 间距按 8 的倍数走（HIG 的 8pt grid）。
SPACE_WINDOW = 16
SPACE_GROUP = 16
SPACE_ROW = 8

#: 一行控件的最小高度。行与行之间只有一条分割线，间隙全靠这个数减去控件本身
#: 的高度撑出来；给小了两行控件会黏成一条竖杠。
ROW_HEIGHT = 32

#: 排查项严重程度的配色。红只表示「会让游戏读不到东西」，别滥用。
SEVERITY_COLOURS: Dict[str, str] = {
    "High": SYSTEM["red"],
    "Medium": SYSTEM["orange"],
    "Low": SYSTEM["yellow"],
    "Info": SYSTEM["gray"],
}

#: 严重程度的中文说法。
SEVERITY_NAMES: Dict[str, str] = {
    "High": "严重",
    "Medium": "注意",
    "Low": "提示",
    "Info": "信息",
}


def font(size_px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    """
    按字体样式表取一档字 / One step of the type scale, as a QFont.

    **字族必须显式设**：自绘的 delegate 不吃 QSS，``QFont()`` 拿到的是 Qt 的默认
    字体，那上面可能一个中文字形都没有，画出来整屏是方框（离屏渲染下连拉丁字母
    都会变方框）。

    参数 / Parameters:
        size_px (int): 从 :data:`TYPE_BODY` 那几档里挑一个。
        weight (QFont.Weight): 字重。

    返回 / Returns:
        QFont: 设好字族和像素大小的字体。
    """
    value = QFont()
    value.setFamilies(FONT_FAMILIES)
    value.setPixelSize(size_px)
    value.setWeight(weight)
    return value


def stylesheet() -> str:
    """
    整个应用的样式表 / The application-wide QSS.

    返回 / Returns:
        str: 一份 QSS。只针对具体控件类和 objectName 写规则，
        **没有** ``QWidget`` 这种会连子类一起命中的类型选择器。
    """
    return """
    QMainWindow, QDialog {{ background: {bg_window}; }}
    #Surface {{ background: {bg_window}; }}

    QLabel {{ color: {label}; font-family: {font}; font-size: {body}px; }}
    QLabel#Title {{ font-size: {title1}px; font-weight: 600; }}
    QLabel#SectionTitle {{ font-size: {title3}px; font-weight: 600; }}
    QLabel#Secondary {{ color: {label2}; font-size: {callout}px; }}
    QLabel#Footnote {{ color: {label3}; font-size: {footnote}px; }}
    QLabel#FieldLabel {{ color: {label2}; font-size: {subhead}px; }}

    QFrame#Group {{
        background: {bg_group};
        border: none;
        border-radius: {radius_group}px;
    }}
    QFrame#Separator {{ background: {separator}; border: none; }}

    QPushButton {{
        background: {fill};
        color: {label};
        border: none;
        border-radius: {radius}px;
        padding: 6px 14px;
        font-family: {font};
        font-size: {body}px;
        min-height: {row}px;
    }}
    QPushButton:hover {{ background: {fill_hover}; }}
    QPushButton:pressed {{ background: {fill_pressed}; }}
    QPushButton:disabled {{ background: {fill_disabled}; color: {label4}; }}
    QPushButton#Primary {{ background: {accent}; color: {on_accent}; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {accent_hover}; }}
    QPushButton#Primary:pressed {{ background: {accent_pressed}; }}
    QPushButton#Primary:disabled {{ background: {fill_disabled}; color: {label4}; }}
    /* 破坏性动作只把字变红，不做红底按钮——红底按钮会把「删除」变成整屏最抢眼的东西 */
    QPushButton#Destructive {{ color: {red}; }}
    QPushButton#Destructive:hover {{ background: {fill_hover}; color: {red}; }}
    QPushButton#Quiet {{ background: transparent; padding: 4px 8px; min-height: 24px; }}
    QPushButton#Quiet:hover {{ background: {fill}; }}

    QLineEdit, QPlainTextEdit, QTextEdit {{
        background: {bg_field};
        color: {label};
        border: 1px solid {separator};
        border-radius: {radius}px;
        padding: 5px 8px;
        font-family: {font};
        font-size: {body}px;
        selection-background-color: {accent};
        selection-color: {on_accent};
        min-height: {input_height}px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {accent}; }}
    QLineEdit:disabled {{ color: {label3}; background: {fill_disabled}; }}
    QLineEdit[readOnly="true"] {{ color: {label2}; }}

    QComboBox {{
        background: {fill};
        color: {label};
        border: none;
        border-radius: {radius}px;
        padding: 5px 10px;
        font-family: {font};
        font-size: {body}px;
        min-height: {input_height}px;
    }}
    QComboBox:hover {{ background: {fill_hover}; }}
    QComboBox:disabled {{ background: {fill_disabled}; color: {label4}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {bg_group};
        color: {label};
        border: 1px solid {separator};
        border-radius: {radius}px;
        padding: 4px;
        outline: none;
        selection-background-color: {accent_soft};
        selection-color: {label};
    }}

    QListView {{
        background: transparent;
        border: none;
        outline: none;
        font-family: {font};
        font-size: {body}px;
    }}
    QListView#Sidebar {{
        background: {bg_group};
        border-radius: {radius_group}px;
        padding: 6px;
        color: {label};
    }}
    QListView#Sidebar::item {{
        border-radius: {radius}px;
        padding: 8px 10px;
        margin: 1px 0;
        color: {label2};
    }}
    QListView#Sidebar::item:hover {{ background: {fill}; color: {label}; }}
    QListView#Sidebar::item:selected {{ background: {accent_soft}; color: {label}; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {fill_hover}; border-radius: 5px; min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {fill_pressed}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{
        background: {fill_hover}; border-radius: 5px; min-width: 32px;
    }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    QToolTip {{
        background: {bg_group};
        color: {label};
        border: 1px solid {separator};
        border-radius: {radius}px;
        padding: 4px 8px;
        font-family: {font};
        font-size: {callout}px;
    }}

    QSlider::groove:horizontal {{ background: {fill}; height: 4px; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {accent}; height: 4px; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: #FFFFFF; width: 16px; height: 16px;
        margin: -6px 0; border-radius: 8px;
    }}
    """.format(
        bg_window=BG_WINDOW,
        bg_group=BG_GROUP,
        bg_field=BG_FIELD,
        fill=FILL,
        fill_hover=FILL_HOVER,
        fill_pressed=FILL_PRESSED,
        fill_disabled=FILL_DISABLED,
        separator=SEPARATOR,
        label=LABEL,
        label2=LABEL_2,
        label3=LABEL_3,
        label4=LABEL_4,
        accent=ACCENT,
        accent_hover=ACCENT_HOVER,
        accent_pressed=ACCENT_PRESSED,
        accent_soft=ACCENT_SOFT,
        on_accent=ON_ACCENT,
        red=SYSTEM["red"],
        font=FONT_SANS,
        body=TYPE_BODY,
        callout=TYPE_CALLOUT,
        subhead=TYPE_SUBHEAD,
        footnote=TYPE_FOOTNOTE,
        title1=TYPE_TITLE1,
        title3=TYPE_TITLE3,
        radius=RADIUS_CONTROL,
        radius_group=RADIUS_GROUP,
        row=ROW_HEIGHT,
        input_height=ROW_HEIGHT - 12,
    )


class Switch(QAbstractButton):
    """
    Apple 那种拨动开关 / An AppKit-style toggle switch.

    「开或关」用它，「从一堆里挑几个」才用勾选框。Qt 自带的 QCheckBox 画不出
    这个形状，QSS 也画不出来，只能自绘。
    """

    #: 轨道尺寸，按 HIG 的比例（宽约高的 1.75 倍）。
    TRACK_WIDTH = 40
    TRACK_HEIGHT = 24

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.TRACK_WIDTH, self.TRACK_HEIGHT)
        self._offset = 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        """固定尺寸 / Fixed size."""
        return QSize(self.TRACK_WIDTH, self.TRACK_HEIGHT)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    #: 旋钮位置，0 关 1 开。动画属性，别直接改。
    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        """拨过去 / Slide the knob."""
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, event) -> None:  # noqa: D102 - Qt 的绘制回调
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        enabled = self.isEnabled()
        track = QColor(ACCENT if self.isChecked() else FILL)
        if not enabled:
            track = QColor(FILL_DISABLED)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        radius = self.TRACK_HEIGHT / 2
        painter.drawRoundedRect(QRectF(0, 0, self.TRACK_WIDTH, self.TRACK_HEIGHT), radius, radius)

        knob = self.TRACK_HEIGHT - 4
        left = 2 + self._offset * (self.TRACK_WIDTH - knob - 4)
        painter.setBrush(QColor("#FFFFFF" if enabled else LABEL_3))
        painter.drawEllipse(QRectF(left, 2, knob, knob))


class Group(QFrame):
    """
    inset grouped 分组框 / One inset grouped section.

    版式就是「系统设置」那个样子：标题在框外，内容在圆角框里。用 :meth:`add`
    往里加行，用 :meth:`add_separator` 在行与行之间加一条细分割线。
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Group")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACE_ROW * 2, SPACE_ROW * 2, SPACE_ROW * 2, SPACE_ROW * 2)
        self._layout.setSpacing(SPACE_ROW)

        self.title_label: Optional[QLabel] = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("SectionTitle")

    def add(self, widget: QWidget) -> QWidget:
        """往框里加一行 / Append a row."""
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        """往框里加一段布局 / Append a laid-out row."""
        self._layout.addLayout(layout)

    def add_separator(self) -> None:
        """加一条细分割线 / Append a hairline."""
        line = QFrame()
        line.setObjectName("Separator")
        line.setFixedHeight(1)
        self._layout.addWidget(line)


def field_label(text: str) -> QLabel:
    """输入框上方的小标签 / The small caption above an input."""
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


def secondary_label(text: str = "") -> QLabel:
    """次要说明文字 / Secondary text."""
    label = QLabel(text)
    label.setObjectName("Secondary")
    return label


def footnote_label(text: str = "") -> QLabel:
    """脚注（路径这类）/ Footnote text, for paths and the like."""
    label = QLabel(text)
    label.setObjectName("Footnote")
    return label


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """圆角矩形路径 / A rounded-rect path, for custom painting."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def resource_dir() -> str:
    """
    资源目录 / Where bundled resources live, frozen or not.

    PyInstaller 冻结之后资源在 ``_MEIPASS``（onedir 模式即 ``_internal``），
    源码运行时就是仓库根目录。
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return bundled
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def icon_path() -> str:
    """应用图标的路径 / Path to the .ico."""
    return os.path.join(resource_dir(), "packaging", "app.ico")


def app_icon() -> QIcon:
    """
    应用图标 / The window icon.

    exe 自带的图标资源只管文件浏览器和任务栏，**标题栏那个是窗口自己
    setWindowIcon 画的**，所以 .ico 必须跟着包一起发。
    """
    path = icon_path()
    return QIcon(path) if os.path.isfile(path) else QIcon()


def apply_dark_titlebar(widget: QWidget) -> None:
    """
    把标题栏刷成深色 / Ask DWM for a dark title bar.

    Windows 不会因为窗口内容是深色就自动给深色标题栏，要显式设
    ``DWMWA_USE_IMMERSIVE_DARK_MODE``。不成功就算了——白色标题栏难看，
    但不该让程序起不来。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        handle = int(widget.winId())
        value = ctypes.c_int(1)
        # 20 是 Windows 10 20H1 之后的属性号，19 是更早的那版；两个都试一遍
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(handle), ctypes.c_int(attribute),
                ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass
