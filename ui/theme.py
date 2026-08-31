# -*- coding: utf-8 -*-
"""
主题运行时 / The theme runtime.

把 :mod:`ui.tokens` 里那套语义 Token 落到 Qt 上：选亮暗模式、生成样式表、给字体、
提供几个自绘控件，再管 Windows 的标题栏和 Mica。**颜色、字号、间距、圆角、阴影和
动画时长只在 tokens.py 里出现，这里只做映射，别处一律引用。**

取色一律走 :func:`palette`，不要缓存成模块常量——切换亮暗之后缓存的那份就是错的::

    theme.palette().text_primary
    theme.palette().error.text

⚠️ **绝对不要写** ``QWidget { background: ... }``。QSS 的类型选择器连子类一起命中，
那一条会把每个 QLabel 都刷上底色，在卡片上显示成一条条横杠。背景只画在真正需要的
容器上（用 objectName 选择器）。

⚠️ **字号按像素下发**。Qt 在 Windows 上按 96 DPI 把 pt 换成 px，13pt 会变成 17px、
整屏字大一圈。系统字号缩放另外处理：从注册表读 ``TextScaleFactor`` 自己乘，
见 :func:`text_scale`。这条偏离记在 ``tokens.OVERRIDES`` 里。
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui import tokens

#: 转发给自绘控件的「主题变了，重画」。QSS 控件由样式表自己更新，自绘的收不到。
class _ThemeSignals(QObject):
    """主题切换的广播 / Broadcast for theme changes."""

    changed = Signal()


_signals = _ThemeSignals()

#: 用户的选择：``system`` / ``light`` / ``dark``。
_preference = "system"
#: 解析出来的当前模式：``light`` 或 ``dark``。
_mode = "dark"
#: 系统字号缩放，1.0 表示 100%。启动和主题变化时刷新一次。
_text_scale = 1.0


def signals() -> _ThemeSignals:
    """主题信号 / The theme signal hub."""
    return _signals


# --------------------------------------------------------------------------
# 系统设置
# --------------------------------------------------------------------------

def _registry_dword(path: str, name: str) -> Optional[int]:
    """
    读一个 HKCU 下的 DWORD / Read one DWORD under HKCU.

    参数 / Parameters:
        path (str): 注册表路径，不含根键。
        name (str): 值名。

    返回 / Returns:
        Optional[int]: 读不到就是 ``None``。读注册表失败绝不能让程序起不来。
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return int(value)
    except Exception:
        return None


def text_scale() -> float:
    """
    系统字号缩放 / The user's text scale factor.

    Windows 的「设置 → 辅助功能 → 文本大小」写在
    ``HKCU\\Software\\Microsoft\\Accessibility\\TextScaleFactor``，是 100 到 225 的
    百分数。Qt 不会自己把它应用到字体上，所以字号由我们乘。

    返回 / Returns:
        float: 1.0 到 2.25 之间的倍数；读不到就是 1.0。
    """
    raw = _registry_dword(r"Software\Microsoft\Accessibility", "TextScaleFactor")
    if not raw:
        return 1.0
    return max(1.0, min(2.25, raw / 100.0))


def transparency_enabled() -> bool:
    """
    系统有没有开透明效果 / Whether the user left transparency on.

    关掉的时候不该再挂 Mica，按规范回退到语义实色。

    返回 / Returns:
        bool: 没有这个键（或者不是 Windows）时按开着算。
    """
    value = _registry_dword(
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "EnableTransparency")
    return True if value is None else bool(value)


def high_contrast() -> bool:
    """
    系统是不是开着高对比度 / Whether High Contrast is on.

    高对比度下不挂材质、不用半透明，一切走实色，否则用户特意要的对比会被材质吃掉。

    返回 / Returns:
        bool: 开着就是 ``True``；不是 Windows 或查询失败一律 ``False``。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        class _HighContrast(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint),
                        ("dwFlags", ctypes.c_uint),
                        ("lpszDefaultScheme", ctypes.c_wchar_p)]

        info = _HighContrast()
        info.cbSize = ctypes.sizeof(_HighContrast)
        # SPI_GETHIGHCONTRAST = 0x0042，HCF_HIGHCONTRASTON = 0x00000001
        if not ctypes.windll.user32.SystemParametersInfoW(
                0x0042, ctypes.sizeof(_HighContrast), ctypes.byref(info), 0):
            return False
        return bool(info.dwFlags & 0x00000001)
    except Exception:
        return False


def reduced_motion() -> bool:
    """
    系统是不是要求减少动态效果 / Whether the user asked for less motion.

    对应「显示动画效果」那个开关（``SPI_GETCLIENTAREAANIMATION``）。关掉之后位移和
    缩放的时长归零，颜色和透明度统一 100ms——不是把反馈一起删掉。

    返回 / Returns:
        bool: 要求减少就是 ``True``。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION = 0x1042，返回 TRUE 表示「动画开着」
        if not ctypes.windll.user32.SystemParametersInfoW(
                0x1042, 0, ctypes.byref(enabled), 0):
            return False
        return not bool(enabled.value)
    except Exception:
        return False


# --------------------------------------------------------------------------
# 亮暗模式
# --------------------------------------------------------------------------

def system_mode() -> str:
    """
    系统现在是亮还是暗 / The system colour scheme.

    走 Qt 的 ``QStyleHints.colorScheme()``（Qt 6.5 起），拿不到就当深色——这个应用
    在深色下待了整整两个大版本，猜错时那一边看着更眼熟。

    返回 / Returns:
        str: ``light`` 或 ``dark``。
    """
    try:
        hints = QGuiApplication.styleHints()
        if hints is not None and hints.colorScheme() == Qt.ColorScheme.Light:
            return "light"
    except Exception:
        pass
    return "dark"


def mode() -> str:
    """当前模式 / The resolved mode, ``light`` or ``dark``."""
    return _mode


def preference() -> str:
    """用户的选择 / The stored preference: system, light or dark."""
    return _preference


def palette() -> tokens.Palette:
    """
    当前这套语义色 / The palette in force right now.

    返回 / Returns:
        tokens.Palette: 亮或暗的那一份。**别把返回值存成模块常量**，
        切换模式之后它就过期了。
    """
    return tokens.LIGHT if _mode == "light" else tokens.DARK


def elevation(level: int) -> tokens.Shadow:
    """
    一档阴影 / One elevation step for the current mode.

    参数 / Parameters:
        level (int): 1 或 2。

    返回 / Returns:
        tokens.Shadow: 当前模式下的阴影定义。
    """
    active = palette()
    return active.elevation_1 if level == 1 else active.elevation_2


def set_preference(value: str, app=None) -> None:
    """
    换一个主题偏好并立刻生效 / Switch the preference and re-apply.

    参数 / Parameters:
        value (str): ``system`` / ``light`` / ``dark``，别的值一律当 ``system``。
        app: QApplication；给了就顺手把样式表重刷一遍。
    """
    global _preference
    _preference = value if value in ("system", "light", "dark") else "system"
    refresh(app)


def refresh(app=None) -> None:
    """
    重新解析模式并刷新界面 / Re-resolve the mode and re-apply everything.

    系统换了主题、改了字号缩放、开关了高对比度之后都要走一遍。样式表重刷之后还要
    ``repolish``：属性选择器是在 polish 的时候算的。
    """
    global _mode, _text_scale
    _text_scale = text_scale()
    _mode = system_mode() if _preference == "system" else _preference

    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
    if app is None:
        return

    app.setFont(font("body"))
    app.setStyleSheet(stylesheet())
    for window in app.topLevelWidgets():
        apply_titlebar(window)
        repolish(window)
    _signals.changed.emit()


def install(app, stored_preference: str = "system") -> None:
    """
    把主题装到应用上 / Install the theme onto the application.

    参数 / Parameters:
        app (QApplication): 应用实例。
        stored_preference (str): 从配置里读出来的偏好。

    只在启动时调一次。除了刷样式表，还会接上系统主题变化的信号——用户在
    Windows 设置里切亮暗时，窗口要跟着走，而不是等下次启动。
    """
    global _preference
    _preference = stored_preference if stored_preference in (
        "system", "light", "dark") else "system"

    try:
        hints = QGuiApplication.styleHints()
        if hints is not None:
            hints.colorSchemeChanged.connect(lambda _scheme: refresh(app))
    except Exception:
        # 拿不到就退化成「启动时定一次」，不该让程序起不来
        pass

    refresh(app)


# --------------------------------------------------------------------------
# 排版
# --------------------------------------------------------------------------

def _ui_family() -> str:
    """
    系统界面字体 / The user's current system UI font family.

    规范要求继承系统界面字体，不擅自替换字体类别。**但字族必须显式设**：自绘的
    delegate 不吃 QSS，``QFont()`` 拿到的是 Qt 的默认字体，那上面可能一个中文字形
    都没有，画出来整屏是方框。
    """
    return QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()


def _mono_family() -> str:
    """系统等宽字体 / The system fixed-width family, for paths and logs."""
    return QFontDatabase.systemFont(QFontDatabase.FixedFont).family()


def _qt_weight(weight: int) -> QFont.Weight:
    """
    CSS 字重转 Qt 字重 / Map a CSS weight onto Qt's enum.

    字体缺这一档时 Qt 自己映射到最近可用的，不需要我们换字体家族。
    """
    if weight >= 600:
        return QFont.DemiBold
    if weight >= 500:
        return QFont.Medium
    return QFont.Normal


def type_style(role: str) -> tokens.TypeStyle:
    """
    取一档排版 / One step of the type scale.

    参数 / Parameters:
        role (str): ``pageTitle`` / ``title`` / ``sectionTitle`` / ``body`` /
            ``secondary`` / ``caption`` / ``metric`` / ``button`` / ``mono``。

    返回 / Returns:
        tokens.TypeStyle: 未经缩放的逻辑值。

    异常 / Raises:
        KeyError: 不在字阶表里的角色。别自己发明档位。
    """
    return tokens.TYPE[role]


def font_size(role: str) -> int:
    """按系统字号缩放算出来的像素字号 / The scaled pixel size for one role."""
    return max(1, round(type_style(role).size * _text_scale))


def line_height(role: str) -> int:
    """按系统字号缩放算出来的行高 / The scaled line height for one role."""
    return max(1, round(type_style(role).line_height * _text_scale))


def font(role: str) -> QFont:
    """
    取一档字 / One step of the type scale, as a QFont.

    参数 / Parameters:
        role (str): 字阶里的角色名。

    返回 / Returns:
        QFont: 设好字族、像素大小和字重的字体。
    """
    style = type_style(role)
    value = QFont()
    value.setFamilies([_mono_family() if role == "mono" else _ui_family()])
    value.setPixelSize(font_size(role))
    value.setWeight(_qt_weight(style.weight))
    return value


# --------------------------------------------------------------------------
# 动效
# --------------------------------------------------------------------------

def duration(name: str, moves: bool = True) -> int:
    """
    一段动效该跑多久 / How long one transition should take.

    参数 / Parameters:
        name (str): ``immediate`` / ``small`` / ``medium`` / ``large``。
        moves (bool): 这段动效有没有位移或缩放。系统要求减少动态效果时，
            有位移的直接归零，纯颜色和透明度的统一压到 100ms——**不是取消反馈**。

    返回 / Returns:
        int: 毫秒。
    """
    table = {"immediate": tokens.MOTION_IMMEDIATE, "small": tokens.MOTION_SMALL,
             "medium": tokens.MOTION_MEDIUM, "large": tokens.MOTION_LARGE}
    full = table[name]
    if not reduced_motion():
        return full
    return 0 if moves else tokens.MOTION_REDUCED_COLOUR


def easing(leaving: bool = False) -> QEasingCurve:
    """
    缓动曲线 / The easing curve for entering or leaving.

    参数 / Parameters:
        leaving (bool): 离场用另一条曲线。

    返回 / Returns:
        QEasingCurve: 和 CSS 的 ``cubic-bezier`` 同一组控制点。
    """
    x1, y1, x2, y2 = tokens.EASE_EXIT if leaving else tokens.EASE_ENTER
    curve = QEasingCurve(QEasingCurve.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return curve


# --------------------------------------------------------------------------
# 样式表
# --------------------------------------------------------------------------

def stylesheet() -> str:
    """
    整个应用的样式表 / The application-wide QSS.

    返回 / Returns:
        str: 一份 QSS。只针对具体控件类和 objectName 写规则，
        **没有** ``QWidget`` 这种会连子类一起命中的类型选择器。
    """
    p = palette()
    return """
    QMainWindow, QDialog {{ background: {canvas}; }}
    #Surface {{ background: {canvas}; }}
    /* 挂上 Mica 的窗口自己不画底，那块留给 DWM。属性选择器比裸类型选择器
       优先级高，压得住上面两条；没挂上的窗口一个字节都不受影响，仍是不透明的。 */
    QMainWindow[mica="true"], QDialog[mica="true"] {{ background: transparent; }}
    QMainWindow[mica="true"] #Surface, QDialog[mica="true"] #Surface {{ background: transparent; }}

    QLabel {{ color: {text}; font-family: "{family}"; font-size: {body}px; }}
    QLabel:disabled {{ color: {disabled}; }}
    QLabel#PageTitle {{ font-size: {page_title}px; font-weight: 600; }}
    QLabel#Title {{ font-size: {title}px; font-weight: 600; }}
    QLabel#SectionTitle {{ font-size: {section_title}px; font-weight: 600; }}
    QLabel#Secondary {{ color: {text2}; font-size: {secondary}px; }}
    QLabel#Caption {{ color: {text3}; font-size: {caption}px; }}
    QLabel#Mono {{ color: {text2}; font-family: "{mono_family}"; font-size: {mono}px; }}
    QLabel#Metric {{ font-size: {metric}px; font-weight: 600; }}

    /* 真正的 Surface：空间上独立的区域。实测 surface 与 canvas 的对比度只有
       1.04（浅）/ 1.07（深），低于规范 2.5 的 1.1:1，所以必须补一条边。 */
    QFrame#Panel {{
        background: {surface};
        border: 1px solid {separator};
        border-radius: {radius_medium}px;
    }}
    QFrame#Separator {{ background: {separator}; border: none; }}
    QFrame#VSeparator {{ background: {separator}; border: none; }}

    QPushButton {{
        background: {fill};
        color: {text};
        border: 1px solid {border};
        border-radius: {radius_small}px;
        padding: {pad_y}px {pad_x}px;
        font-family: "{family}";
        font-size: {button}px;
        font-weight: 500;
        min-height: {row}px;
    }}
    QPushButton:hover {{ background: {fill_hover}; }}
    QPushButton:pressed {{ background: {fill_pressed}; }}
    QPushButton:focus {{ outline: {ring}px solid {focus}; outline-offset: {ring_offset}px; }}
    QPushButton:disabled {{ background: {fill}; color: {disabled}; border-color: {separator}; }}

    QPushButton#Primary {{ background: {accent}; color: {on_accent}; border-color: {accent}; }}
    QPushButton#Primary:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
    QPushButton#Primary:pressed {{ background: {accent_pressed}; border-color: {accent_pressed}; }}
    QPushButton#Primary:disabled {{ background: {fill}; color: {disabled}; border-color: {separator}; }}

    /* 破坏性动作：红字 + 红边。颜色不是唯一载体——按下去还有一个说清对象、
       范围和后果的确认框。 */
    QPushButton#Destructive {{ color: {error_text}; border-color: {error_border}; }}
    QPushButton#Destructive:hover {{ background: {error_subtle}; }}
    QPushButton#Destructive:pressed {{ background: {error_subtle}; }}
    QPushButton#Destructive:disabled {{ color: {disabled}; border-color: {separator}; }}

    QPushButton#Quiet {{ background: transparent; border-color: transparent; }}
    QPushButton#Quiet:hover {{ background: {fill_hover}; }}
    QPushButton#Quiet:pressed {{ background: {fill_pressed}; }}

    /* 分段控件：少量互斥、标签短、要直接比较 */
    QPushButton#Segment {{ border-radius: {radius_small}px; }}
    QPushButton#Segment:checked {{
        background: {accent_subtle};
        color: {accent_text};
        border-color: {accent_border};
    }}
    QPushButton#Segment:checked:hover {{ background: {accent_subtle_hover}; }}

    QLineEdit, QPlainTextEdit, QTextEdit {{
        background: {fill};
        color: {text};
        border: 1px solid {border};
        border-radius: {radius_small}px;
        padding: {pad_y}px {pad_x}px;
        font-family: "{family}";
        font-size: {body}px;
        selection-background-color: {accent};
        selection-color: {on_accent};
        min-height: {input_height}px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        outline: {ring}px solid {focus}; outline-offset: {ring_offset}px;
    }}
    QLineEdit[invalid="true"] {{ border: 2px solid {error_border}; }}
    QLineEdit:disabled, QPlainTextEdit:disabled {{ color: {disabled}; background: {fill}; }}
    QLineEdit[readOnly="true"] {{ color: {text2}; }}

    QComboBox {{
        background: {fill};
        color: {text};
        border: 1px solid {border};
        border-radius: {radius_small}px;
        padding: {pad_y}px {pad_x}px;
        font-family: "{family}";
        font-size: {body}px;
        min-height: {input_height}px;
    }}
    QComboBox:hover {{ background: {fill_hover}; }}
    QComboBox:focus {{ outline: {ring}px solid {focus}; outline-offset: {ring_offset}px; }}
    QComboBox:disabled {{ background: {fill}; color: {disabled}; border-color: {separator}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {elevated};
        color: {text};
        border: 1px solid {separator};
        border-radius: {radius_small}px;
        padding: 4px;
        outline: none;
        selection-background-color: {accent_subtle};
        selection-color: {accent_text};
    }}

    QListView {{
        background: transparent;
        border: none;
        outline: none;
        font-family: "{family}";
        font-size: {body}px;
    }}
    QListView#Nav {{ background: transparent; color: {text}; }}
    QListView#Nav::item {{
        border-radius: {radius_small}px;
        padding: {pad_y}px {pad_x}px;
        margin: 1px 0;
        color: {text2};
    }}
    QListView#Nav::item:hover {{ background: {fill_hover}; color: {text}; }}
    QListView#Nav::item:selected {{ background: {accent_subtle}; color: {accent_text}; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {separator_strong}; border-radius: 5px; min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {border}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{
        background: {separator_strong}; border-radius: 5px; min-width: 32px;
    }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    QToolTip {{
        background: {elevated};
        color: {text2};
        border: 1px solid {separator};
        border-radius: {radius_small}px;
        padding: {pad_y}px {pad_x}px;
        font-family: "{family}";
        font-size: {secondary}px;
    }}

    QProgressBar {{
        background: {fill};
        border: 1px solid {border};
        border-radius: {radius_small}px;
        height: 6px;
        text-align: center;
        color: {text2};
        font-size: {caption}px;
    }}
    QProgressBar::chunk {{ background: {accent}; border-radius: {radius_small}px; }}
    """.format(
        canvas=p.canvas,
        surface=p.surface,
        elevated=p.surface_elevated,
        text=p.text_primary,
        text2=p.text_secondary,
        text3=p.text_tertiary,
        disabled=p.text_disabled,
        separator=p.separator_subtle,
        separator_strong=p.separator_strong,
        border=p.border_default,
        fill=p.fill_control,
        fill_hover=p.fill_hover,
        fill_pressed=p.fill_pressed,
        accent=p.accent_primary,
        accent_hover=p.accent_hover,
        accent_pressed=p.accent_pressed,
        accent_subtle=p.accent_subtle,
        accent_subtle_hover=p.accent_subtle_hover,
        accent_text=p.accent_text,
        accent_border=p.accent_border,
        focus=p.accent_focus,
        on_accent=p.accent_on_accent,
        error_text=p.error.text,
        error_border=p.error.border,
        error_subtle=p.error.subtle,
        family=_ui_family(),
        mono_family=_mono_family(),
        page_title=font_size("pageTitle"),
        title=font_size("title"),
        section_title=font_size("sectionTitle"),
        body=font_size("body"),
        secondary=font_size("secondary"),
        caption=font_size("caption"),
        metric=font_size("metric"),
        button=font_size("button"),
        mono=font_size("mono"),
        radius_small=tokens.RADIUS_SMALL,
        radius_medium=tokens.RADIUS_MEDIUM,
        pad_x=tokens.PADDING_CONTROL_X,
        pad_y=tokens.PADDING_CONTROL_Y,
        ring=tokens.FOCUS_RING_WIDTH,
        ring_offset=tokens.FOCUS_RING_OFFSET,
        row=tokens.ROW_MIN_HEIGHT,
        input_height=tokens.ROW_MIN_HEIGHT - 2 * tokens.PADDING_CONTROL_Y,
    )


# --------------------------------------------------------------------------
# 自绘用的小工具
# --------------------------------------------------------------------------

def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    """圆角矩形路径 / A rounded-rect path, for custom painting."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def paint_focus_ring(painter: QPainter, rect: QRectF, radius: float) -> None:
    """
    画一圈焦点环 / Draw the focus ring around a self-painted control.

    2px 宽、向外偏移 2px，中间露出控件所在的 Surface，圆角跟着控件加上偏移量
    （规范 2.5「Focus 指示」）。**容器要为这 4px 预留空间**，否则环会被裁掉。

    参数 / Parameters:
        painter (QPainter): 正在画这个控件的画笔。
        rect (QRectF): 控件本体的矩形。
        radius (float): 控件本体的圆角。
    """
    width = tokens.FOCUS_RING_WIDTH
    offset = tokens.FOCUS_RING_OFFSET
    outer = rect.adjusted(-offset - width / 2, -offset - width / 2,
                          offset + width / 2, offset + width / 2)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(palette().accent_focus), width))
    painter.drawRoundedRect(outer, radius + offset, radius + offset)


def apply_elevation(widget: QWidget, level: int = 2) -> None:
    """
    给浮层加阴影 / Put one elevation step behind a floating widget.

    Qt 没有 spread 的概念，取 ``blur`` 作 ``blurRadius``、``(x, y)`` 作 offset，
    和规范 2.5 的结构化定义一一对应。

    参数 / Parameters:
        widget (QWidget): 浮层本体。
        level (int): 1 或 2。
    """
    shadow = elevation(level)
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(shadow.blur)
    effect.setOffset(shadow.x, shadow.y)
    colour = QColor(0, 0, 0)
    colour.setAlphaF(0.28 if palette().mode == "dark" and level == 1 else
                     0.32 if palette().mode == "dark" else
                     0.10 if level == 1 else 0.14)
    effect.setColor(colour)
    widget.setGraphicsEffect(effect)


def repolish(widget: QWidget) -> None:
    """
    让样式表重新认一遍这个窗口 / Re-run the style over a widget and its children.

    属性选择器（``[mica="true"]``、``[invalid="true"]``）是在 polish 的时候算的，
    改完属性不重来一遍就不生效。
    """
    for target in [widget] + widget.findChildren(QWidget):
        target.style().unpolish(target)
        target.style().polish(target)
    widget.update()


# --------------------------------------------------------------------------
# 控件
# --------------------------------------------------------------------------

class Switch(QAbstractButton):
    """
    拨动开关 / A toggle switch.

    「开或关」用它，「从一堆里挑几个」才用勾选框。Qt 自带的 QCheckBox 画不出这个
    形状，QSS 也画不出来，只能自绘——自绘就得自己补齐 Focus、Disabled 和键盘操作。
    """

    TRACK_WIDTH = 40
    TRACK_HEIGHT = 24

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        # 焦点环要往外画 4px，控件得把这块地方留出来，否则会被父容器裁掉
        margin = tokens.FOCUS_RING_OFFSET + tokens.FOCUS_RING_WIDTH
        self.setFixedSize(self.TRACK_WIDTH + 2 * margin, self.TRACK_HEIGHT + 2 * margin)
        self._margin = margin
        self._offset = 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(duration("small"))
        self._animation.setEasingCurve(easing())
        self.toggled.connect(self._animate)
        _signals.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        """固定尺寸 / Fixed size."""
        return QSize(self.TRACK_WIDTH + 2 * self._margin,
                     self.TRACK_HEIGHT + 2 * self._margin)

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
        self._animation.setDuration(duration("small"))
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, event) -> None:  # noqa: D102 - Qt 的绘制回调
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        enabled = self.isEnabled()
        body = QRectF(self._margin, self._margin, self.TRACK_WIDTH, self.TRACK_HEIGHT)
        radius = self.TRACK_HEIGHT / 2

        if not enabled:
            track = QColor(p.fill_control)
        elif self.isChecked():
            track = QColor(p.accent_pressed if self.isDown() else p.accent_primary)
        else:
            track = QColor(p.fill_pressed if self.isDown() else p.fill_control)
        painter.setPen(QPen(QColor(p.separator_subtle if not enabled else p.border_default), 1))
        painter.setBrush(track)
        painter.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        knob = self.TRACK_HEIGHT - 6
        left = body.left() + 3 + self._offset * (self.TRACK_WIDTH - knob - 6)
        if not enabled:
            knob_colour = QColor(p.text_disabled)
        elif self.isChecked():
            knob_colour = QColor(p.accent_on_accent)
        else:
            knob_colour = QColor(p.text_secondary)
        painter.setPen(Qt.NoPen)
        painter.setBrush(knob_colour)
        painter.drawEllipse(QRectF(left, body.top() + 3, knob, knob))

        if self.hasFocus():
            paint_focus_ring(painter, body, radius)


class CloseButton(QAbstractButton):
    """
    面板上的关闭按钮 / The close button on a panel.

    自绘一个 ✕：Emoji 不能当正式 UI 图标，而 Qt 自带的标准图标是给对话框按钮用的，
    在面板标题旁边太重。命中区按 :data:`tokens.ROW_MIN_HEIGHT` 给足，
    视觉上的叉只有 :data:`tokens.ICON_INLINE` 那么大。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(tokens.ROW_MIN_HEIGHT, tokens.ROW_MIN_HEIGHT)
        self.setToolTip("关闭")
        self.setAccessibleName("关闭")
        _signals.changed.connect(self.update)

    def paintEvent(self, event) -> None:  # noqa: D102 - Qt 的绘制回调
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QRectF(2, 2, self.width() - 4, self.height() - 4)

        if self.isDown():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(p.fill_pressed))
            painter.drawRoundedRect(body, tokens.RADIUS_SMALL, tokens.RADIUS_SMALL)
        elif self.underMouse():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(p.fill_hover))
            painter.drawRoundedRect(body, tokens.RADIUS_SMALL, tokens.RADIUS_SMALL)

        size = tokens.ICON_INLINE / 2
        centre = body.center()
        colour = QColor(p.text_disabled if not self.isEnabled() else p.text_secondary)
        painter.setPen(QPen(colour, 1.5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(centre.x() - size / 2, centre.y() - size / 2),
                         QPointF(centre.x() + size / 2, centre.y() + size / 2))
        painter.drawLine(QPointF(centre.x() + size / 2, centre.y() - size / 2),
                         QPointF(centre.x() - size / 2, centre.y() + size / 2))

        if self.hasFocus():
            paint_focus_ring(painter, body.adjusted(1, 1, -1, -1), tokens.RADIUS_SMALL)


#: Section 里两块非行内容之间的距离。用 gap.control 那一档。
GAP_BLOCK = tokens.GAP_CONTROL


class Section(QWidget):
    """
    一个设置组 / One settings section.

    规范 3.4 的 Desktop 版式：**组标题在外，行直接排在 Canvas 或所在 Surface 上，
    不再套一层 Card**。行与行之间用 Separator，用了 Separator 就不再加 gap.control。

    参数 / Parameters:
        title (str): 组标题，空字符串表示这一组没有标题。
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(tokens.SECTION_TITLE_TO_ROWS)

        self.title_label: Optional[QLabel] = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("SectionTitle")
            self._outer.addWidget(self.title_label)

        self._rows_host = QWidget(self)
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)
        self._outer.addWidget(self._rows_host)

    def add(self, widget: QWidget) -> QWidget:
        """加一行 / Append a row."""
        self._separate()
        widget.setMinimumHeight(tokens.ROW_MIN_HEIGHT)
        self._rows.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        """加一段布局 / Append a laid-out row."""
        self._separate()
        holder = QWidget(self._rows_host)
        holder.setMinimumHeight(tokens.ROW_MIN_HEIGHT)
        holder.setLayout(layout)
        layout.setContentsMargins(0, tokens.GAP_RELATED, 0, tokens.GAP_RELATED)
        self._rows.addWidget(holder)

    def add_block(self, widget: QWidget) -> QWidget:
        """
        加一块不算「行」的内容 / Append content that is not a settings row.

        预览图、说明段落这类东西没有「标签 + 值」的结构，前面不该有分隔线，
        也不受最小行高约束。
        """
        if self._rows.count():
            self._rows.addSpacing(GAP_BLOCK)
        self._rows.addWidget(widget)
        return widget

    def _separate(self) -> None:
        """行与行之间补一条线 / A hairline between rows, never before the first."""
        if self._rows.count():
            self._rows.addWidget(separator())

    def row_count(self) -> int:
        """这一组有几行 / How many rows this section holds."""
        return sum(1 for index in range(self._rows.count())
                   if self._rows.itemAt(index).widget() is not None
                   and self._rows.itemAt(index).widget().objectName() != "Separator")


def panel() -> QFrame:
    """
    一块真正的 Surface / One genuine Surface container.

    只有空间或交互上真正独立的区域才用它——检查器面板是，表单里的几个字段不是。
    """
    frame = QFrame()
    frame.setObjectName("Panel")
    return frame


def separator() -> QFrame:
    """一条细分隔线 / One hairline separator."""
    line = QFrame()
    line.setObjectName("Separator")
    line.setFixedHeight(1)
    line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return line


def vertical_separator() -> QFrame:
    """一条竖分隔线 / One vertical hairline."""
    line = QFrame()
    line.setObjectName("VSeparator")
    line.setFixedWidth(1)
    line.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    return line


class SegmentedControl(QWidget):
    """
    分段控件 / A segmented control.

    少量互斥、标签简短、需要直接比较时用它（规范 4.1）。Qt 没有原生的，用一组
    ``autoExclusive`` 的按钮拼——这样方向键切换和无障碍语义都跟着来了。
    """

    changed = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(tokens.GAP_RELATED)
        self._buttons: List[QPushButton] = []
        self._data: List[object] = []

    def add_item(self, text: str, data: object) -> None:
        """
        加一段 / Append one segment.

        参数 / Parameters:
            text (str): 段上的文字。
            data (object): 选中时 :meth:`current_data` 返回的东西。
        """
        button = QPushButton(text, self)
        button.setObjectName("Segment")
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setAccessibleName(text)
        index = len(self._buttons)
        button.clicked.connect(lambda _checked, i=index: self.changed.emit(i))
        if not self._buttons:
            button.setChecked(True)
        self._buttons.append(button)
        self._data.append(data)
        self._layout.addWidget(button)

    def current_index(self) -> int:
        """当前选中第几段 / The checked segment's index."""
        for index, button in enumerate(self._buttons):
            if button.isChecked():
                return index
        return 0

    def current_data(self) -> object:
        """当前选中那段带的数据 / The checked segment's data."""
        return self._data[self.current_index()] if self._data else None


def label(text: str = "", role: str = "body") -> QLabel:
    """
    一个按字阶配好的标签 / One label wired to a type-scale role.

    参数 / Parameters:
        text (str): 文字。
        role (str): ``body`` / ``secondary`` / ``caption`` / ``mono`` /
            ``sectionTitle`` / ``title`` / ``pageTitle`` / ``metric``。

    返回 / Returns:
        QLabel: 设好 objectName 的标签，颜色和字号由样式表给。
    """
    names = {"body": "", "secondary": "Secondary", "caption": "Caption",
             "mono": "Mono", "sectionTitle": "SectionTitle", "title": "Title",
             "pageTitle": "PageTitle", "metric": "Metric"}
    widget = QLabel(text)
    if names[role]:
        widget.setObjectName(names[role])
    return widget


def wrapped_label(text: str = "", role: str = "secondary") -> QLabel:
    """
    会换行的说明文字 / A wrapping label that honours the token line height.

    单行标签用不上行高，多行的必须给——不给的话行距是字体自己的默认值，
    和字阶表对不上。QSS 没有 ``line-height``，只能走富文本。

    参数 / Parameters:
        text (str): 文字。
        role (str): 字阶角色。

    返回 / Returns:
        QLabel: 已经打开自动换行的标签。用 :func:`set_wrapped_text` 改文字。
    """
    widget = label("", role)
    widget.setWordWrap(True)
    widget.setProperty("textRole", role)
    set_wrapped_text(widget, text)
    return widget


def set_wrapped_text(widget: QLabel, text: str) -> None:
    """
    给会换行的标签换文字 / Replace the text of a wrapping label.

    参数 / Parameters:
        widget (QLabel): :func:`wrapped_label` 造出来的标签。
        text (str): 纯文本，会被转义。
    """
    role = widget.property("textRole") or "secondary"
    escaped = (text.replace("&", "&amp;").replace("<", "&lt;")
               .replace(">", "&gt;").replace("\n", "<br>"))
    widget.setText('<div style="line-height: {}px;">{}</div>'.format(
        line_height(role), escaped))


# --------------------------------------------------------------------------
# 资源
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Windows 的标题栏与 Mica
# --------------------------------------------------------------------------

def apply_titlebar(widget: QWidget) -> None:
    """
    标题栏跟着主题走 / Match the title bar to the active theme.

    Windows 不会因为窗口内容是深色就自动给深色标题栏，要显式设
    ``DWMWA_USE_IMMERSIVE_DARK_MODE``；浅色模式下同样要显式设回去，否则会得到
    深标题栏配浅内容。不成功就算了——难看，但不该让程序起不来。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        handle = int(widget.winId())
        value = ctypes.c_int(1 if mode() == "dark" else 0)
        # 20 是 Windows 10 20H1 之后的属性号，19 是更早的那版；两个都试一遍
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(handle), ctypes.c_int(attribute),
                ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


#: Windows 11 的起始内部版本号。Mica 是 Win11 才有的东西，Win10 上这些属性号
#: 不认，硬设只会得到一个不透明也不 Mica 的窗口，所以低于这个数一律不试。
BUILD_WIN11 = 22000
#: ``DWMWA_SYSTEMBACKDROP_TYPE`` 是 22H2（22621）起的正式属性号；21H2 只认没进
#: 文档的 ``DWMWA_MICA_EFFECT``。两版写法不一样，按版本分。
BUILD_BACKDROP_ATTRIBUTE = 22621

#: DwmSetWindowAttribute 的属性号。
DWMWA_MICA_EFFECT = 1029
DWMWA_SYSTEMBACKDROP_TYPE = 38
#: ``DWMSBT_MAINWINDOW``，也就是 Mica。3 是 Acrylic（给临时窗口的），4 是 Mica Alt。
#: 主窗口用 Mica：它取的是**桌面壁纸**而不是身后那扇窗，长驻窗口才配得上。
DWMSBT_MAINWINDOW = 2


def windows_build() -> int:
    """
    Windows 的内部版本号 / The Windows build number, 0 elsewhere.

    返回 / Returns:
        int: 例如 22631；不是 Windows 就是 0。
    """
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def supports_mica() -> bool:
    """
    这台机器现在能不能上 Mica / Whether Mica is appropriate right now.

    三个条件：Windows 11、系统没关透明效果、没开高对比度。后两个是规范要求的
    材质回退——用户特意要的对比度不能被一层材质吃掉。
    """
    return (windows_build() >= BUILD_WIN11
            and transparency_enabled()
            and not high_contrast())


def _backdrop_attribute(build: int) -> tuple:
    """
    这个版本认哪个属性号 / Which attribute this build understands.

    参数 / Parameters:
        build (int): Windows 内部版本号。

    返回 / Returns:
        tuple: ``(属性号, 值)``。
    """
    if build >= BUILD_BACKDROP_ATTRIBUTE:
        return DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW
    return DWMWA_MICA_EFFECT, 1


def _enable_backdrop(handle: int) -> None:
    """
    真正去调 DWM 的那几行 / The actual DWM calls.

    ``DwmExtendFrameIntoClientArea`` 那一步不能省：只设属性号的话，材质只出现在
    标题栏那一条，客户区还是老样子。``-1`` 是「整个客户区都算边框玻璃」的写法。

    参数 / Parameters:
        handle (int): 顶层窗口的 HWND。

    异常 / Raises:
        OSError: DWM 不认这个属性，或者句柄无效。
    """
    import ctypes

    class _Margins(ctypes.Structure):
        _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

    dwm = ctypes.windll.dwmapi
    window = ctypes.c_void_p(handle)

    attribute, value = _backdrop_attribute(windows_build())
    holder = ctypes.c_int(value)
    result = dwm.DwmSetWindowAttribute(window, ctypes.c_int(attribute),
                                       ctypes.byref(holder), ctypes.sizeof(holder))
    if result != 0:
        raise OSError("DwmSetWindowAttribute({}) 返回 0x{:08X}".format(attribute, result & 0xFFFFFFFF))

    margins = _Margins(-1, -1, -1, -1)
    result = dwm.DwmExtendFrameIntoClientArea(window, ctypes.byref(margins))
    if result != 0:
        raise OSError("DwmExtendFrameIntoClientArea 返回 0x{:08X}".format(result & 0xFFFFFFFF))


def apply_mica(widget: QWidget) -> bool:
    """
    背景换成 Mica / Put a Mica backdrop behind the window.

    三件事缺一不可，少一件就只是个透明窗口：

    1. 窗口自己不能画底——``WA_TranslucentBackground`` 加样式表里那两条
       ``[mica="true"]``，否则 DWM 画的东西被盖在下面；
    2. ``DwmExtendFrameIntoClientArea`` 把玻璃摊到整个客户区；
    3. 属性号按版本分（见 :func:`_backdrop_attribute`）。

    **半路失败要把透明属性收回去**：窗口透明而底下没有 Mica，看到的是一个黑
    窟窿，比没有材质难看得多。

    参数 / Parameters:
        widget (QWidget): 顶层窗口。子控件没有自己的 HWND，设了不算数。

    返回 / Returns:
        bool: 材质是否真的挂上了。没挂上的窗口仍是不透明的语义实色底。
    """
    if not supports_mica():
        apply_titlebar(widget)
        return False

    # 透明属性要赶在 winId() 之前设：窗口建出来之后再改，Qt 得把它拆了重建
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    apply_titlebar(widget)
    try:
        _enable_backdrop(int(widget.winId()))
    except Exception:
        widget.setAttribute(Qt.WA_TranslucentBackground, False)
        return False

    widget.setProperty("mica", True)
    repolish(widget)
    return True
