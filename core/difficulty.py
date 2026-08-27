# -*- coding: utf-8 -*-
"""
难度的唯一真源 / The one place difficulty is defined.

``Music.xml`` 把难度存成 ``ID_00``..``ID_05``，另有 ``ULTRA`` / ``WorldsEnd``
这些历史写法。全流程只认 :func:`normalise` 吐出来的六个规范值：

    BASIC / ADVANCED / EXPERT / MASTER / ULTIMA / WORLD'S END

配色、排序、筛选、卡面全部从这里取。散在各处各写一份的话，同一个难度在列表里
是一个颜色、在卡面上是另一个颜色，而这种错误没人会当成 bug 报上来。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

#: 规范难度名，按游戏内的从易到难排列。
ORDER: Tuple[str, ...] = ("BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA", "WORLD'S END")

#: XML 里的原始写法 → 规范名。
_ALIASES: Dict[str, str] = {
    "ID_00": "BASIC",
    "ID_01": "ADVANCED",
    "ID_02": "EXPERT",
    "ID_03": "MASTER",
    "ID_04": "ULTIMA",
    "ID_05": "WORLD'S END",
    "ULTRA": "ULTIMA",
    "WORLDSEND": "WORLD'S END",
    "WORLD'SEND": "WORLD'S END",
}

#: 难度色。取自游戏内配色，不是 Apple 系统色——这一组是**数据的颜色**，
#: 玩家一眼认的就是它们，改了反而看不懂。界面本身的配色在 ui/theme.py。
COLOURS: Dict[str, str] = {
    "BASIC": "#00A985",
    "ADVANCED": "#F97700",
    "EXPERT": "#E02929",
    "MASTER": "#B700FF",
    "ULTIMA": "#000000",
}

#: 没有难度（谱面全空 / 解析失败）时的底色。
FALLBACK_COLOUR = "#485466"

#: WORLD'S END 是彩虹渐变，不是单色。``(位置 0~1, 颜色)``，交给界面去画。
WORLDS_END_GRADIENT: List[Tuple[float, str]] = [
    (0.00, "#FF2C4C"),
    (0.20, "#FFBA00"),
    (0.40, "#00B46E"),
    (0.62, "#00A8FF"),
    (0.82, "#9244FF"),
    (1.00, "#FF46D2"),
]


def normalise(value: str) -> str:
    """
    把 XML 里的写法归一成规范难度名 / Normalise a raw difficulty string.

    参数 / Parameters:
        value (str): ``Music.xml`` 里 ``type/data`` 或 ``type/str`` 的原文。

    返回 / Returns:
        str: 六个规范名之一；认不出来就返回大写后的原文，
        让它在界面上显形而不是被悄悄吞掉。
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    return _ALIASES.get(upper, upper)


def rank(value: str) -> int:
    """
    排序用的序号 / Sort order, easiest first.

    返回 / Returns:
        int: 0~5；不认识的难度返回 -1，排在所有已知难度前面。
    """
    normalised = normalise(value)
    return ORDER.index(normalised) if normalised in ORDER else -1


def colour(value: str) -> str:
    """
    难度的底色 / The fill colour for a difficulty.

    WORLD'S END 没有单色，这里返回渐变的中段色，只给「需要一个纯色」的场合
    （比如卡面边框）用；真正画标签时请用 :data:`WORLDS_END_GRADIENT`。
    """
    normalised = normalise(value)
    if normalised == "WORLD'S END":
        return "#00B46E"
    return COLOURS.get(normalised, FALLBACK_COLOUR)


def foreground(value: str) -> str:
    """
    难度底色上的字色 / Text colour on top of that fill.

    只有 ADVANCED 那支橙用黑字：白字压在 ``#F97700`` 上只有 2.4:1，看不清。
    """
    return "#000000" if normalise(value) == "ADVANCED" else "#FFFFFF"


def is_worlds_end(value: str) -> bool:
    """是不是 WORLD'S END / Is this the rainbow one?"""
    return normalise(value) == "WORLD'S END"


def level_text(level: int, level_decimal: int) -> str:
    """
    定数的显示写法 / How a level reads on screen.

    参数 / Parameters:
        level (int): ``<level>``。
        level_decimal (int): ``<levelDecimal>``，游戏里存的是百分位，
            如 ``60`` 表示 ``.6``。

    返回 / Returns:
        str: ``15.6`` / ``11`` / ``-``（没有定数时）。
    """
    if level <= 0:
        return "-"
    if level_decimal > 0:
        return "{}.{}".format(level, level_decimal // 10)
    return str(level)
