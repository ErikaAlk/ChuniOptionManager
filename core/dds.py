# -*- coding: utf-8 -*-
"""
把普通图片写成游戏认的 DDS / Encoding PNG or JPG into the DDS the game reads.

游戏的角色贴图是 **DXT5（BC3）、带完整 mipmap 链** 的 DDS，三张一组：
``big.dds`` 1080、``small.dds`` 512、``thumb.dds`` 128。没有现成的 Python 库
能直接写这个组合（Pillow 只读不写 mipmap），所以编码器在这里手写，用 numpy
按块向量化——一张 1080 的图连 mipmap 有九万多个块，逐块 Python 循环要跑几分钟。

解码在 :mod:`core.ddspreview`，走 Pillow，那边不需要手写。
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
from PIL import Image

#: 三张贴图各自的边长 / The three texture sizes the game expects.
TEXTURE_SIZES: Tuple[Tuple[str, str, int], ...] = (
    ("big", "big.dds", 1080),
    ("small", "small.dds", 512),
    ("thumb", "thumb.dds", 128),
)

#: 缩放上下限。放得比 10 倍还大只会糊，不如挡住。
MIN_ZOOM = 1.0
MAX_ZOOM = 10.0

#: 一次处理多少个块。块表是 ``(N, 16, 16)`` 的距离矩阵，全图一把算下来
#: 会吃掉几百 MB；分批之后峰值稳定在几十 MB，速度没有可测差别。
_CHUNK = 8192


def _clamp(value: float, low: float, high: float) -> float:
    """夹到区间里 / Clamp."""
    return max(low, min(high, value))


def crop_box(
    source_width: int,
    source_height: int,
    zoom: float,
    offset_x: float,
    offset_y: float,
) -> Tuple[float, float, float]:
    """
    算出取景框 / Work out the square crop taken from the source image.

    取景框永远是正方形，边长 = 短边 / 缩放；偏移是 -100~100 的百分比，
    映射到「能移动的范围」上，所以框永远不会越出图外。

    参数 / Parameters:
        source_width (int): 源图宽。
        source_height (int): 源图高。
        zoom (float): 缩放，1 表示整个短边都进框。
        offset_x (float): 水平偏移，-100 最左、100 最右。
        offset_y (float): 垂直偏移，-100 最上、100 最下。

    返回 / Returns:
        Tuple[float, float, float]: ``(left, top, size)``。

    界面上的预览和这里的实际裁剪**必须用同一套算法**，否则拖出来的位置和
    生成出来的贴图对不上——这正是这个函数被单独摘出来的原因。
    """
    min_side = min(source_width, source_height)
    size = min_side / _clamp(zoom, MIN_ZOOM, MAX_ZOOM)
    max_x = max(0.0, source_width - size)
    max_y = max(0.0, source_height - size)
    left = max_x * ((_clamp(offset_x, -100.0, 100.0) + 100.0) / 200.0)
    top = max_y * ((_clamp(offset_y, -100.0, 100.0) + 100.0) / 200.0)
    return left, top, size


def render_square(source: Image.Image, output_size: int, crop: Any = None) -> Image.Image:
    """
    按取景框裁出一张正方形 / Render one square texture out of the source.

    参数 / Parameters:
        source (Image.Image): 源图，任何 Pillow 读得了的格式。
        output_size (int): 输出边长。
        crop (Any): 带 ``zoom`` / ``offset_x`` / ``offset_y`` 的对象；
            ``None`` 表示整幅短边居中。

    返回 / Returns:
        Image.Image: RGBA 模式的正方形图。
    """
    zoom = getattr(crop, "zoom", 1.0)
    offset_x = getattr(crop, "offset_x", 0.0)
    offset_y = getattr(crop, "offset_y", 0.0)

    rgba = source if source.mode == "RGBA" else source.convert("RGBA")
    left, top, size = crop_box(rgba.width, rgba.height, zoom, offset_x, offset_y)
    return rgba.resize(
        (output_size, output_size),
        Image.LANCZOS,
        box=(left, top, left + size, top + size),
    )


def build_mipmaps(image: Image.Image) -> List[Image.Image]:
    """
    生成完整 mipmap 链 / Build the full mipmap chain, down to 1x1.

    每一级从**上一级**缩，不是从原图缩——和显卡自己生成 mipmap 的做法一致，
    逐级缩出来的过渡更平滑。
    """
    levels = [image]
    current = image
    while current.width > 1 or current.height > 1:
        current = current.resize(
            (max(1, current.width // 2), max(1, current.height // 2)), Image.LANCZOS)
        levels.append(current)
    return levels


def _dds_header(width: int, height: int, mipmap_count: int) -> bytes:
    """
    128 字节的 DDS 头 / The 128-byte DDS header for a mipmapped DXT5 texture.

    标志位是固定组合：``0x000A1007`` = CAPS|HEIGHT|WIDTH|PIXELFORMAT|
    MIPMAPCOUNT|LINEARSIZE，``0x00401008`` = TEXTURE|MIPMAP|COMPLEX。
    """
    linear_size = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
    parts = [
        struct.pack("<4s", b"DDS "),
        struct.pack("<7I", 124, 0x000A1007, height, width, linear_size, 0, mipmap_count),
        b"\x00" * (11 * 4),
        struct.pack("<2I", 32, 0x00000004),
        struct.pack("<4s", b"DXT5"),
        b"\x00" * (5 * 4),
        struct.pack("<I", 0x00401008),
        b"\x00" * (4 * 4),
    ]
    return b"".join(parts)


def _to_blocks(pixels: np.ndarray) -> np.ndarray:
    """
    把像素切成 4x4 的块 / Cut the image into 4x4 blocks.

    宽高不是 4 的倍数时用**边缘像素补齐**（而不是补透明），这样块内不会凭空
    多出一条与画面无关的边，压出来也不会在边上产生色带。

    参数 / Parameters:
        pixels (np.ndarray): ``(h, w, 4)`` 的 uint8 RGBA。

    返回 / Returns:
        np.ndarray: ``(块数, 16, 4)`` 的 uint8。
    """
    height, width = pixels.shape[:2]
    blocks_y = max(1, (height + 3) // 4)
    blocks_x = max(1, (width + 3) // 4)

    rows = np.minimum(np.arange(blocks_y * 4), height - 1)
    cols = np.minimum(np.arange(blocks_x * 4), width - 1)
    padded = pixels[rows][:, cols]

    grid = padded.reshape(blocks_y, 4, blocks_x, 4, 4)
    return grid.transpose(0, 2, 1, 3, 4).reshape(blocks_y * blocks_x, 16, 4)


def _encode_alpha(alpha: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    压 BC3 的 alpha 部分 / Encode the alpha half of each block.

    端点取块内的最大和最小值，中间六档线性插值，每个像素取最近的一档。

    参数 / Parameters:
        alpha (np.ndarray): ``(N, 16)`` 的 uint8。

    返回 / Returns:
        Tuple[np.ndarray, np.ndarray]: ``(端点 (N, 2), 3 位索引 (N, 16))``。
    """
    high = alpha.max(axis=1).astype(np.int32)
    low = alpha.min(axis=1).astype(np.int32)

    weights = np.arange(2, 8, dtype=np.int32)
    table = np.empty((alpha.shape[0], 8), dtype=np.int32)
    table[:, 0] = high
    table[:, 1] = low
    table[:, 2:] = ((8 - weights) * high[:, None] + (weights - 1) * low[:, None]) // 7

    distance = np.abs(alpha.astype(np.int32)[:, :, None] - table[:, None, :])
    indices = distance.argmin(axis=2).astype(np.uint8)
    endpoints = np.stack([high, low], axis=1).astype(np.uint8)
    return endpoints, indices


def _to_rgb565(colours: np.ndarray) -> np.ndarray:
    """RGB 压成 16 位 / Pack RGB into 5:6:5."""
    red = colours[..., 0].astype(np.uint32) >> 3
    green = colours[..., 1].astype(np.uint32) >> 2
    blue = colours[..., 2].astype(np.uint32) >> 3
    return ((red << 11) | (green << 5) | blue).astype(np.uint16)


def _from_rgb565(packed: np.ndarray) -> np.ndarray:
    """16 位还原成 RGB / Unpack 5:6:5 back to 8-bit RGB, the way a GPU does."""
    value = packed.astype(np.int32)
    red = (value >> 11) & 31
    green = (value >> 5) & 63
    blue = value & 31
    return np.stack([red * 255 // 31, green * 255 // 63, blue * 255 // 31], axis=-1)


def _encode_colour(colours: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    压 BC3 的颜色部分 / Encode the colour half of each block.

    端点选块内**距离最远的那一对**像素（欧氏距离的平方，只看 RGB）。这是
    最朴素的做法，压出来比不上 stb_dxt 那种带迭代求精的编码器，但足够稳，
    而且不会引入外部依赖。

    参数 / Parameters:
        colours (np.ndarray): ``(N, 16, 3)`` 的 uint8 RGB。

    返回 / Returns:
        Tuple[np.ndarray, np.ndarray, np.ndarray]: ``(color0, color1, 2 位索引)``。
    """
    values = colours.astype(np.int32)
    delta = values[:, :, None, :] - values[:, None, :, :]
    distance = (delta * delta).sum(axis=3)

    # 只看上三角（i < j），并且按 i 升序、j 升序展平——argmax 取第一个最大值，
    # 于是并列时选中的那一对和逐对扫描的顺序一致。
    upper = np.triu(np.ones((16, 16), dtype=bool), k=1)
    distance = np.where(upper[None, :, :], distance, -1)
    flat = distance.reshape(distance.shape[0], -1).argmax(axis=1)
    first = flat // 16
    second = flat % 16

    rows = np.arange(values.shape[0])
    colour_a = _to_rgb565(values[rows, first])
    colour_b = _to_rgb565(values[rows, second])

    # 四色模式要求 color0 > color1，否则解码端会切到「三色 + 透明」那套
    swap = colour_a < colour_b
    colour0 = np.where(swap, colour_b, colour_a).astype(np.uint16)
    colour1 = np.where(swap, colour_a, colour_b).astype(np.uint16)

    end0 = _from_rgb565(colour0)
    end1 = _from_rgb565(colour1)
    palette = np.stack([
        end0,
        end1,
        (2 * end0 + end1) // 3,
        (end0 + 2 * end1) // 3,
    ], axis=1)

    delta = values[:, :, None, :] - palette[:, None, :, :]
    indices = (delta * delta).sum(axis=3).argmin(axis=2).astype(np.uint8)
    return colour0, colour1, indices


def _pack_blocks(blocks: np.ndarray) -> bytes:
    """
    把一批块压成 DXT5 的字节 / Turn a batch of blocks into DXT5 bytes.

    每块 16 字节：2 字节 alpha 端点 + 6 字节 3 位索引 + 4 字节颜色端点
    + 4 字节 2 位索引。
    """
    count = blocks.shape[0]
    endpoints, alpha_indices = _encode_alpha(blocks[:, :, 3])
    colour0, colour1, colour_indices = _encode_colour(blocks[:, :, :3])

    alpha_bits = np.zeros(count, dtype=np.uint64)
    for position in range(16):
        alpha_bits |= alpha_indices[:, position].astype(np.uint64) << np.uint64(3 * position)

    colour_bits = np.zeros(count, dtype=np.uint32)
    for position in range(16):
        colour_bits |= colour_indices[:, position].astype(np.uint32) << np.uint32(2 * position)

    output = np.zeros((count, 16), dtype=np.uint8)
    output[:, 0:2] = endpoints
    for byte in range(6):
        output[:, 2 + byte] = ((alpha_bits >> np.uint64(8 * byte)) & np.uint64(0xFF)).astype(np.uint8)
    output[:, 8:10] = colour0.view(np.uint8).reshape(count, 2)
    output[:, 10:12] = colour1.view(np.uint8).reshape(count, 2)
    output[:, 12:16] = colour_bits.view(np.uint8).reshape(count, 4)
    return output.tobytes()


def encode_dxt5(image: Image.Image) -> bytes:
    """
    一层图像压成 DXT5 / Compress one mip level to DXT5 bytes.

    参数 / Parameters:
        image (Image.Image): RGBA 图像。

    返回 / Returns:
        bytes: 这一层的块数据。
    """
    pixels = np.asarray(image if image.mode == "RGBA" else image.convert("RGBA"), dtype=np.uint8)
    blocks = _to_blocks(pixels)
    chunks = [_pack_blocks(blocks[start:start + _CHUNK])
              for start in range(0, blocks.shape[0], _CHUNK)]
    return b"".join(chunks)


def write_dxt5_dds(image: Image.Image, path: Any) -> None:
    """
    写出一张带 mipmap 的 DXT5 DDS / Write one mipmapped DXT5 file.

    参数 / Parameters:
        image (Image.Image): 最高一级的图像。
        path (Any): 落点。
    """
    levels = build_mipmaps(image if image.mode == "RGBA" else image.convert("RGBA"))
    payload = [_dds_header(image.width, image.height, len(levels))]
    payload.extend(encode_dxt5(level) for level in levels)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    with open(temp, "wb") as handle:
        handle.write(b"".join(payload))
    temp.replace(target)


def generate_character_textures(
    source_image_path: Any,
    destination: Any,
    crops: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    """
    一张源图出三张角色贴图 / One source image, three character textures.

    参数 / Parameters:
        source_image_path (Any): 源图（PNG / JPG / BMP 等 Pillow 读得了的格式）。
        destination (Any): 输出目录，通常是新角色的 ``ddsImage<id>``。
        crops (Optional[Mapping[str, Any]]): ``{"big"/"small"/"thumb": 取景}``；
            缺哪个就用默认取景。

    返回 / Returns:
        Dict[str, str]: ``{"big": 路径, ...}``。

    异常 / Raises:
        FileNotFoundError: 源图不在。
        OSError: 源图读不了（改了扩展名的非图片、WebP 之类）。
    """
    source = Path(source_image_path)
    if not source.is_file():
        raise FileNotFoundError("找不到源图片：{}".format(source_image_path))

    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=True)
    settings = dict(crops or {})

    written: Dict[str, str] = {}
    with Image.open(source) as opened:
        rgba = opened.convert("RGBA")

    for key, file_name, size in TEXTURE_SIZES:
        target = folder / file_name
        write_dxt5_dds(render_square(rgba, size, settings.get(key)), target)
        written[key] = str(target)
    return written
