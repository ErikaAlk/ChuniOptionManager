# -*- coding: utf-8 -*-
"""
测试用的假 option 树 / A fake option tree for the tests.

**测试一律不碰真实的游戏目录。** 真目录是用户的数据，跑一次测试就动一次是不能
接受的；而且它的内容随时在变，靠它做断言的测试今天绿明天红，没有意义。
这里在临时目录里造一棵结构一模一样的小树。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 界面测试要在没有显示器的环境里跑（CI、打包脚本），所以先把平台钉成 offscreen
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: 一份最小的 Music.xml。缩进和 CRLF 都按游戏发出来的样子写，
#: 字节级写回的测试要靠它们才有意义。
MUSIC_TEMPLATE = """<?xml version='1.0' encoding='utf-8'?>
<MusicData>
  <dataName>{data_name}</dataName>
  <disableFlag>false</disableFlag>
  <name>
    <id>{song_id}</id>
    <str>{title}</str>
    <data />
  </name>
  <sortName>{sort_name}</sortName>
  <artistName>
    <id>1</id>
    <str>{artist}</str>
    <data />
  </artistName>
  <genreNames>
    <list>
      <StringID>
        <id>5</id>
        <str>ORIGINAL</str>
        <data />
      </StringID>
    </list>
  </genreNames>
  <worksName>
    <id>-1</id>
    <str>Invalid</str>
    <data />
  </worksName>
  <jaketFile>
    <path>CHU_UI_Jacket_{song_id:04d}.dds</path>
  </jaketFile>
  <enableUltima>false</enableUltima>
  <fumens>
{fumens}  </fumens>
</MusicData>"""

FUMEN_TEMPLATE = """    <MusicFumenData>
      <type>
        <id>{type_id}</id>
        <str>{type_str}</str>
        <data>{type_data}</data>
      </type>
      <enable>{enable}</enable>
      <file>
        <path>{file_name}</path>
      </file>
      <level>{level}</level>
      <levelDecimal>{level_decimal}</levelDecimal>
      <notesDesigner />
    </MusicFumenData>
"""

CHARA_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<CharaData>
  <dataName>chara{chara_id}</dataName>
  <releaseTagName>
    <id>70</id>
    <str>v2 2.10.00</str>
    <data />
  </releaseTagName>
  <netOpenName>
    <id>22300</id>
    <str>v2_10 20_1</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <name>
    <id>{chara_id}</id>
    <str>{name}</str>
    <data />
  </name>
  <explainText />
  <sortName>{name}</sortName>
  <works>
    <id>{works_id}</id>
    <str>{works_name}</str>
    <data />
  </works>
  <illustratorName>
    <id>50</id>
    <str />
    <data />
  </illustratorName>
  <defaultHave>true</defaultHave>
  <rareType>0</rareType>
  <defaultImages>
    <id>{chara_id}</id>
    <str>chara{chara_id}_00</str>
    <data />
  </defaultImages>
  <addImages1>
    <changeImg>true</changeImg>
    <charaName>
      <id>1</id>
      <str>x</str>
      <data />
    </charaName>
    <image>
      <id>1</id>
      <str>x</str>
      <data />
    </image>
    <rank>15</rank>
  </addImages1>
  <priority>0</priority>
</CharaData>"""

DDS_XML_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<DDSImageData xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <dataName>ddsImage{chara_id}</dataName>
  <name>
    <id>{chara_id}</id>
    <str>chara{chara_id}_00</str>
    <data />
  </name>
  <ddsFile0>
    <path>big.dds</path>
  </ddsFile0>
  <ddsFile1>
    <path>small.dds</path>
  </ddsFile1>
  <ddsFile2>
    <path>thumb.dds</path>
  </ddsFile2>
</DDSImageData>"""

WORKS_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<CharaWorksData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>charaWorks{works_id:06d}</dataName>
  <name>
    <id>{works_id}</id>
    <str>{name}</str>
    <data />
  </name>
  <sortName>{name}</sortName>
  <priority>{priority}</priority>
  <ranks />
</CharaWorksData>"""

#: 六个难度的默认组合：BASIC~MASTER 开着，ULTIMA / WORLD'S END 关着。
DEFAULT_FUMENS = (
    (0, "Basic", "BASIC", True, 5, 0),
    (1, "Advanced", "ADVANCED", True, 8, 0),
    (2, "Expert", "EXPERT", True, 12, 50),
    (3, "Master", "MASTER", True, 14, 0),
    (4, "Ultima", "ULTIMA", False, 0, 0),
    (5, "WorldsEnd", "WORLD'S END", False, 0, 0),
)


def _write(path: Path, text: str) -> None:
    """按游戏的样子落盘：UTF-8 无 BOM、CRLF、结尾不留换行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))


def write_song(root: Path, package: str, song_id: int, title: str,
               fumens=DEFAULT_FUMENS, make_files: bool = True) -> Path:
    """
    往假树里写一首歌 / Add one song to the fake tree.

    参数 / Parameters:
        make_files (bool): 是否顺便创建 ``.c2s``。传 ``False`` 就能造出
            「开着但文件不在」这种排查项。

    返回 / Returns:
        Path: 这首歌的 ``Music.xml``。
    """
    directory = root / package / "music" / "music{:06d}".format(song_id)
    blocks = []
    for type_id, type_str, type_data, enable, level, level_decimal in fumens:
        file_name = "{:04d}_{:02d}.c2s".format(song_id, type_id)
        blocks.append(FUMEN_TEMPLATE.format(
            type_id=type_id, type_str=type_str, type_data=type_data,
            enable="true" if enable else "false", file_name=file_name,
            level=level, level_decimal=level_decimal))
        if make_files and enable:
            _write(directory / file_name, "dummy chart")

    xml_path = directory / "Music.xml"
    _write(xml_path, MUSIC_TEMPLATE.format(
        data_name="music{:06d}".format(song_id), song_id=song_id, title=title,
        sort_name=title.upper(), artist="ARTIST", fumens="".join(blocks)))
    return xml_path


def write_character(root: Path, package: str, chara_id: int, name: str,
                    works_id: int = 11451, works_name: str = "アズールレーン",
                    with_textures: bool = True) -> Path:
    """
    往假树里写一个角色 / Add one character, with or without its textures.

    返回 / Returns:
        Path: 这个角色的 ``Chara.xml``。
    """
    chara_path = root / package / "chara" / "chara{}".format(chara_id) / "Chara.xml"
    _write(chara_path, CHARA_TEMPLATE.format(
        chara_id=chara_id, name=name, works_id=works_id, works_name=works_name))

    dds_dir = root / package / "ddsImage" / "ddsImage{}".format(chara_id)
    _write(dds_dir / "DDSImage.xml", DDS_XML_TEMPLATE.format(chara_id=chara_id))
    if with_textures:
        for file_name in ("big.dds", "small.dds", "thumb.dds"):
            (dds_dir / file_name).write_bytes(b"DDS " + b"\x00" * 124)
    return chara_path


def write_works(root: Path, package: str, works_id: int, name: str, priority: int = 0) -> Path:
    """往假树里写一个作品 / Add one works entry."""
    path = (root / package / "charaWorks" / "charaWorks{:06d}".format(works_id)
            / "CharaWorks.xml")
    _write(path, WORKS_TEMPLATE.format(works_id=works_id, name=name, priority=priority))
    return path


@pytest.fixture
def option_root(tmp_path: Path) -> Path:
    """
    一棵能过 :func:`core.paths.looks_like_option_root` 的假树 / A usable fake tree.

    内容刻意造得有代表性：两个包、一首缺谱面文件的歌、一首同 ID 但难度更少的
    重复歌、一个没有贴图的角色、一个模板角色和一个模板作品。
    """
    root = tmp_path / "option"

    write_song(root, "A001", 1, "Song One")
    write_song(root, "A001", 2, "Song Two", make_files=False)
    write_song(root, "A300", 3, "Song Three")
    # 同 ID 的重复项，只带 BASIC——用来触发「重复项少难度」
    write_song(root, "A300", 1, "Song One", fumens=DEFAULT_FUMENS[:1])

    write_character(root, "AZUR", 114514, "乳蛙")
    write_character(root, "A001", 20540, "无图角色", works_id=0, works_name="Invalid",
                    with_textures=False)
    write_works(root, "AZUR", 11451, "アズールレーン", priority=0)
    return root
