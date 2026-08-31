# -*- coding: utf-8 -*-
"""
设计 Token 的唯一真源 / The single source of truth for design tokens.

全局规范 ``~/.claude/DESIGN.md`` 的本项目落地：Neutral / Accent / Semantic 三套
语义色，加上排版、间距、圆角、阴影、动效和层叠顺序。**每个 Token 都是解析完成的
单值**，没有区间、没有 ``auto``、没有「按需」——规范 10.1「实现前解析门槛」要求的
就是这个。

**这个模块不 import 任何 Qt。** 两个理由：对比度测试不用起 QApplication 就能跑；
Qt 线的另外两个项目（cun、superpicky-universal）照抄时只需要换这一个文件里的值。

色值由 OKLCH 生成后人工校准，校准过程和实测对比度记在 :data:`OVERRIDES` 与
``更新记录.md``。**运行时不依赖任何生成器**，改色只改这里。

用 ``python -m ui.tokens`` 打印解析后的全套 Token（规范 10.1 第 6 条）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Tuple

#: 本项目实现的规范版本。跨项目视觉对比只在这个值一致时才成立（规范 10.1）。
DESIGN_SYSTEM_REVISION = "2026.08.31-a11y-baseline"

#: 本项目只有桌面一种形态，排版和间距一律取规范里的 Desktop 列。
PLATFORM = "desktop"

#: 品牌方向。色相 300 附近的薰衣草紫，登记在规范 2.1 的品牌色表里。
BRAND_DIRECTION = "薰衣草紫"
BRAND_HUE = 299.8
BRAND_CHROMA = 0.130
#: Neutral 的染色。规范给的起点就是 0.006，本项目没有扩大搜索范围。
NEUTRAL_HUE = 300.0
NEUTRAL_CHROMA = 0.006


# --------------------------------------------------------------------------
# 覆盖登记
# --------------------------------------------------------------------------

#: 偏离全局默认的地方，逐条记下确定值和原因（规范 10.1 第 4、5 条）。
#: 没有写进这张表的值，一律等于 ``DESIGN.md`` 的默认值。
OVERRIDES: Tuple[Dict[str, str], ...] = (
    {
        "token": "accent.primary / hover / pressed（Light）",
        "value": "#7C5BAF / #7353A6 / #6F4EA1，onAccent 取白",
        "reason": "Windows Fluent 浅色主题的强调按钮就是深底白字。若按候选色板走淡紫底"
                  "配深字，规范要求的 pressed ΔL 0.045 会把 onAccent 压到 4.5:1 以下，"
                  "三态一致和对比度无法同时成立。实测白字 5.29 / 5.97 / 6.40。",
    },
    {
        "token": "text.tertiary（Light）",
        "value": "#68676A（OKLCH L 0.515）",
        "reason": "规范给的搜索边界是 0.54–0.58，但文字承载面集合里含 fill.control"
                  "（L 0.930），在边界内最高只有 3.94:1。下探到 0.515 后全集合最低 4.55:1。",
    },
    {
        "token": "border.default",
        "value": "Light #908F93 / Dark #6C6B6F",
        "reason": "规范 2.1 要求控件边界至少 3:1，2.5 又要求自绘 Input 带 1px border.default。"
                  "候选色板的 #C8C6CC 只有 1.62:1，重新生成到 canvas / surface / "
                  "surfaceElevated 三个面上都不低于 3:1。",
    },
    {
        "token": "semantic.error.solid（Light）",
        "value": "#E35451",
        "reason": "候选值 #E0514E 的 onSolid 正好卡在 4.50，一点余量都没有。抬到 4.66，"
                  "边框对 canvas 仍有 3.55。",
    },
    {
        "token": "typography：Qt 的字号映射",
        "value": "逻辑值 × Windows 文字缩放百分比，按像素下发",
        "reason": "规范的映射表没有 Qt 一行。Qt 在 Windows 上按 96 DPI 把 pt 换算成 px，"
                  "13pt 会变成 17px、整屏字大一圈，所以字号必须按像素给；系统字号缩放改从"
                  "注册表的 TextScaleFactor 读出来自己乘（见 ui.theme.text_scale）。",
    },
    {
        "token": "motion：QSS 控件的 hover / pressed",
        "value": "瞬时（native）",
        "reason": "Qt 的样式表没有 transition，QSS 控件的颜色反馈只能是瞬时的。自绘控件"
                  "（Switch、检查器展开、状态条）照常走 motion Token。",
    },
    {
        "token": "GAME_CARD / IMAGE_BACKDROP / core.difficulty 的难度色",
        "value": "见下方常量与 core/difficulty.py",
        "reason": "游戏内选曲卡面的复刻色和判断贴图透明边缘用的纯黑，是内容不是 UI Token，"
                  "不参与亮暗切换，也不受 Neutral / Accent / Semantic 管辖。",
    },
    {
        "token": "检查器内部分组不使用 Card",
        "value": "Section 标题 + 行 + separator.subtle",
        "reason": "规范 3.4 的 Desktop Settings 默认就是 Section + 行；检查器面板本身已经是"
                  "一层 surface，再套一层 Card 属于 2.5 说的「外层 Surface 已经提供清晰边界，"
                  "再加 Card 只会重复包裹」。",
    },
)


# --------------------------------------------------------------------------
# 颜色
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Semantic:
    """
    一个语义色族 / One semantic colour family.

    四个族（success / warning / error / info）结构相同，各自独立生成，
    不从品牌色推导。
    """

    solid: str
    subtle: str
    text: str
    border: str
    on_solid: str


@dataclass(frozen=True)
class Palette:
    """
    一套完整的语义色 / One complete semantic palette.

    Light 和 Dark 各一份，**不是互为反色**：Light 的层级靠接近白的微小明度差，
    Dark 靠 Surface 随层级提亮；Accent 更是两种形态——Light 深底白字，
    Dark 浅底深字。
    """

    mode: str

    canvas: str
    surface: str
    surface_elevated: str
    surface_sunken: str

    text_primary: str
    text_secondary: str
    text_tertiary: str
    text_disabled: str
    text_inverse: str

    separator_subtle: str
    separator_strong: str
    border_default: str

    fill_control: str
    fill_hover: str
    fill_pressed: str

    scrim: str

    accent_primary: str
    accent_hover: str
    accent_pressed: str
    accent_subtle: str
    accent_subtle_hover: str
    accent_text: str
    accent_border: str
    accent_focus: str
    accent_on_accent: str

    success: Semantic
    warning: Semantic
    error: Semantic
    info: Semantic

    #: 阴影。规范给的是结构化字段，不是某个平台的表达式字符串。
    elevation_1: "Shadow" = field(default=None)  # type: ignore[assignment]
    elevation_2: "Shadow" = field(default=None)  # type: ignore[assignment]

    def semantic(self, name: str) -> Semantic:
        """
        按名字取一个语义色族 / One semantic family by name.

        参数 / Parameters:
            name (str): ``success`` / ``warning`` / ``error`` / ``info``。

        返回 / Returns:
            Semantic: 对应的色族。

        异常 / Raises:
            KeyError: 名字不在四个族里。
        """
        table = {"success": self.success, "warning": self.warning,
                 "error": self.error, "info": self.info}
        return table[name]

    #: 文字承载面集合。规范 2.1 要求每个文字 Token 在这些面上逐一达标，
    #: 不能只对 canvas 校验一次。fill.hover / fill.pressed / accent.subtleHover
    #: **不在**集合内——整行 hover 时行内辅助文字提升为 text.secondary。
    def text_bearing_surfaces(self) -> Dict[str, str]:
        """文字可以落在哪些面上 / The surfaces text is guaranteed to be readable on."""
        return {
            "canvas": self.canvas,
            "surface": self.surface,
            "surfaceElevated": self.surface_elevated,
            "surfaceSunken": self.surface_sunken,
            "fill.control": self.fill_control,
            "accent.subtle": self.accent_subtle,
            "success.subtle": self.success.subtle,
            "warning.subtle": self.warning.subtle,
            "error.subtle": self.error.subtle,
            "info.subtle": self.info.subtle,
        }


@dataclass(frozen=True)
class Shadow:
    """
    一档阴影 / One elevation step.

    字段就是规范里那五个，长度单位是逻辑像素。Qt 取 ``blur`` 作
    ``blurRadius``、``(x, y)`` 作 offset；``spread`` Qt 没有对应概念，保持 0。
    """

    x: int
    y: int
    blur: int
    spread: int
    color: str


ELEVATION_1_LIGHT = Shadow(0, 1, 3, 0, "rgba(0, 0, 0, 0.10)")
ELEVATION_2_LIGHT = Shadow(0, 4, 16, 0, "rgba(0, 0, 0, 0.14)")
ELEVATION_1_DARK = Shadow(0, 1, 3, 0, "rgba(0, 0, 0, 0.28)")
ELEVATION_2_DARK = Shadow(0, 4, 16, 0, "rgba(0, 0, 0, 0.32)")


LIGHT = Palette(
    mode="light",

    canvas="#FBF9FE",
    surface="#FEFEFF",
    surface_elevated="#FFFFFF",
    surface_sunken="#F2F0F5",

    text_primary="#1B1A1D",
    text_secondary="#504F53",
    text_tertiary="#68676A",
    text_disabled="#939195",
    text_inverse="#FFFFFF",

    separator_subtle="#D5D4D8",
    separator_strong="#B9B7BC",
    border_default="#908F93",

    fill_control="#E8E7EB",
    fill_hover="#DFDDE2",
    fill_pressed="#D3D2D6",

    scrim="rgba(0, 0, 0, 0.32)",

    accent_primary="#7C5BAF",
    accent_hover="#7353A6",
    accent_pressed="#6F4EA1",
    accent_subtle="#F1EBFE",
    accent_subtle_hover="#E6E0F3",
    accent_text="#7555A8",
    accent_border="#8F7AB6",
    accent_focus="#7C5BAF",
    accent_on_accent="#FFFFFF",

    success=Semantic("#519D55", "#E1F5E0", "#2E7C35", "#5E905F", "#1B1A1D"),
    warning=Semantic("#EAAA40", "#FFEFDB", "#956400", "#A77D3B", "#1B1A1D"),
    error=Semantic("#E35451", "#FFE9E7", "#C63738", "#CA6862", "#1B1A1D"),
    info=Semantic("#3C93D5", "#E1F1FF", "#0D71B1", "#538AB7", "#1B1A1D"),

    elevation_1=ELEVATION_1_LIGHT,
    elevation_2=ELEVATION_2_LIGHT,
)


DARK = Palette(
    mode="dark",

    canvas="#100F12",
    surface="#17171A",
    surface_elevated="#212023",
    surface_sunken="#08080A",

    text_primary="#ECEAEF",
    text_secondary="#B1B0B4",
    text_tertiary="#939195",
    text_disabled="#656468",
    text_inverse="#1B1A1D",

    separator_subtle="#2A292C",
    separator_strong="#3E3D40",
    border_default="#6C6B6F",

    fill_control="#1E1D20",
    fill_hover="#2A292D",
    fill_pressed="#373639",

    scrim="rgba(0, 0, 0, 0.52)",

    accent_primary="#BD9DF7",
    accent_hover="#C6A7FF",
    accent_pressed="#CAAEFF",
    accent_subtle="#292139",
    accent_subtle_hover="#342B44",
    accent_text="#BD9DF7",
    accent_border="#735F98",
    accent_focus="#BD9DF7",
    accent_on_accent="#1B1A1D",

    success=Semantic("#78BF7B", "#1A2C1A", "#78BF7B", "#467347", "#1B1A1D"),
    warning=Semantic("#F4B85B", "#342611", "#F4B85B", "#876224", "#1B1A1D"),
    error=Semantic("#F97770", "#3A1D1B", "#F97770", "#A44F4A", "#1B1A1D"),
    info=Semantic("#72B8F2", "#142838", "#72B8F2", "#406D92", "#1B1A1D"),

    elevation_1=ELEVATION_1_DARK,
    elevation_2=ELEVATION_2_DARK,
)


# --------------------------------------------------------------------------
# 排版
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TypeStyle:
    """
    一档字 / One step of the type scale.

    ``size`` 和 ``line_height`` 是两个独立数值，映射时分别取用，
    不要用同一个数填两处（规范 2.2「字号映射」）。``weight`` 是 CSS 数值
    字重，400 Regular / 500 Medium / 600 Semibold。
    """

    size: int
    line_height: int
    weight: int


#: 规范 2.2 的 Desktop 列，一个字不改。别在别处随手写字号，从这张表里挑一档。
TYPE: Dict[str, TypeStyle] = {
    "pageTitle": TypeStyle(22, 28, 600),
    "title": TypeStyle(17, 22, 600),
    "sectionTitle": TypeStyle(14, 18, 600),
    "body": TypeStyle(13, 18, 400),
    "secondary": TypeStyle(12, 16, 400),
    "caption": TypeStyle(11, 15, 400),
    "metric": TypeStyle(28, 34, 600),
    "button": TypeStyle(13, 18, 500),
    "mono": TypeStyle(12, 18, 400),
}

#: 按 WCAG 判定能享受 3:1 门槛的「大号文本」。字号 ≥24 任意字重，或 ≥18.66 且
#: 字重达 Bold(700)。Semibold(600) 不按 Bold 放宽——所以桌面端只有 metric 一个。
LARGE_TEXT_ROLES = ("metric",)


# --------------------------------------------------------------------------
# 间距 / 圆角 / 尺寸
# --------------------------------------------------------------------------

#: 基础单位 4。语义间距在下面，组件优先用语义那一组。
SPACE = {1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40}

GAP_INLINE = 8
GAP_RELATED = 4
GAP_CONTROL = 8
GAP_GROUP = 16
GAP_SECTION = 24

PADDING_CONTROL_X = 12
PADDING_CONTROL_Y = 8
PADDING_CONTAINER = 16
PADDING_PAGE_X = 24
PADDING_PAGE_Y = 24

RADIUS_SMALL = 6
RADIUS_MEDIUM = 10
RADIUS_LARGE = 14

#: 规范 3.4 的 Desktop 设置行度量。行高是**下限**，长文本和系统字号放大时继续长，
#: 不为了守住这个数截断内容。
ROW_MIN_HEIGHT = 32
ROW_WITH_CAPTION_MIN_HEIGHT = 48
PAGE_TITLE_TO_SECTION = 24
SECTION_TITLE_TO_ROWS = 8

#: 自绘图标尺寸（规范 2.6 的 Desktop 值）。视觉尺寸不改变命中区。
ICON_INLINE = 16
ICON_ACTION = 20

#: Focus 环：2px 宽，向外偏移 2px，中间露出控件所在的 Surface（规范 2.5）。
#: 容器必须为这 4px 预留空间，否则环会被裁掉。
FOCUS_RING_WIDTH = 2
FOCUS_RING_OFFSET = 2

#: Tooltip（规范 4.7）。
TOOLTIP_MAX_WIDTH = 280
TOOLTIP_DELAY_MS = 500


# --------------------------------------------------------------------------
# 动效
# --------------------------------------------------------------------------

MOTION_IMMEDIATE = 120
MOTION_SMALL = 180
MOTION_MEDIUM = 260
MOTION_LARGE = 360

#: 进入与状态变化用的缓动，离场用另一条（规范 2.7）。四个控制点，
#: 对应 CSS 的 ``cubic-bezier(x1, y1, x2, y2)``。
EASE_ENTER = (0.2, 0.0, 0.0, 1.0)
EASE_EXIT = (0.4, 0.0, 1.0, 1.0)

#: 系统开了「减少动态效果」时：位移和缩放归零，颜色与透明度统一这个时长。
MOTION_REDUCED_COLOUR = 100


# --------------------------------------------------------------------------
# 层叠顺序
# --------------------------------------------------------------------------

#: 规范 2.5「层叠顺序」。浮层不靠临时数值互相压。
LAYER_CONTENT = 0
LAYER_NAV = 100
LAYER_POPOVER = 200
LAYER_SHEET = 300
LAYER_DIALOG = 400
LAYER_TOAST = 500
LAYER_TOOLTIP = 600


# --------------------------------------------------------------------------
# 内容色：不属于设计系统的那部分
# --------------------------------------------------------------------------

#: 仿游戏内选曲卡面的复刻色。**这不是 UI Token**：它复刻的是游戏画面，
#: 跟着亮暗模式变反而认不出来了。改这里等于改「像不像游戏里那张卡」。
GAME_CARD: Dict[str, str] = {
    "frame": "#CCFFFFFF",       # 卡片外框，半透明白
    "cover_frame": "#F2FFFFFF",  # 曲绘那一圈更实的白边
    "cover_backdrop": "#111827",  # 曲绘没解出来时垫在底下的深蓝黑
    "level_box": "#222B36",     # LEVEL 小格
    "name_bar": "#F8F5EA",      # 米白色曲名条
    "name_text": "#1A1A1A",     # 曲名条上的字
}

#: 游戏卡面上的字号。同样是复刻尺寸，不走 TYPE 那张表。
GAME_CARD_TYPE: Dict[str, int] = {
    "level_caption": 7,
    "level_value": 13,
    "difficulty": 10,
    "title": 10,
}

#: 游戏卡面的尺寸。**LEVEL 小格必须放得下四个字符**：这个工具显示的是定数
#: （``13.2``）而不是游戏内的 ``13+``，格子按后者的宽度给会把它省略成「1…」。
GAME_CARD_LAYOUT: Dict[str, int] = {
    "width": 132,
    "height": 160,
    "padding": 6,
    "cover_height": 92,
    "strip_height": 28,
    "level_width": 56,
}

#: 看图区的底。贴图必须落在纯黑上——周围有底色会干扰对透明边缘的判断，
#: 所以浅色模式下它也是黑的。
IMAGE_BACKDROP = "#000000"


def resolved() -> Dict[str, object]:
    """
    解析后的全套 Token / Every token, fully resolved.

    规范 10.1 第 6 条要求开发构建能把解析后的 Typography Token 打出来，
    顺手把颜色、间距、圆角、动效一起给了。

    返回 / Returns:
        Dict[str, object]: 可以直接 ``json.dumps`` 的嵌套字典。
    """
    return {
        "designSystemRevision": DESIGN_SYSTEM_REVISION,
        "platform": PLATFORM,
        "brand": {"direction": BRAND_DIRECTION, "hue": BRAND_HUE, "chroma": BRAND_CHROMA},
        "typography": {name: asdict(style) for name, style in TYPE.items()},
        "spacing": {
            "space": SPACE,
            "gap": {"inline": GAP_INLINE, "related": GAP_RELATED, "control": GAP_CONTROL,
                    "group": GAP_GROUP, "section": GAP_SECTION},
            "padding": {"control.x": PADDING_CONTROL_X, "control.y": PADDING_CONTROL_Y,
                        "container": PADDING_CONTAINER,
                        "page.x": PADDING_PAGE_X, "page.y": PADDING_PAGE_Y},
        },
        "radius": {"small": RADIUS_SMALL, "medium": RADIUS_MEDIUM, "large": RADIUS_LARGE},
        "motion": {"immediate": MOTION_IMMEDIATE, "small": MOTION_SMALL,
                   "medium": MOTION_MEDIUM, "large": MOTION_LARGE,
                   "easeEnter": EASE_ENTER, "easeExit": EASE_EXIT,
                   "reducedColour": MOTION_REDUCED_COLOUR},
        "layer": {"content": LAYER_CONTENT, "nav": LAYER_NAV, "popover": LAYER_POPOVER,
                  "sheet": LAYER_SHEET, "dialog": LAYER_DIALOG, "toast": LAYER_TOAST,
                  "tooltip": LAYER_TOOLTIP},
        "color": {"light": asdict(LIGHT), "dark": asdict(DARK)},
        "overrides": [dict(item) for item in OVERRIDES],
    }


if __name__ == "__main__":  # pragma: no cover - 开发构建用的输出口
    import json

    print(json.dumps(resolved(), ensure_ascii=False, indent=2))
