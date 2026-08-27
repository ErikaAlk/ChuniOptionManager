# -*- coding: utf-8 -*-
"""XML 读写的保真度 / How faithfully the XML layer writes files back."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core import xmlio


def test_a_round_trip_leaves_the_file_byte_identical(option_root: Path) -> None:
    """
    读进来再写出去，字节要一模一样 / Parse and write back, byte for byte.

    这是整个写入层的地基：保存一个字段不该顺带改动其余几十行的缩进、换行和
    XML 声明。有一个字节不一样，diff 就没法看了。
    """
    path = option_root / "AZUR" / "charaWorks" / "charaWorks011451" / "CharaWorks.xml"
    before = path.read_bytes()

    decls = xmlio.namespace_decls(path)
    xmlio.save_xml(xmlio.parse(path), path, decls)

    assert path.read_bytes() == before


def test_the_namespace_declarations_survive(option_root: Path) -> None:
    """
    根节点上那两行 xmlns 不能丢 / The unused xmlns declarations must survive.

    ``xmlns:xsd`` / ``xmlns:xsi`` 在这些文档里一次都没被用到，ElementTree
    默认只写它实际用到的命名空间——不显式补回去就会**静默消失**。
    这条测试盯的就是那个「静默」。
    """
    path = option_root / "AZUR" / "ddsImage" / "ddsImage114514" / "DDSImage.xml"

    decls = xmlio.namespace_decls(path)
    assert ("xsi", "http://www.w3.org/2001/XMLSchema-instance") in decls

    xmlio.save_xml(xmlio.parse(path), path, decls)
    text = path.read_text(encoding="utf-8")
    assert 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' in text
    assert 'xmlns:xsd="http://www.w3.org/2001/XMLSchema"' in text


def test_dropping_the_declarations_is_what_a_naive_write_does(option_root: Path) -> None:
    """
    不传 decls 就会掉 / Without the fix, the declarations do go missing.

    这条是上一条的对照组：证明那个 ``decls`` 参数确实在起作用，而不是
    ElementTree 本来就会保留。少了它，上一条测试就只是在测一个恒真的东西。
    """
    path = option_root / "AZUR" / "ddsImage" / "ddsImage114514" / "DDSImage.xml"
    xmlio.save_xml(xmlio.parse(path), path)
    assert "xmlns:xsi" not in path.read_text(encoding="utf-8")


def test_only_the_enable_bytes_change(option_root: Path) -> None:
    """
    改谱面开关时，除了 enable 一个字节都不动 / Byte-exact except the toggles.
    """
    path = option_root / "A001" / "music" / "music000001" / "Music.xml"
    before = path.read_bytes()

    assert xmlio.replace_enable_flags(path, [True, True, True, True, True, False])

    after = path.read_bytes()
    assert len(before.split(b"\r\n")) == len(after.split(b"\r\n"))
    changed = [(a, b) for a, b in zip(before.split(b"\r\n"), after.split(b"\r\n")) if a != b]
    assert changed == [(b"      <enable>false</enable>", b"      <enable>true</enable>")]


def test_a_mismatched_block_count_is_refused(option_root: Path) -> None:
    """
    块数对不上就认输 / A wrong number of states is refused, not guessed.

    字节级改写靠「第 N 个块对应第 N 个开关」这个假设。数量对不上说明假设已经
    不成立，这时候硬改就是在乱写别人的文件。
    """
    path = option_root / "A001" / "music" / "music000001" / "Music.xml"
    before = path.read_bytes()

    assert not xmlio.replace_enable_flags(path, [True, True])
    assert path.read_bytes() == before


def test_a_self_closing_enable_is_recognised(tmp_path: Path) -> None:
    """
    自闭合的 ``<enable />`` 也要认 / The self-closing form counts too.

    把它当成「没有这个节点」会让整份文件退回重排缩进那条路，白白产生一堆差异。
    """
    path = tmp_path / "Music.xml"
    path.write_bytes(b"<MusicData><fumens><MusicFumenData><enable /></MusicFumenData>"
                     b"</fumens></MusicData>")
    assert xmlio.replace_enable_flags(path, [True])
    assert b"<enable>true</enable>" in path.read_bytes()


def test_set_text_creates_the_nodes_it_needs(tmp_path: Path) -> None:
    """路径上缺的节点要顺手补出来 / Missing nodes are created on the way down."""
    root = ET.Element("CharaData")
    xmlio.set_text(root, "works", "str", "アズールレーン")
    assert xmlio.text(root, "works", "str") == "アズールレーン"


def test_set_text_needs_a_name_and_a_value() -> None:
    """参数不够就抛 / Too few arguments is a programming error, not a no-op."""
    with pytest.raises(ValueError):
        xmlio.set_text(ET.Element("x"), "only-one")


def test_the_backup_is_made_once_and_only_once(option_root: Path) -> None:
    """
    .bak 只留第一次那份 / The backup captures the original, not the last save.

    每次保存都覆盖备份的话，改错了再存一次就把好的那份也盖没了。
    """
    path = option_root / "A001" / "music" / "music000001" / "Music.xml"
    original = path.read_bytes()

    xmlio.ensure_backup(path)
    path.write_bytes(b"<MusicData />")
    xmlio.ensure_backup(path)

    assert path.with_name("Music.xml.bak").read_bytes() == original


def test_dot_directories_are_skipped(option_root: Path) -> None:
    """
    点开头的目录不进扫描 / Dot directories are pruned.

    option 根目录里放过 ``.git`` / ``.vs`` / ``.venv`` 的人会踩到：那里面
    可能有别的 XML，而且遍历它们纯属浪费。
    """
    hidden = option_root / ".vs" / "music" / "music000099"
    hidden.mkdir(parents=True)
    (hidden / "Music.xml").write_bytes(b"<MusicData />")

    found = list(xmlio.iter_xml_files(option_root, "Music.xml"))
    assert all(".vs" not in str(path) for path in found)
