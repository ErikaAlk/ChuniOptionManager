# -*- coding: utf-8 -*-
"""
数据模型 / The data classes.

纯数据 + 几个纯函数派生属性。**不认识任何界面对象**：图片在这里只是路径，
解码和缓存是 ui 那边的事，这样引擎和测试都能在没有 Qt 的解释器里跑起来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core import difficulty


def _contains(haystack: str, needle: str) -> bool:
    """不区分大小写的包含 / Case-insensitive contains."""
    return needle.lower() in (haystack or "").lower()


@dataclass
class ChartModel:
    """一个难度的谱面 / One chart of one song."""

    index: int = 0
    difficulty: str = ""
    file_name: str = ""
    full_path: str = ""
    level: int = 0
    level_decimal: int = 0
    file_exists: bool = False
    notes_designer: str = ""
    enabled: bool = False

    @property
    def level_text(self) -> str:
        """定数的显示写法 / The level as shown."""
        return difficulty.level_text(self.level, self.level_decimal)

    @property
    def problem_text(self) -> str:
        """这一档现在是什么状况 / One line on this chart's state."""
        if self.enabled and not self.file_exists:
            return "启用但文件缺失"
        if not self.enabled and self.file_exists:
            return "文件存在但未启用"
        return "文件正常" if self.file_exists else "无谱面文件"

    @property
    def rank(self) -> int:
        """排序序号 / Sort order."""
        return difficulty.rank(self.difficulty)


@dataclass
class MusicItem:
    """一首歌 / One song, one Music.xml."""

    title: str = ""
    sort_title: str = ""
    artist: str = ""
    genre: str = ""
    works: str = ""
    package: str = ""
    data_name: str = ""
    release_tag: str = ""
    xml_path: str = ""
    relative_path: str = ""
    jacket_path: str = ""
    song_id: int = 0
    disable_flag: bool = False
    enable_ultima: bool = False
    charts: List[ChartModel] = field(default_factory=list)

    @property
    def enabled_charts(self) -> List[ChartModel]:
        """开着的谱面 / Charts the game will load."""
        return [chart for chart in self.charts if chart.enabled]

    @property
    def existing_enabled_charts(self) -> List[ChartModel]:
        """开着且文件真的在的谱面 / Enabled charts whose .c2s is present."""
        return [chart for chart in self.charts if chart.enabled and chart.file_exists]

    @property
    def has_missing_enabled_file(self) -> bool:
        """有没有「开着但文件不在」的谱面 / Any enabled-but-missing chart?"""
        return any(chart.enabled and not chart.file_exists for chart in self.charts)

    @property
    def primary_chart(self) -> Optional[ChartModel]:
        """
        卡面上代表这首歌的那一档 / The chart the card shows.

        优先「开着且文件在」的最高难度，退而求其次是开着的最高难度，
        再退就是任意最高难度——三层都空才返回 ``None``。
        """
        for pool in (self.existing_enabled_charts, self.enabled_charts, self.charts):
            if pool:
                return max(pool, key=lambda chart: (chart.rank, chart.level))
        return None

    @property
    def primary_difficulty(self) -> str:
        """代表难度 / The card's difficulty label."""
        chart = self.primary_chart
        return chart.difficulty if chart else "NO DATA"

    @property
    def primary_level(self) -> str:
        """代表定数 / The card's level."""
        chart = self.primary_chart
        return chart.level_text if chart else "-"

    @property
    def card_sub_text(self) -> str:
        """卡面第二行 / The card's second line: artist, or the package."""
        return self.artist if self.artist.strip() else self.package

    def has_enabled(self, wanted: str) -> bool:
        """这首歌有没有开着的某个难度 / Is this difficulty enabled here?"""
        return any(chart.difficulty == wanted for chart in self.enabled_charts)

    def matches(self, query: str) -> bool:
        """搜索命中 / Does this song match the search box?"""
        text = query.strip()
        if not text:
            return True
        return (
            _contains(self.title, text)
            or _contains(self.artist, text)
            or _contains(self.genre, text)
            or _contains(self.works, text)
            or _contains(self.data_name, text)
            or text in str(self.song_id)
        )


@dataclass
class CharacterItem:
    """一个角色 / One character, one Chara.xml."""

    name: str = ""
    sort_name: str = ""
    works: str = ""
    illustrator_name: str = ""
    explain_text: str = ""
    package: str = ""
    data_name: str = ""
    release_tag: str = ""
    net_open_name: str = ""
    xml_path: str = ""
    relative_path: str = ""
    dds_xml_path: str = ""
    dds_relative_path: str = ""
    image_key: str = ""
    big_image_path: str = ""
    small_image_path: str = ""
    thumb_image_path: str = ""
    character_id: int = 0
    works_id: int = 0
    release_tag_id: int = 0
    net_open_id: int = 0
    illustrator_id: int = 0
    disable_flag: bool = False
    default_have: bool = False
    rare_type: int = 0
    priority: int = 0

    def image_path(self, kind: str) -> str:
        """按 ``big`` / ``small`` / ``thumb`` 取贴图路径 / Path of one texture."""
        return {
            "small": self.small_image_path,
            "thumb": self.thumb_image_path,
        }.get(kind, self.big_image_path)

    def matches(self, query: str) -> bool:
        """搜索命中 / Does this character match the search box?"""
        text = query.strip()
        if not text:
            return True
        return (
            _contains(self.name, text)
            or _contains(self.works, text)
            or _contains(self.data_name, text)
            or text in str(self.character_id)
        )


@dataclass
class WorksItem:
    """一个作品 / One works entry, one CharaWorks.xml."""

    works_id: int = 0
    name: str = ""
    sort_name: str = ""
    priority: int = 0
    package: str = ""
    xml_path: str = ""
    relative_path: str = ""

    @property
    def display(self) -> str:
        """下拉框里的写法 / How it reads in a combo box."""
        return "{}（{}）".format(self.name, self.works_id)


@dataclass
class IssueItem:
    """一条排查项 / One row on the issues page."""

    severity: str = "Info"
    title: str = ""
    detail: str = ""
    path: str = ""

    @property
    def severity_rank(self) -> int:
        """排序序号，越严重越靠前 / Sort order, worst first."""
        return {"High": 0, "Medium": 1, "Low": 2}.get(self.severity, 3)


@dataclass
class OptionCatalog:
    """一次扫描的全部结果 / Everything one scan found."""

    songs: List[MusicItem] = field(default_factory=list)
    characters: List[CharacterItem] = field(default_factory=list)
    issues: List[IssueItem] = field(default_factory=list)
