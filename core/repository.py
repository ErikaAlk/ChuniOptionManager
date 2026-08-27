# -*- coding: utf-8 -*-
"""
option 目录的全部读写 / Every read and write against the option tree.

界面之外的逻辑都在这里：扫描、排查、保存、软删除、新增角色、作品库。
纯函数式的模块级函数，没有依赖注入、没有全局状态——传 option 根目录进来，
拿结果出去。

三条不能破坏的约定：

1. **解析永远容错。** 一份坏掉的自定义 XML 只能让它自己不出现在列表里，
   不能让整个目录打不开。所以每个 parse 都包着 try。
2. **删除永远是软删除。** 目录移进 ``option\\_deleted\\<时间戳>_…\\``，
   扫描时跳过。真删除不提供，也不该提供。
3. **写之前先备份。** 每个文件第一次被保存时复制一份 ``.bak``，只复制一次。
"""

from __future__ import annotations

import os
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core import difficulty, xmlio
from core.models import (
    CharacterItem,
    ChartModel,
    IssueItem,
    MusicItem,
    OptionCatalog,
    WorksItem,
)
from core.paths import DELETED_DIR

#: 新角色 / 新作品的 priority。999 让它排在游戏内列表最前面，找得到。
DEFAULT_CUSTOM_PRIORITY = 999

#: 新增角色的模板包。``chara114514`` / ``ddsImage114514``（乳蛙）就在这里面。
TEMPLATE_PACKAGE = "AZUR"

#: 模板角色 / 模板作品的 ID。
TEMPLATE_CHARACTER_ID = 114514
DEFAULT_AZUR_WORKS_ID = 11451

#: 自动分配角色 ID 的下限。低于它的号段属于游戏本体，别去占。
MIN_CUSTOM_CHARACTER_ID = 114514


@dataclass
class CropSettings:
    """一张贴图的取景 / How one texture is framed out of the source image."""

    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass
class AddCharacterRequest:
    """新增角色要的全部信息 / Everything needed to create a character."""

    #: 显式角色 ID；``<=0`` 表示交给程序自动分配下一个空闲号。
    character_id: int = 0
    name: str = ""
    sort_name: str = ""
    illustrator_name: str = ""
    works_id: int = DEFAULT_AZUR_WORKS_ID
    works_name: str = "アズールレーン"
    source_image_path: str = ""
    crops: Dict[str, CropSettings] = field(default_factory=dict)


@dataclass(frozen=True)
class _DdsImageInfo:
    """DDSImage.xml 索引里的一条 / One entry of the texture index."""

    package: str
    xml_path: str
    relative_path: str
    big_path: str
    small_path: str
    thumb_path: str


# ---------------------------------------------------------------------------
# 扫描 / Scanning
# ---------------------------------------------------------------------------

def _walk(root: Path, wanted: Sequence[str], skip_deleted: bool = True) -> Dict[str, List[Path]]:
    """
    一趟走完整棵树，把要的几种文件一起收回来 / One walk, several file kinds.

    option 树有一万多个文件，每种文件各走一遍是四倍的 I/O。

    参数 / Parameters:
        root (Path): option 根目录。
        wanted (Sequence[str]): 要收集的文件名。
        skip_deleted (bool): 是否跳过回收区。

    返回 / Returns:
        Dict[str, List[Path]]: 文件名 → 命中的路径列表。
    """
    found: Dict[str, List[Path]] = {name: [] for name in wanted}
    targets = set(wanted)
    for current, dirs, files in os.walk(root):
        kept = [name for name in dirs if not name.startswith(".")]
        if skip_deleted:
            kept = [name for name in kept if name.lower() != DELETED_DIR]
        dirs[:] = kept
        for name in files:
            if name in targets:
                found[name].append(Path(current) / name)
    return found


def _package_name(root: Path, path: Path) -> str:
    """
    这个文件属于哪个包 / Which top-level option package holds this file.

    包名就是相对 option 根目录的第一段路径（``A001`` / ``AZUR`` / …）。
    """
    try:
        relative = Path(os.path.relpath(path, root))
    except ValueError:
        return ""
    parts = [part for part in relative.parts if part not in (".", "")]
    return parts[0] if parts else ""


def _relative(root: Path, path: Any) -> str:
    """相对 option 根目录的路径 / Path relative to the option root."""
    try:
        return os.path.relpath(str(path), str(root))
    except ValueError:
        return str(path)


def _build_dds_index(root: Path, paths: Iterable[Path]) -> Dict[str, List[_DdsImageInfo]]:
    """
    建一张「图片名 → 贴图文件」的索引 / Index textures by their image key.

    角色 ``Chara.xml`` 只写图片名（``chara114514_00``），贴图在别处的
    ``DDSImage.xml`` 里。同一个名字可能在多个包里各有一份，所以值是列表，
    取的时候优先同包（见 :func:`_resolve_dds_image`）。
    """
    index: Dict[str, List[_DdsImageInfo]] = {}
    for path in paths:
        try:
            document = xmlio.parse(path)
        except (ET.ParseError, OSError):
            continue  # 坏掉的自定义 XML 不该让整个目录打不开

        node = document.getroot()
        image_key = xmlio.text(node, "name", "str")
        if not image_key:
            continue

        directory = path.parent

        def resolve(tag: str) -> str:
            relative = xmlio.text(node, tag, "path")
            return str(directory / relative) if relative else ""

        index.setdefault(image_key.lower(), []).append(_DdsImageInfo(
            package=_package_name(root, path),
            xml_path=str(path),
            relative_path=_relative(root, path),
            big_path=resolve("ddsFile0"),
            small_path=resolve("ddsFile1"),
            thumb_path=resolve("ddsFile2"),
        ))
    return index


def _resolve_dds_image(
    index: Dict[str, List[_DdsImageInfo]],
    image_key: str,
    package: str,
) -> Optional[_DdsImageInfo]:
    """
    给角色配上贴图 / Pick the texture entry for one character.

    同包的优先：跨包同名是常见的覆盖手法，取错包就会显示成别人的立绘。
    """
    entries = index.get((image_key or "").lower())
    if not entries:
        return None
    for entry in entries:
        if entry.package.lower() == (package or "").lower():
            return entry
    return entries[0]


def _parse_music(root: Path, path: Path) -> Optional[MusicItem]:
    """
    解析一份 Music.xml / Parse one song, or ``None`` if it is unusable.
    """
    try:
        node = xmlio.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    if node is None:
        return None

    directory = path.parent
    charts: List[ChartModel] = []
    fumens = node.find("fumens")
    chart_nodes = list(fumens.findall("MusicFumenData")) if fumens is not None else []
    for index, chart_node in enumerate(chart_nodes):
        file_name = xmlio.text(chart_node, "file", "path")
        full_path = str(directory / file_name) if file_name else ""
        raw = xmlio.text(chart_node, "type", "data") or xmlio.text(chart_node, "type", "str")
        charts.append(ChartModel(
            index=index,
            difficulty=difficulty.normalise(raw),
            file_name=file_name,
            full_path=full_path,
            level=xmlio.int_of(chart_node, "level"),
            level_decimal=xmlio.int_of(chart_node, "levelDecimal"),
            file_exists=bool(full_path) and os.path.isfile(full_path),
            notes_designer=xmlio.text(chart_node, "notesDesigner"),
            enabled=xmlio.bool_of(chart_node, "enable"),
        ))

    genres: List[str] = []
    genre_list = node.find("genreNames")
    if genre_list is not None:
        inner = genre_list.find("list")
        if inner is not None:
            genres = [xmlio.text(item, "str") for item in inner.findall("StringID")]

    jacket = xmlio.text(node, "jaketFile", "path")
    return MusicItem(
        title=xmlio.text(node, "name", "str"),
        sort_title=xmlio.text(node, "sortName"),
        artist=xmlio.text(node, "artistName", "str"),
        genre=", ".join(item for item in genres if item),
        works=xmlio.text(node, "worksName", "str"),
        package=_package_name(root, path),
        data_name=xmlio.text(node, "dataName"),
        release_tag=xmlio.text(node, "releaseTagName", "str"),
        xml_path=str(path),
        relative_path=_relative(root, path),
        jacket_path=str(directory / jacket) if jacket else "",
        song_id=xmlio.int_of(node.find("name"), "id"),
        disable_flag=xmlio.bool_of(node, "disableFlag"),
        enable_ultima=xmlio.bool_of(node, "enableUltima"),
        charts=charts,
    )


def _parse_character(
    root: Path,
    path: Path,
    dds_index: Dict[str, List[_DdsImageInfo]],
) -> Optional[CharacterItem]:
    """解析一份 Chara.xml / Parse one character, or ``None`` if unusable."""
    try:
        node = xmlio.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    if node is None:
        return None

    package = _package_name(root, path)
    image_key = xmlio.text(node, "defaultImages", "str")
    image = _resolve_dds_image(dds_index, image_key, package)

    return CharacterItem(
        name=xmlio.text(node, "name", "str"),
        sort_name=xmlio.text(node, "sortName"),
        works=xmlio.text(node, "works", "str"),
        illustrator_name=xmlio.text(node, "illustratorName", "str"),
        explain_text=xmlio.text(node, "explainText"),
        package=package,
        data_name=xmlio.text(node, "dataName"),
        release_tag=xmlio.text(node, "releaseTagName", "str"),
        net_open_name=xmlio.text(node, "netOpenName", "str"),
        xml_path=str(path),
        relative_path=_relative(root, path),
        dds_xml_path=image.xml_path if image else "",
        dds_relative_path=image.relative_path if image else "",
        image_key=image_key,
        big_image_path=image.big_path if image else "",
        small_image_path=image.small_path if image else "",
        thumb_image_path=image.thumb_path if image else "",
        character_id=xmlio.int_of(node.find("name"), "id"),
        works_id=xmlio.int_of(node.find("works"), "id"),
        release_tag_id=xmlio.int_of(node.find("releaseTagName"), "id"),
        net_open_id=xmlio.int_of(node.find("netOpenName"), "id"),
        illustrator_id=xmlio.int_of(node.find("illustratorName"), "id"),
        disable_flag=xmlio.bool_of(node, "disableFlag"),
        default_have=xmlio.bool_of(node, "defaultHave"),
        rare_type=xmlio.int_of(node, "rareType"),
        priority=xmlio.int_of(node, "priority"),
    )


def scan(option_root: Any) -> OptionCatalog:
    """
    扫一遍整个 option 目录 / Scan the whole option tree.

    参数 / Parameters:
        option_root (Any): option 根目录。

    返回 / Returns:
        OptionCatalog: 歌曲、角色、排查项。坏掉的 XML 会被跳过，不会抛异常。
    """
    root = Path(option_root).resolve()
    found = _walk(root, ("Music.xml", "Chara.xml", "DDSImage.xml"))

    dds_index = _build_dds_index(root, found["DDSImage.xml"])

    songs = [item for item in (_parse_music(root, path) for path in found["Music.xml"]) if item]
    songs.sort(key=lambda song: (song.sort_title.casefold(), song.song_id))

    characters = [
        item for item in
        (_parse_character(root, path, dds_index) for path in found["Chara.xml"])
        if item
    ]
    characters.sort(key=lambda item: (item.sort_name.casefold(), item.character_id))

    return OptionCatalog(songs=songs, characters=characters, issues=build_issues(songs, characters))


def build_issues(
    songs: Sequence[MusicItem],
    characters: Sequence[CharacterItem],
) -> List[IssueItem]:
    """
    排查页的内容 / What the issues page lists.

    三类：

    * **High** ——「XML 里开着，谱面文件却不在」。同一首歌缺多个难度合并成一条，
      否则一首歌能刷出五行。
    * **Medium** —— 同 ID 的重复条目之间难度对不齐（多半是覆盖包只带了部分难度）。
    * **Low** —— 角色配不到贴图索引。

    WORLD'S END 拆成独立条目是**正常做法**，不报。

    参数 / Parameters:
        songs (Sequence[MusicItem]): 已解析的歌曲。
        characters (Sequence[CharacterItem]): 已解析的角色。

    返回 / Returns:
        List[IssueItem]: 按严重程度排好序。
    """
    issues: List[IssueItem] = []

    for song in songs:
        missing = sorted(
            (chart for chart in song.charts if chart.enabled and not chart.file_exists),
            key=lambda chart: chart.rank,
        )
        if not missing:
            continue
        issues.append(IssueItem(
            severity="High",
            title="{} 缺少 {}".format(song.title, ", ".join(chart.difficulty for chart in missing)),
            detail="XML 已启用，但找不到谱面文件：{}".format(
                "、".join(chart.file_name or "(未填写文件名)" for chart in missing)),
            path=song.relative_path,
        ))

    # 只对有效 ID（>0）比对重复：id=0 表示 name/id 缺失或不是数字，
    # 把它们归成一组会刷出一大堆假的「重复」。
    by_id: Dict[int, List[MusicItem]] = {}
    for song in songs:
        if song.song_id > 0:
            by_id.setdefault(song.song_id, []).append(song)

    for group in by_id.values():
        if len(group) < 2:
            continue
        signatures = {
            ",".join(sorted(chart.difficulty for chart in song.existing_enabled_charts))
            for song in group
        }
        if len(signatures) <= 1:
            continue

        union = sorted(
            {chart.difficulty for song in group for chart in song.existing_enabled_charts},
            key=difficulty.rank,
        )
        for song in group:
            present = {chart.difficulty for chart in song.existing_enabled_charts}
            missing_names = [name for name in union if name not in present]
            if not missing_names:
                continue
            issues.append(IssueItem(
                severity="Medium",
                title="{} 重复项少难度".format(song.title),
                detail="{}/{} 缺少 {}".format(song.package, song.data_name, ", ".join(missing_names)),
                path=song.relative_path,
            ))

    for character in characters:
        if not character.big_image_path or not os.path.isfile(character.big_image_path):
            issues.append(IssueItem(
                severity="Low",
                title="{} 缺少角色图索引".format(character.name),
                detail="defaultImages={}".format(character.image_key),
                path=character.relative_path,
            ))

    issues.sort(key=lambda issue: (issue.severity_rank, issue.title))
    return issues


# ---------------------------------------------------------------------------
# 保存 / Saving
# ---------------------------------------------------------------------------

def save_chart_enable_states(music: MusicItem) -> None:
    """
    把谱面开关写回 Music.xml / Write the enable toggles back.

    走字节级改写，除了 ``<enable>`` 之外一个字节都不动（见
    :func:`core.xmlio.replace_enable_flags`）。文件长得不认识时退回整份重写，
    保证功能永远可用。

    参数 / Parameters:
        music (MusicItem): 带着当前开关状态的歌曲。

    异常 / Raises:
        FileNotFoundError: ``Music.xml`` 不在了。
    """
    path = Path(music.xml_path)
    if not path.is_file():
        raise FileNotFoundError("找不到歌曲 Music.xml：{}".format(music.xml_path))

    xmlio.ensure_backup(path)
    states = [chart.enabled for chart in music.charts]
    if xmlio.replace_enable_flags(path, states):
        return

    document = xmlio.parse(path)
    fumens = document.getroot().find("fumens")
    nodes = list(fumens.findall("MusicFumenData")) if fumens is not None else []
    for chart in music.charts:
        if not 0 <= chart.index < len(nodes):
            continue
        node = nodes[chart.index]
        enable = node.find("enable")
        if enable is None:
            enable = ET.SubElement(node, "enable")
        enable.text = xmlio.bool_text(chart.enabled)
    # 保留原有空白：这条退路本来就是给「格式不认识」的文件用的，再重排一次
    # 只会把差异放得更大。
    xmlio.save_xml(document, path, xmlio.namespace_decls(path), reindent=False)


def save_character_settings(character: CharacterItem) -> None:
    """
    把角色的元数据写回 Chara.xml / Write character metadata back.

    参数 / Parameters:
        character (CharacterItem): 已经改好字段的角色。

    异常 / Raises:
        FileNotFoundError: ``Chara.xml`` 不在了。
        ValueError: 文件没有根节点。
    """
    path = Path(character.xml_path)
    if not path.is_file():
        raise FileNotFoundError("找不到角色 Chara.xml：{}".format(character.xml_path))

    decls = xmlio.namespace_decls(path)
    document = xmlio.parse(path)
    root = document.getroot()
    if root is None:
        raise ValueError("Chara.xml 没有根节点。")

    sort_name = character.sort_name.strip() or character.name.strip()
    xmlio.set_text(root, "disableFlag", xmlio.bool_text(character.disable_flag))
    xmlio.set_text(root, "name", "str", character.name.strip())
    xmlio.set_text(root, "sortName", sort_name)
    xmlio.set_text(root, "works", "id", str(character.works_id))
    xmlio.set_text(root, "works", "str", character.works.strip())
    xmlio.set_text(root, "defaultHave", xmlio.bool_text(character.default_have))
    xmlio.set_text(root, "rareType", str(character.rare_type))
    xmlio.set_text(root, "priority", str(character.priority))
    xmlio.set_text(root, "releaseTagName", "id", str(character.release_tag_id))
    xmlio.set_text(root, "releaseTagName", "str", character.release_tag.strip())
    xmlio.set_text(root, "netOpenName", "id", str(character.net_open_id))
    xmlio.set_text(root, "netOpenName", "str", character.net_open_name.strip())
    xmlio.set_text(root, "illustratorName", "id", str(character.illustrator_id))
    xmlio.set_text(root, "illustratorName", "str", character.illustrator_name.strip())
    xmlio.set_text(root, "explainText", character.explain_text.strip())

    xmlio.ensure_backup(path)
    xmlio.save_xml(document, path, decls)


# ---------------------------------------------------------------------------
# 软删除 / The recycle area
# ---------------------------------------------------------------------------

def _is_inside(root: Path, path: Path) -> bool:
    """path 在不在 root 里面 / Is *path* under *root*?"""
    try:
        relative = Path(os.path.relpath(path, root))
    except ValueError:
        return False
    return not str(relative).startswith("..") and not relative.is_absolute()


def _is_deleted_path(root: Path, path: Path) -> bool:
    """这条路径是不是已经在回收区里 / Is this already inside the recycle area?"""
    try:
        relative = Path(os.path.relpath(path, root))
    except ValueError:
        return False
    return any(part.lower() == DELETED_DIR for part in relative.parts)


_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_file_name(value: str) -> str:
    """
    把任意字符串削成能当目录名的样子 / Make a string safe as a folder name.

    截到 40 个字符：归档目录名里还要塞时间戳、类型和 ID，歌名太长会把整条
    路径顶过 Windows 的长度上限。
    """
    cleaned = _INVALID_NAME_CHARS.sub("_", value or "").strip()
    if not cleaned:
        return "item"
    return cleaned[:40]


def _move_to_deleted(
    option_root: Any,
    kind: str,
    item_id: int,
    name: str,
    sources: Iterable[Any],
) -> str:
    """
    把目录移进回收区 / Move directories into the recycle area.

    参数 / Parameters:
        option_root (Any): option 根目录。
        kind (str): ``song`` / ``character`` / ``works``，写进归档目录名。
        item_id (int): 条目 ID，同上。
        name (str): 条目名，同上。
        sources (Iterable[Any]): 要移走的目录。

    返回 / Returns:
        str: 归档目录的绝对路径。

    异常 / Raises:
        FileNotFoundError: 一个存在的源目录都没有。
        ValueError: 有目录在 option 根目录之外、就是根目录本身、
            或者已经在回收区里——这三种情况一律拒绝，不做删除。
    """
    root = Path(option_root).resolve()
    seen: Dict[str, Path] = {}
    for item in sources:
        if not item:
            continue
        resolved = Path(item).resolve()
        if resolved.is_dir():
            seen.setdefault(str(resolved).lower(), resolved)
    directories = list(seen.values())

    if not directories:
        raise FileNotFoundError("找不到可删除的目录。")

    for directory in directories:
        if not _is_inside(root, directory):
            raise ValueError("目录不在 option 根目录内：{}".format(directory))
        if directory == root or _is_deleted_path(root, directory):
            raise ValueError("不允许移动该目录：{}".format(directory))

    deleted_root = root / DELETED_DIR
    deleted_root.mkdir(parents=True, exist_ok=True)

    # 归档目录名只精确到秒。同一秒删掉两个同类型同名的条目会撞名，撞了就加序号，
    # 否则 shutil.move 会把第二个塞进第一个里面去。
    base = "{}_{}_{}_{}".format(
        datetime.now().strftime("%Y%m%d_%H%M%S"), kind, item_id, _safe_file_name(name))
    archive = deleted_root / base
    suffix = 2
    while archive.exists():
        archive = deleted_root / "{}_{}".format(base, suffix)
        suffix += 1
    archive.mkdir(parents=True)

    for directory in directories:
        destination = archive / os.path.relpath(directory, root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(directory), str(destination))

    return str(archive)


def _same_package(root: Path, first: Any, second: Any) -> bool:
    """两个文件在不在同一个包里 / Are both files in the same package?"""
    if not first or not second:
        return False
    return _package_name(root, Path(first)).lower() == _package_name(root, Path(second)).lower()


def delete_music(option_root: Any, music: MusicItem) -> str:
    """
    软删除一首歌 / Move a song into the recycle area.

    返回 / Returns:
        str: 归档目录。
    """
    directory = Path(music.xml_path).parent
    if not directory.is_dir():
        raise FileNotFoundError("找不到歌曲目录：{}".format(music.xml_path))
    return _move_to_deleted(option_root, "song", music.song_id, music.title, [directory])


def delete_character(option_root: Any, character: CharacterItem) -> str:
    """
    软删除一个角色 / Move a character into the recycle area.

    连带移走它的 ``DDSImage`` 目录，**但只在同一个包里时才连带**：跨包借用的
    贴图目录可能被别的角色共用，一起删就误伤了。

    返回 / Returns:
        str: 归档目录。
    """
    root = Path(option_root).resolve()
    directories: List[Path] = []

    chara_directory = Path(character.xml_path).parent
    if chara_directory.is_dir():
        directories.append(chara_directory)

    if character.dds_xml_path and _same_package(root, character.xml_path, character.dds_xml_path):
        directories.append(Path(character.dds_xml_path).parent)

    return _move_to_deleted(option_root, "character", character.character_id, character.name, directories)


# ---------------------------------------------------------------------------
# 作品库 / The works library
# ---------------------------------------------------------------------------

def list_works(option_root: Any) -> List[WorksItem]:
    """
    列出 option 里所有作品 / Every CharaWorks.xml in the tree.

    返回 / Returns:
        List[WorksItem]: 按 ID、再按包名排序。坏掉的 XML 跳过。
    """
    root = Path(option_root).resolve()
    items: List[WorksItem] = []
    for path in xmlio.iter_xml_files(root, "CharaWorks.xml"):
        try:
            node = xmlio.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        if node is None:
            continue
        items.append(WorksItem(
            works_id=xmlio.int_of(node.find("name"), "id"),
            name=xmlio.text(node, "name", "str"),
            sort_name=xmlio.text(node, "sortName"),
            priority=xmlio.int_of(node, "priority"),
            package=_package_name(root, path),
            xml_path=str(path),
            relative_path=_relative(root, path),
        ))
    items.sort(key=lambda works: (works.works_id, works.package.casefold()))
    return items


def list_packages(option_root: Any) -> List[str]:
    """
    列出可以写入的包目录 / Top-level packages a works entry can go into.

    跳过回收区和点开头的目录；模板包 ``AZUR`` 排在最前面，它是新增角色的默认落点。
    """
    root = Path(option_root).resolve()
    if not root.is_dir():
        return []
    names = [
        entry.name for entry in root.iterdir()
        if entry.is_dir() and not entry.name.startswith(".") and entry.name.lower() != DELETED_DIR
    ]
    names.sort(key=lambda name: (name.upper() != TEMPLATE_PACKAGE, name.casefold()))
    return names


def _resolve_template_works(root: Path, works_root: Path) -> Path:
    """
    找一份 CharaWorks.xml 当模板 / Find a CharaWorks.xml to clone.

    优先目标包自己的，再退到 AZUR 的乳蛙作品，最后退到 option 里任意一份。
    """
    if works_root.is_dir():
        local = sorted(works_root.rglob("CharaWorks.xml"))
        if local:
            return local[0]

    azur = (root / TEMPLATE_PACKAGE / "charaWorks"
            / "charaWorks{:06d}".format(DEFAULT_AZUR_WORKS_ID) / "CharaWorks.xml")
    if azur.is_file():
        return azur

    for path in xmlio.iter_xml_files(root, "CharaWorks.xml"):
        return path
    raise FileNotFoundError("option 内没有可用的 CharaWorks.xml 模板。")


def add_works(option_root: Any, package: str, works_id: int, name: str, sort_name: str) -> WorksItem:
    """
    新建一个作品 / Create a works entry.

    参数 / Parameters:
        option_root (Any): option 根目录。
        package (str): 写进哪个包（任意顶层目录，不限于 AZUR）。
        works_id (int): 作品 ID，正整数且不能和现有的撞。
        name (str): 作品显示名。
        sort_name (str): 排序名，留空就用显示名。

    返回 / Returns:
        WorksItem: 新建好的作品。

    异常 / Raises:
        ValueError: ID 不合法、名字为空、没选包、ID 已存在或目录已存在。
        FileNotFoundError: 包目录不存在，或找不到模板。
    """
    if works_id <= 0:
        raise ValueError("作品 ID 必须是正整数。")
    if not name.strip():
        raise ValueError("作品名不能为空。")
    if not package.strip():
        raise ValueError("请选择写入的包目录。")

    root = Path(option_root).resolve()
    package_root = root / package
    if not package_root.is_dir():
        raise FileNotFoundError("找不到包目录：{}".format(package_root))

    if any(item.works_id == works_id for item in list_works(root)):
        raise ValueError("作品 ID {} 已存在，请换一个。".format(works_id))

    works_root = package_root / "charaWorks"
    data_name = "charaWorks{:06d}".format(works_id)
    directory = works_root / data_name
    if directory.exists():
        raise ValueError("目录已存在：{}".format(directory))

    effective_sort = sort_name.strip() or name.strip()
    template = _resolve_template_works(root, works_root)
    decls = xmlio.namespace_decls(template)
    document = xmlio.parse(template)
    node = document.getroot()
    if node is None:
        raise ValueError("模板 CharaWorks.xml 无根节点。")

    xmlio.set_text(node, "dataName", data_name)
    xmlio.set_text(node, "name", "id", str(works_id))
    xmlio.set_text(node, "name", "str", name.strip())
    xmlio.set_text(node, "sortName", effective_sort)
    xmlio.set_text(node, "priority", str(DEFAULT_CUSTOM_PRIORITY))

    directory.mkdir(parents=True)
    xml_path = directory / "CharaWorks.xml"
    xmlio.save_xml(document, xml_path, decls)
    add_works_to_sort_first(works_root / "WorksSort.xml", works_id)

    return WorksItem(
        works_id=works_id,
        name=name.strip(),
        sort_name=effective_sort,
        priority=DEFAULT_CUSTOM_PRIORITY,
        package=package,
        xml_path=str(xml_path),
        relative_path=_relative(root, xml_path),
    )


def update_works(works: WorksItem) -> None:
    """
    改一个作品的名字和 priority / Rename a works entry.

    异常 / Raises:
        FileNotFoundError: ``CharaWorks.xml`` 不在了。
        ValueError: 文件没有根节点。
    """
    path = Path(works.xml_path)
    if not path.is_file():
        raise FileNotFoundError("找不到作品 CharaWorks.xml：{}".format(works.xml_path))

    decls = xmlio.namespace_decls(path)
    document = xmlio.parse(path)
    node = document.getroot()
    if node is None:
        raise ValueError("CharaWorks.xml 无根节点。")

    xmlio.set_text(node, "name", "str", works.name.strip())
    xmlio.set_text(node, "sortName", works.sort_name.strip() or works.name.strip())
    xmlio.set_text(node, "priority", str(works.priority))

    xmlio.ensure_backup(path)
    xmlio.save_xml(document, path, decls)


def delete_works(option_root: Any, works: WorksItem) -> str:
    """
    软删除一个作品，**连带删掉属于它的角色** / Delete a works entry and its characters.

    这是整个应用里破坏性最强的一步：作品目录、以及每一个 ``works id`` 等于它的
    角色的 Chara 目录（和同包的 DDSImage 目录）一起进回收区。

    ``works_id <= 0`` 时**不做连带**：0 表示「无作品 / 解析失败」，放任 cascade
    会把所有没填 works 的角色一起卷走。

    返回 / Returns:
        str: 归档目录。
    """
    directory = Path(works.xml_path).parent
    if not directory.is_dir():
        raise FileNotFoundError("找不到作品目录：{}".format(works.xml_path))

    root = Path(option_root).resolve()
    remove_works_from_sort(directory.parent / "WorksSort.xml", works.works_id)

    directories: List[Path] = [directory]
    if works.works_id > 0:
        found = _walk(root, ("Chara.xml", "DDSImage.xml"))
        dds_index = _build_dds_index(root, found["DDSImage.xml"])
        for path in found["Chara.xml"]:
            character = _parse_character(root, path, dds_index)
            if character is None or character.works_id != works.works_id:
                continue
            directories.append(Path(character.xml_path).parent)
            if character.dds_xml_path and _same_package(root, character.xml_path, character.dds_xml_path):
                directories.append(Path(character.dds_xml_path).parent)

    return _move_to_deleted(option_root, "works", works.works_id, works.name, directories)


def add_works_to_sort_first(sort_path: Any, works_id: int) -> None:
    """
    把作品插到 WorksSort.xml 的最前面 / Put a works id first in the sort list.

    文件不存在就新建一份（带上游戏期望的 xsd/xsi 命名空间声明）。已经在表里的
    先摘掉再插到最前，避免出现两条同 ID。
    """
    path = Path(sort_path)
    decls: List[Tuple[str, str]]
    if path.is_file():
        decls = xmlio.namespace_decls(path)
        document = xmlio.parse(path)
    else:
        decls = [
            ("xsd", "http://www.w3.org/2001/XMLSchema"),
            ("xsi", "http://www.w3.org/2001/XMLSchema-instance"),
        ]
        root = ET.Element("SerializeSortData")
        ET.SubElement(root, "dataName").text = "charaWorks"
        ET.SubElement(root, "SortList")
        document = ET.ElementTree(root)
        path.parent.mkdir(parents=True, exist_ok=True)

    node = document.getroot()
    sort_list = node.find("SortList")
    if sort_list is None:
        sort_list = ET.SubElement(node, "SortList")

    for duplicate in [item for item in sort_list.findall("StringID")
                      if xmlio.int_of(item, "id") == works_id]:
        sort_list.remove(duplicate)

    entry = ET.Element("StringID")
    ET.SubElement(entry, "id").text = str(works_id)
    ET.SubElement(entry, "str")
    ET.SubElement(entry, "data")
    sort_list.insert(0, entry)

    xmlio.save_xml(document, path, decls)


def remove_works_from_sort(sort_path: Any, works_id: int) -> None:
    """把作品从 WorksSort.xml 里摘掉 / Drop a works id from the sort list."""
    path = Path(sort_path)
    if not path.is_file():
        return

    decls = xmlio.namespace_decls(path)
    try:
        document = xmlio.parse(path)
    except (ET.ParseError, OSError):
        return

    sort_list = document.getroot().find("SortList")
    if sort_list is None:
        return

    removed = [item for item in sort_list.findall("StringID") if xmlio.int_of(item, "id") == works_id]
    if not removed:
        return
    for item in removed:
        sort_list.remove(item)
    xmlio.save_xml(document, path, decls)


def _ensure_works_priority(works_root: Path, works_id: int) -> bool:
    """
    把某个作品的 priority 抬到 999 / Bump one works entry to the top.

    返回 / Returns:
        bool: 在这个包里找到并改了才是 ``True``。
    """
    if not works_root.is_dir():
        return False

    for path in sorted(works_root.rglob("CharaWorks.xml")):
        try:
            document = xmlio.parse(path)
        except (ET.ParseError, OSError):
            continue
        node = document.getroot()
        if node is None or xmlio.int_of(node.find("name"), "id") != works_id:
            continue
        xmlio.set_text(node, "priority", str(DEFAULT_CUSTOM_PRIORITY))
        xmlio.save_xml(document, path, xmlio.namespace_decls(path))
        return True
    return False


# ---------------------------------------------------------------------------
# 新增角色 / Creating characters
# ---------------------------------------------------------------------------

def collect_character_ids(option_root: Any) -> set:
    """
    option 里所有角色 ID / Every character id in the tree, recycle area included.

    **回收区也要算进来**：软删除的角色随时可能被恢复，重用它的 ID 会撞号。
    """
    root = Path(option_root).resolve()
    ids = set()
    for path in xmlio.iter_xml_files(root, "Chara.xml", skip_deleted=False):
        try:
            node = xmlio.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        value = xmlio.int_of(node.find("name") if node is not None else None, "id")
        if value > 0:
            ids.add(value)
    return ids


def next_custom_character_id(option_root: Any, chara_root: Path) -> int:
    """
    下一个空闲的自定义角色 ID / The next free custom character id.

    从整棵树的最大 ID 往上取，而不是只看模板包：别的包里的自定义角色同样会撞号。
    """
    ids = collect_character_ids(option_root)
    candidate = max(max(ids) + 1 if ids else 0, MIN_CUSTOM_CHARACTER_ID)
    while (chara_root / "chara{}".format(candidate)).exists():
        candidate += 1
    return candidate


def validate_character_id(option_root: Any, chara_root: Path, character_id: int) -> int:
    """
    校验显式指定的角色 ID / Check a user-supplied character id.

    异常 / Raises:
        ValueError: 不是正整数、目录已存在、或 ID 已被占用（含回收区）。
    """
    if character_id <= 0:
        raise ValueError("角色 ID 必须是正整数。")
    if (chara_root / "chara{}".format(character_id)).exists():
        raise ValueError("{} 下已存在 chara{} 目录，请换一个 ID。".format(
            TEMPLATE_PACKAGE, character_id))
    if character_id in collect_character_ids(option_root):
        raise ValueError("角色 ID {} 已被占用（option 内或 _deleted 中已存在），请换一个。".format(
            character_id))
    return character_id


def compose_character_id(base_text: str, skin_text: str) -> Optional[int]:
    """
    基 ID + 皮肤 ID 组成最终角色 ID / Compose the final id from base and skin.

    最终 ID = 基 ID × 10 + 皮肤 ID，皮肤是个位 0–9（0 即默认皮肤）。
    模板 ``chara114514`` 就是基 ``11451`` + 皮肤 ``4``。

    返回 / Returns:
        Optional[int]: 组不出来（基 ID 非正整数、皮肤不在 0–9）就是 ``None``。
    """
    try:
        base = int((base_text or "").strip())
    except ValueError:
        return None
    if base <= 0:
        return None

    raw_skin = (skin_text or "").strip() or "0"
    try:
        skin = int(raw_skin)
    except ValueError:
        return None
    if not 0 <= skin <= 9:
        return None
    return base * 10 + skin


def _resolve_template(directory: Path, preferred: str, filename: str) -> Path:
    """找模板文件 / Locate a template XML, preferring the known-good one."""
    candidate = directory / preferred / filename
    if candidate.is_file():
        return candidate
    found = sorted(directory.rglob(filename)) if directory.is_dir() else []
    if found:
        return found[0]
    raise FileNotFoundError("{} 下没有可用的 {} 模板。".format(TEMPLATE_PACKAGE, filename))


def add_character(option_root: Any, request: AddCharacterRequest) -> int:
    """
    新增一个角色 / Create a character from the AZUR templates.

    克隆 ``AZUR`` 包里的 ``chara114514`` / ``ddsImage114514``，写出新的
    ``Chara.xml`` 和 ``DDSImage.xml``，priority 设成 999。

    给了源图就顺带生成三张 DDS；**没给就不写任何 DDS**——套模板的贴图会让
    新角色顶着乳蛙的脸，那比没有立绘更让人困惑。

    参数 / Parameters:
        option_root (Any): option 根目录。
        request (AddCharacterRequest): 表单里填的东西。

    返回 / Returns:
        int: 新角色的 ID。

    异常 / Raises:
        ValueError: 角色名为空，或指定的 ID 不合法 / 已占用。
        FileNotFoundError: 找不到模板包或模板文件。
    """
    if not request.name.strip():
        raise ValueError("角色名不能为空。")

    root = Path(option_root).resolve()
    package_root = root / TEMPLATE_PACKAGE
    if not package_root.is_dir():
        raise FileNotFoundError("找不到模板包目录：{}".format(package_root))

    chara_root = package_root / "chara"
    dds_root = package_root / "ddsImage"
    works_root = package_root / "charaWorks"

    template_chara = _resolve_template(
        chara_root, "chara{}".format(TEMPLATE_CHARACTER_ID), "Chara.xml")
    template_dds = _resolve_template(
        dds_root, "ddsImage{}".format(TEMPLATE_CHARACTER_ID), "DDSImage.xml")

    new_id = (validate_character_id(root, chara_root, request.character_id)
              if request.character_id > 0
              else next_custom_character_id(root, chara_root))

    sort_name = request.sort_name.strip() or request.name.strip()
    image_key = "chara{}_00".format(new_id)
    add_image_key = "chara{}_01".format(new_id)

    new_chara_dir = chara_root / "chara{}".format(new_id)
    new_dds_dir = dds_root / "ddsImage{}".format(new_id)
    created = [path for path in (new_chara_dir, new_dds_dir) if not path.exists()]
    new_chara_dir.mkdir(parents=True, exist_ok=True)
    new_dds_dir.mkdir(parents=True, exist_ok=True)

    try:
        chara_decls = xmlio.namespace_decls(template_chara)
        chara_doc = xmlio.parse(template_chara)
        chara = chara_doc.getroot()
        if chara is None:
            raise ValueError("模板 Chara.xml 无根节点。")

        xmlio.set_text(chara, "dataName", "chara{}".format(new_id))
        xmlio.set_text(chara, "name", "id", str(new_id))
        xmlio.set_text(chara, "name", "str", request.name.strip())
        xmlio.set_text(chara, "sortName", sort_name)
        xmlio.set_text(chara, "defaultImages", "id", str(new_id))
        xmlio.set_text(chara, "defaultImages", "str", image_key)
        xmlio.set_text(chara, "addImages1", "charaName", "id", str(new_id + 100000))
        xmlio.set_text(chara, "addImages1", "charaName", "str", request.name.strip())
        xmlio.set_text(chara, "addImages1", "image", "id", str(new_id + 100000))
        xmlio.set_text(chara, "addImages1", "image", "str", add_image_key)
        xmlio.set_text(chara, "works", "id", str(request.works_id))
        xmlio.set_text(chara, "works", "str", request.works_name.strip())
        xmlio.set_text(chara, "priority", str(DEFAULT_CUSTOM_PRIORITY))
        if request.illustrator_name.strip():
            xmlio.set_text(chara, "illustratorName", "str", request.illustrator_name.strip())
        xmlio.save_xml(chara_doc, new_chara_dir / "Chara.xml", chara_decls)

        dds_decls = xmlio.namespace_decls(template_dds)
        dds_doc = xmlio.parse(template_dds)
        dds = dds_doc.getroot()
        if dds is None:
            raise ValueError("模板 DDSImage.xml 无根节点。")

        xmlio.set_text(dds, "dataName", "ddsImage{}".format(new_id))
        xmlio.set_text(dds, "name", "id", str(new_id))
        xmlio.set_text(dds, "name", "str", image_key)
        xmlio.set_text(dds, "ddsFile0", "path", "big.dds")
        xmlio.set_text(dds, "ddsFile1", "path", "small.dds")
        xmlio.set_text(dds, "ddsFile2", "path", "thumb.dds")
        xmlio.save_xml(dds_doc, new_dds_dir / "DDSImage.xml", dds_decls)

        if request.source_image_path:
            from core import dds as dds_writer
            dds_writer.generate_character_textures(
                request.source_image_path, new_dds_dir, request.crops)

        if request.works_id > 0 and _ensure_works_priority(works_root, request.works_id):
            add_works_to_sort_first(works_root / "WorksSort.xml", request.works_id)
    except Exception:
        # 半路失败（源图损坏、DDS 生成抛错）就把刚建的目录清掉。否则 option 树里
        # 会留下一个没有贴图的残缺角色，而这个 ID 从此被永久占用。
        for path in created:
            shutil.rmtree(path, ignore_errors=True)
        raise

    return new_id
