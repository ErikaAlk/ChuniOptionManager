# -*- coding: utf-8 -*-
"""
DDS 预览缓存 / Decoding DDS for on-screen preview.

Qt 不认 ``.dds``，所以每张贴图先解码成 PNG 落到临时目录，界面再去读那个 PNG。
缓存键是「路径 + 目标边长 + 文件大小 + 修改时间」——换了图、换了尺寸都会自然
失效，不需要手动清缓存。

**歌曲卡面的曲绘也走这里。** option 里 730 张曲绘全是 ``.dds``，老版本（WinUI）
直接把 ``.dds`` 喂给 ``BitmapImage``，于是每一张卡都显示 NO IMAGE——那不是没有
图，是根本没解码。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from PIL import Image

#: 缓存目录。放系统临时目录，清掉不影响任何数据。
CACHE_ROOT = Path(tempfile.gettempdir()) / "ChuniOptionManager" / "dds-preview"


def _cache_key(path: Path, max_size: Optional[int]) -> str:
    """
    缓存键 / The cache key for one texture at one size.

    带上大小和修改时间：贴图被替换之后，路径不变但内容变了，只按路径做键会
    永远命中那张旧图。
    """
    try:
        stat = path.stat()
        stamp = "{}|{}|{}".format(path, stat.st_size, stat.st_mtime_ns)
    except OSError:
        stamp = str(path)
    digest = hashlib.sha256(stamp.encode("utf-8")).hexdigest()
    return "{}-{}".format(digest, max_size or 0)


def preview_path(path: Any, max_size: Optional[int] = None) -> Optional[str]:
    """
    拿到一张可以直接给 Qt 读的 PNG / Get a PNG Qt can actually load.

    参数 / Parameters:
        path (Any): ``.dds`` 文件。非 DDS 的图片原样返回路径（不必多此一举）。
        max_size (Optional[int]): 长边上限；``None`` 表示原尺寸。卡片列表传
            256 就够，省下来的是几百张 1080 图的解码时间和内存。

    返回 / Returns:
        Optional[str]: PNG 路径；文件不在或解不开就是 ``None``。
    """
    if not path:
        return None
    source = Path(path)
    if not source.is_file():
        return None
    if source.suffix.lower() != ".dds":
        return str(source)

    try:
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        target = CACHE_ROOT / (_cache_key(source, max_size) + ".png")
        if target.is_file():
            return str(target)

        # 先解码到唯一的临时文件再改名。中途被杀 / 磁盘满 / 两个线程同时解同一张，
        # 都只会留下临时文件；否则缓存里会留下一个截断的 PNG，而缓存键不变，
        # 这张坏图会被之后每一次运行永久命中。
        temp = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
            if max_size and max(image.width, image.height) > max_size:
                image.thumbnail((max_size, max_size), Image.LANCZOS)
            image.save(temp, format="PNG")

        try:
            os.replace(temp, target)
        except OSError:
            temp.unlink(missing_ok=True)
        return str(target)
    except (OSError, ValueError, NotImplementedError):
        # Pillow 遇到 DX10 头或没见过的压缩格式会抛 NotImplementedError。
        # 预览失败就是没有预览，不该让整个列表塌掉。
        return None
