# -*- coding: utf-8 -*-
"""
设计 Token / The design tokens.

这一组测的不是「好不好看」，是**规范里那些能算出来的硬条件**：对比度、控件边界、
焦点指示、状态之间的明度差、以及「每个 Token 都解析成单值」。

色板是人工校准过再固化进 :mod:`ui.tokens` 的，生成器不参与运行时。所以对比度
计算在这里自己实现一份——测试依赖那个离线工具的话，工具一改测试就跟着变，
那就不是守着色板了。
"""

from __future__ import annotations

import re
from pathlib import Path

from ui import tokens

#: WCAG 的两档门槛。普通文本 4.5，控件边界和焦点指示 3.0。
TEXT_TARGET = 4.5
BOUNDARY_TARGET = 3.0


def _channel(value: float) -> float:
    """一个 sRGB 通道转线性 / One sRGB channel, linearised."""
    value /= 255.0
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    """
    相对亮度 / WCAG relative luminance.

    参数 / Parameters:
        hex_colour (str): ``#RRGGBB``。

    返回 / Returns:
        float: 0 到 1。
    """
    red, green, blue = (int(hex_colour[index:index + 2], 16) for index in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast(one: str, other: str) -> float:
    """
    两个颜色的对比度 / The WCAG contrast ratio between two colours.

    参数 / Parameters:
        one (str): ``#RRGGBB``。
        other (str): ``#RRGGBB``。

    返回 / Returns:
        float: 1.0 到 21.0。
    """
    first, second = luminance(one), luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def oklch_lightness(hex_colour: str) -> float:
    """
    OKLCH 的 L / The OKLCH lightness of one colour.

    规范说的「状态之间的明度差」是 OKLCH 的 L，不是 WCAG 亮度——两者差得很远，
    用错了这条测试就形同虚设。

    参数 / Parameters:
        hex_colour (str): ``#RRGGBB``。

    返回 / Returns:
        float: 0 到 1。
    """
    red, green, blue = (_channel(int(hex_colour[index:index + 2], 16)) for index in (1, 3, 5))
    long = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    medium = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    short = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    long, medium, short = (value ** (1 / 3) if value >= 0 else -((-value) ** (1 / 3))
                           for value in (long, medium, short))
    return 0.2104542553 * long + 0.7936177850 * medium - 0.0040720468 * short


PALETTES = (("light", tokens.LIGHT), ("dark", tokens.DARK))


def test_every_text_token_is_readable_on_every_bearing_surface() -> None:
    """
    文字在整个承载面集合上都达标 / Text passes on the whole bearing set.

    规范 2.1 明确写着「不能只对 canvas 校验一次」。这条最容易漏的是
    ``fill.control``（浅色下是三个面里最暗的）和深色的 ``warning.subtle``
    （深色下最亮）——它们才是把 ``text.tertiary`` 顶出边界的那两个面。
    """
    for mode, active in PALETTES:
        for surface_name, surface in active.text_bearing_surfaces().items():
            for token in ("text_primary", "text_secondary", "text_tertiary"):
                ratio = contrast(getattr(active, token), surface)
                assert ratio >= TEXT_TARGET, (
                    "{} 模式：{} 压在 {} 上只有 {:.2f}:1".format(
                        mode, token, surface_name, ratio))


def test_control_boundaries_reach_three_to_one() -> None:
    """
    控件边界看得见 / Control boundaries are actually discernible.

    规范 2.5 让自绘 Input 用 ``fill.control`` 加 1px ``border.default``，
    2.1 又要求控件边界至少 3:1。填充本身离 Surface 只有 1.1 左右，
    **全靠这条边**——它不达标的话，输入框在哪里就只能靠猜。
    """
    for mode, active in PALETTES:
        for surface_name in ("canvas", "surface", "surface_elevated"):
            ratio = contrast(active.border_default, getattr(active, surface_name))
            assert ratio >= BOUNDARY_TARGET, (
                "{} 模式：border.default 压在 {} 上只有 {:.2f}:1".format(
                    mode, surface_name, ratio))


def test_the_focus_ring_stands_out_wherever_it_lands() -> None:
    """
    焦点环在它压住的每个面上都够 3:1 / The focus ring is visible on every surface.

    可见 Focus 是规范 08 的底线。焦点环画在控件外面，压住的是控件所在的
    Surface，所以三个面都要测。
    """
    for mode, active in PALETTES:
        for surface_name in ("canvas", "surface", "surface_elevated"):
            ratio = contrast(active.accent_focus, getattr(active, surface_name))
            assert ratio >= BOUNDARY_TARGET, (
                "{} 模式：accent.focus 压在 {} 上只有 {:.2f}:1".format(
                    mode, surface_name, ratio))


def test_the_accent_foreground_survives_all_three_states() -> None:
    """
    主按钮的字在三态里都读得出来 / onAccent holds across default, hover and pressed.

    规范 2.1 要求 ``onAccent`` 三态一致——交互时文字突然反色是很难看的。
    一致之后风险就落在最难的那一态上，所以三个都要算。
    """
    for mode, active in PALETTES:
        for state in ("accent_primary", "accent_hover", "accent_pressed"):
            ratio = contrast(active.accent_on_accent, getattr(active, state))
            assert ratio >= TEXT_TARGET, (
                "{} 模式：onAccent 压在 {} 上只有 {:.2f}:1".format(mode, state, ratio))


def test_the_accent_states_step_the_right_way() -> None:
    """
    Hover 和 Pressed 同方向，Pressed 走得更远 / Both states move one way, pressed further.

    规范 2.1 给的是确定值：自绘控件按 OKLCH Lightness 差 0.03 生成 Hover、
    0.045 生成 Pressed。生成器最初给的深色方案是「hover 变亮、pressed 变暗」，
    那样按下去的反馈方向和悬停相反，这条就是挡它的。
    """
    for mode, active in PALETTES:
        base = oklch_lightness(active.accent_primary)
        hover = oklch_lightness(active.accent_hover) - base
        pressed = oklch_lightness(active.accent_pressed) - base
        assert hover * pressed > 0, "{} 模式：hover 和 pressed 的方向相反".format(mode)
        assert abs(pressed) > abs(hover), "{} 模式：pressed 的变化没有比 hover 明显".format(mode)
        assert abs(abs(hover) - 0.030) <= 0.006, "{} 模式：hover 的 ΔL 是 {:.3f}".format(mode, hover)
        assert abs(abs(pressed) - 0.045) <= 0.006, (
            "{} 模式：pressed 的 ΔL 是 {:.3f}".format(mode, pressed))


def test_light_and_dark_are_two_mappings_not_one_inverted() -> None:
    """
    两套映射，不是反色 / Light and dark are separate mappings.

    规范 2.1：「Light 与 Dark 是两套映射，不是反色，也不共用一个品牌色值。」
    本项目更明显——浅色是深底白字、深色是浅底深字，两边的 Accent 和 Canvas
    是相反的关系。
    """
    assert tokens.LIGHT.accent_primary != tokens.DARK.accent_primary
    assert tokens.LIGHT.canvas != tokens.DARK.canvas
    assert tokens.LIGHT.accent_on_accent != tokens.DARK.accent_on_accent

    # 浅色的强调填充比页面底暗，深色的比页面底亮
    assert luminance(tokens.LIGHT.accent_primary) < luminance(tokens.LIGHT.canvas)
    assert luminance(tokens.DARK.accent_primary) > luminance(tokens.DARK.canvas)


def test_every_semantic_family_is_readable_where_it_is_used() -> None:
    """
    四个语义色族各自成立 / Each semantic family holds where it is used.

    规范 2.1：``text`` 要在 Canvas 和自己的 Subtle 上都可读，``border`` 承担
    状态表达时至少 3:1，``onSolid`` 不能默认白色、要按整组 Solid 算。
    """
    for mode, active in PALETTES:
        for name in ("success", "warning", "error", "info"):
            family = active.semantic(name)
            assert contrast(family.text, active.canvas) >= TEXT_TARGET, (mode, name, "canvas")
            assert contrast(family.text, family.subtle) >= TEXT_TARGET, (mode, name, "subtle")
            assert contrast(family.border, active.canvas) >= BOUNDARY_TARGET, (mode, name, "border")
            assert contrast(family.on_solid, family.solid) >= TEXT_TARGET, (mode, name, "onSolid")


def test_the_brand_colour_never_becomes_the_error_colour() -> None:
    """
    错误色不从品牌色推导 / Error is its own colour, not a tinted brand.

    规范 2.1 把这条写成禁令：``error`` 与 ``destructive`` 始终使用独立语义色。
    薰衣草紫和红色离得远，但这条守的是「将来有人图省事把破坏性动作也染成品牌色」。
    """
    for _mode, active in PALETTES:
        assert active.error.solid != active.accent_primary
        assert active.error.text != active.accent_text


def test_no_interface_module_hardcodes_a_colour() -> None:
    """
    界面代码里一个 Hex 都不许有 / Not one hex literal outside the token file.

    规范 10.1：「业务组件只消费语义 Token，不散写 Hex、字号、间距、圆角、阴影与
    动画时长。」这条直接扫源码——上一版就是靠人盯，结果 ``cards.py`` 里躺着
    六个写死的颜色。
    """
    ui_dir = Path(__file__).resolve().parent.parent / "ui"
    pattern = re.compile(r"#[0-9A-Fa-f]{6}\b")
    offenders = []
    for path in sorted(ui_dir.glob("*.py")):
        if path.name == "tokens.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append("{}:{}".format(path.name, number))
    assert not offenders, "这些地方写死了颜色：{}".format("、".join(offenders))


def test_every_typography_token_resolves_to_a_single_value() -> None:
    """
    字阶全是解析好的单值 / Every type token is one resolved number.

    规范 10.1「实现前解析门槛」第 1、2 条：不许留区间、``auto``、``TBD``。
    顺手把「组标题必须比正文大」也钉上——规范 2.2 把它写成了硬要求。
    """
    for name, style in tokens.TYPE.items():
        assert isinstance(style.size, int) and style.size > 0, name
        assert isinstance(style.line_height, int) and style.line_height > style.size, name
        assert style.weight in (400, 500, 600), name

    assert tokens.TYPE["sectionTitle"].size > tokens.TYPE["body"].size


def test_the_theme_entry_records_its_revision_and_overrides() -> None:
    """
    覆盖登记写全了 / Every override is recorded with a value and a reason.

    规范 10.1 第 4 条要求项目覆盖全局默认时写出确定值与原因，
    并记录 ``designSystemRevision``。没有原因的覆盖过几个月就没人知道能不能动了。
    """
    assert tokens.DESIGN_SYSTEM_REVISION == "2026.08.31-a11y-baseline"
    assert tokens.OVERRIDES
    for item in tokens.OVERRIDES:
        assert item["token"].strip()
        assert item["value"].strip()
        assert len(item["reason"].strip()) > 20


def test_the_resolved_dump_covers_every_group() -> None:
    """
    解析结果能整份打印出来 / The resolved tokens can be dumped.

    规范 10.1 第 6 条：开发构建必须能输出解析后的 Typography Token。
    这里顺带确认颜色、间距、圆角、动效也在同一份里。
    """
    import json

    dump = tokens.resolved()
    for key in ("designSystemRevision", "typography", "spacing", "radius",
                "motion", "layer", "color", "overrides"):
        assert key in dump, key
    # 能序列化才算「输出得出来」
    assert json.dumps(dump, ensure_ascii=False)
