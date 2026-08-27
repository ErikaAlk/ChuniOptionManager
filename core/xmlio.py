# -*- coding: utf-8 -*-
"""
option 里那些 XML 的读写 / Reading and writing the option XML files.

**这里有两套写法，是故意的**：

* :func:`save_xml` 重排缩进后整份写出（UTF-8 无 BOM、CRLF、两个空格），
  角色、作品、模板都走它；
* :func:`replace_enable_flags` 只把 ``<enable>`` 那几个字节换掉，
  文件其余部分一个字节都不动——谱面开关走它。

分开的理由：谱面开关是最高频的编辑，而 ``Music.xml`` 是游戏自己发出来的文件，
每次保存都重排一遍缩进，会让 diff 和「到底改了什么」彻底没法看。

改哪个文件就用哪套写法，别混。
"""

from __future__ import annotations

import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

#: 写出去的 XML 声明。和 option 里现成的文件保持一致（双引号、utf-8 小写）。
XML_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>'

#: 软删除的回收区目录名。放在这里而不是 core.paths，是为了让本模块不反向依赖它。
DELETED_DIR = "_deleted"


def parse(path: Any) -> ET.ElementTree:
    """读一份 XML / Parse an XML file."""
    return ET.parse(str(path))


def text(element: Optional[ET.Element], *names: str) -> str:
    """
    顺着标签名往下取文本 / Walk down by tag name and return the text.

    参数 / Parameters:
        element (Optional[ET.Element]): 起点，``None`` 直接返回空串。
        *names (str): 一层层的标签名，如 ``("name", "str")``。

    返回 / Returns:
        str: 去掉首尾空白的文本；路径上任何一层缺失都返回空串。
    """
    current = element
    for name in names:
        if current is None:
            return ""
        current = current.find(name)
    if current is None or current.text is None:
        return ""
    return current.text.strip()


def int_of(element: Optional[ET.Element], *names: str) -> int:
    """取整数 / Read an int；读不出来算 0（和老版本一致，0 表示「没有 / 无效」）。"""
    try:
        return int(text(element, *names))
    except ValueError:
        return 0


def bool_of(element: Optional[ET.Element], *names: str) -> bool:
    """取布尔 / Read a bool；只有字面量 ``true`` 算真。"""
    return text(element, *names).lower() == "true"


def bool_text(value: bool) -> str:
    """布尔写回 XML 的字面量 / The literal the game expects."""
    return "true" if value else "false"


def set_text(root: ET.Element, *path_and_value: str) -> None:
    """
    按路径写文本，路径上缺的节点顺手补出来 / Set text, creating missing nodes.

    参数 / Parameters:
        root (ET.Element): 起点。
        *path_and_value (str): 最后一个是值，前面全是标签名。

    异常 / Raises:
        ValueError: 少于两个参数（没有标签名或没有值）。
    """
    if len(path_and_value) < 2:
        raise ValueError("set_text 至少要一个标签名和一个值。")

    value = path_and_value[-1]
    current = root
    for name in path_and_value[:-1]:
        child = current.find(name)
        if child is None:
            child = ET.SubElement(current, name)
        current = child
    current.text = value


def namespace_decls(path: Any) -> List[Tuple[str, str]]:
    """
    读出根节点上的 xmlns 声明 / The root's namespace declarations.

    ``DDSImage.xml`` / ``CharaWorks.xml`` / ``WorksSort.xml`` 的根节点上挂着
    ``xmlns:xsd`` 和 ``xmlns:xsi``，但文档里**一次都没用到**这两个前缀。
    ElementTree 只写它实际用到的命名空间，于是原样读进来再写出去，这两行
    声明会**静默消失**——游戏那边认不认，赌不起。写回时靠 :func:`save_xml`
    的 ``decls`` 参数把它们原样补回去。

    参数 / Parameters:
        path (Any): XML 文件。

    返回 / Returns:
        List[Tuple[str, str]]: ``[(前缀, URI)]``，按源文件里的先后顺序；
        默认命名空间的前缀是空串。
    """
    decls: List[Tuple[str, str]] = []
    parser = ET.XMLPullParser(events=("start-ns", "start"))
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(8192)
                if not chunk:
                    break
                parser.feed(chunk)
                reached_root = False
                for event, payload in parser.read_events():
                    if event == "start-ns":
                        decls.append((payload[0], payload[1]))
                    else:
                        reached_root = True
                        break
                if reached_root:
                    break
    except (OSError, ET.ParseError):
        return []
    return decls


def ensure_backup(path: Any) -> None:
    """
    第一次保存时留一份 .bak / Back up once, on the first save.

    只复制一次是有意的：每次保存都覆盖备份的话，改错了第二次保存就把好的
    那份也盖没了，备份反而成了摆设。
    """
    target = Path(path)
    backup = target.with_name(target.name + ".bak")
    if target.is_file() and not backup.exists():
        shutil.copy2(target, backup)


def write_bytes_atomic(path: Any, data: bytes) -> None:
    """
    先写临时文件再改名 / Write to a temp file, then rename into place.

    直接覆写的话，中途出错会留下一个半截文件——而这是游戏要读的数据。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    with open(temp, "wb") as handle:
        handle.write(data)
    os.replace(temp, target)


def serialize(
    tree: ET.ElementTree,
    decls: Sequence[Tuple[str, str]] = (),
    reindent: bool = True,
) -> bytes:
    """
    整份序列化成字节 / Render the tree to bytes: CRLF, UTF-8, no BOM.

    参数 / Parameters:
        tree (ET.ElementTree): 要写的树。
        decls (Sequence[Tuple[str, str]]): 要补回根节点的命名空间声明，
            见 :func:`namespace_decls`。
        reindent (bool): ``True`` 重排成两个空格的缩进；``False`` 原样保留源文件
            的空白（ElementTree 把它们存在 text/tail 里，不动就还在）。

    返回 / Returns:
        bytes: 可以直接落盘的内容。
    """
    root = tree.getroot()
    for prefix, uri in decls:
        # 写成字面属性名，ElementTree 会原样输出——这是让声明活下来的唯一办法
        root.set("xmlns:" + prefix if prefix else "xmlns", uri)

    if reindent:
        ET.indent(tree, space="  ")
    body = ET.tostring(root, encoding="unicode").rstrip()
    # 结尾**不留换行**：游戏自己发出来的 XML 就是以 `</Root>` 收尾的，
    # 多一个 CRLF 会让每份文件第一次保存后都产生一处无意义的差异。
    document = XML_DECLARATION + "\n" + body
    return document.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def save_xml(
    tree: ET.ElementTree,
    path: Any,
    decls: Sequence[Tuple[str, str]] = (),
    reindent: bool = True,
) -> None:
    """整份写出 / Write the whole document, re-indented unless told otherwise."""
    write_bytes_atomic(path, serialize(tree, decls, reindent))


#: 一段 MusicFumenData。谱面块不嵌套，非贪婪匹配就够了。
_FUMEN_BLOCK = re.compile(rb"<MusicFumenData>.*?</MusicFumenData>", re.DOTALL)
#: 块里的 enable 节点。自闭合写法也要认，否则会被当成「没有这个节点」。
_ENABLE_TAG = re.compile(rb"<enable\s*/>|<enable>.*?</enable>", re.DOTALL)


def replace_enable_flags(path: Any, states: Sequence[bool]) -> bool:
    """
    只改 enable，别的字节一个不动 / Flip the enable flags, byte-exact elsewhere.

    参数 / Parameters:
        path (Any): ``Music.xml``。
        states (Sequence[bool]): 每个谱面块的新状态，顺序即文件里的顺序。

    返回 / Returns:
        bool: 改成了就是 ``True``；块数对不上、或有块里根本没有 ``<enable>``
        就返回 ``False``，由调用方退回到整份重写那条路。

    这条路径不解析 XML，因此注释、属性引号、原有缩进、甚至 XML 声明的引号
    风格全部原样保留。代价是它对格式有假设，所以对不上就老老实实认输。
    """
    data = Path(path).read_bytes()
    blocks = list(_FUMEN_BLOCK.finditer(data))
    if len(blocks) != len(states):
        return False

    pieces: List[bytes] = []
    cursor = 0
    for block, enabled in zip(blocks, states):
        chunk = data[block.start():block.end()]
        replacement = b"<enable>true</enable>" if enabled else b"<enable>false</enable>"
        patched, count = _ENABLE_TAG.subn(replacement, chunk, count=1)
        if count != 1:
            return False
        pieces.append(data[cursor:block.start()])
        pieces.append(patched)
        cursor = block.end()
    pieces.append(data[cursor:])

    write_bytes_atomic(path, b"".join(pieces))
    return True


def iter_xml_files(root: Any, filename: str, skip_deleted: bool = True) -> Iterable[Path]:
    """
    在 option 树里找同名文件 / Walk the option tree for files with this name.

    跳过一切点开头的目录（``.git`` / ``.venv`` 这类；option 根目录里塞过工具
    目录的人会感谢这一条），默认也跳过回收区。

    参数 / Parameters:
        root (Any): option 根目录。
        filename (str): 要找的文件名，如 ``Music.xml``。
        skip_deleted (bool): 是否跳过回收区。给「分配新 ID」用时要传 ``False``：
            软删除掉的 ID 不能被重新发出去，否则恢复回来就撞号了。

    产出 / Yields:
        Path: 命中的文件。
    """
    for current, dirs, files in os.walk(Path(root)):
        kept = [name for name in dirs if not name.startswith(".")]
        if skip_deleted:
            kept = [name for name in kept if name.lower() != DELETED_DIR]
        dirs[:] = kept
        if filename in files:
            yield Path(current) / filename
