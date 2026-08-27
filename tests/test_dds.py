# -*- coding: utf-8 -*-
"""DDS 编码 / The hand-written DXT5 encoder."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core import dds
from core.repository import CropSettings


def _gradient(size: int = 128) -> Image.Image:
    """
    一张有色彩和透明梯度的测试图 / A test image with colour and alpha gradients.

    纯色图压出来永远没有误差，测不出编码器有没有把端点选错。
    """
    ramp = np.linspace(0, 255, size, dtype=np.uint8)
    pixels = np.zeros((size, size, 4), np.uint8)
    pixels[..., 0] = ramp[None, :]
    pixels[..., 1] = ramp[:, None]
    pixels[..., 2] = 128
    pixels[..., 3] = np.clip(ramp[None, :].astype(int) + ramp[:, None].astype(int),
                             0, 255).astype(np.uint8)
    return Image.fromarray(pixels, "RGBA")


def test_the_header_says_dxt5_with_a_full_mipmap_chain(tmp_path: Path) -> None:
    """
    头里要写明 DXT5 和完整的 mipmap 级数 / The header declares DXT5 and every level.

    游戏读的是头。级数写错，它要么少读一段、要么读过界。
    """
    dds.write_dxt5_dds(_gradient(256), tmp_path / "t.dds")
    header = (tmp_path / "t.dds").read_bytes()[:128]

    assert header[:4] == b"DDS "
    assert header[84:88] == b"DXT5"
    assert struct.unpack("<II", header[12:20]) == (256, 256)
    assert struct.unpack("<I", header[28:32])[0] == 9  # 256 → 1 共九级


def test_the_file_is_exactly_as_long_as_the_format_says(tmp_path: Path) -> None:
    """
    文件长度要和格式算出来的一致 / The file length matches the format exactly.

    128 字节头 + 每级 ``块数 × 16``。多一个字节少一个字节都说明分块或
    mipmap 链写错了，而这种错在图上看不出来。
    """
    dds.write_dxt5_dds(_gradient(64), tmp_path / "t.dds")

    expected = 128
    size = 64
    while size >= 1:
        blocks = max(1, (size + 3) // 4)
        expected += blocks * blocks * 16
        if size == 1:
            break
        size = max(1, size // 2)

    assert (tmp_path / "t.dds").stat().st_size == expected


def test_what_comes_back_out_looks_like_what_went_in(tmp_path: Path) -> None:
    """
    压完再解开，还得是原来那张图 / Decode the encoding and it still matches.

    BC3 是有损的，所以定的是误差上限而不是相等。上限定死之后，端点选取写错
    （比如取块内前两个像素而不是最远的一对）会立刻顶穿它。
    """
    source = _gradient(128)
    dds.write_dxt5_dds(source, tmp_path / "t.dds")

    decoded = np.asarray(Image.open(tmp_path / "t.dds").convert("RGBA"), dtype=np.int16)
    original = np.asarray(source, dtype=np.int16)

    for channel in range(3):
        assert np.abs(decoded[..., channel] - original[..., channel]).max() <= 16
    # alpha 每块只有八档插值，连续渐变必然量化；真正要紧的是抠图边缘那种
    # 非 0 即 255 的 alpha，见下一条
    assert np.abs(decoded[..., 3] - original[..., 3]).max() <= 4


def test_a_cutout_edge_keeps_its_alpha_exactly(tmp_path: Path) -> None:
    """
    非 0 即 255 的 alpha 必须一字不差 / Binary alpha must round-trip exactly.

    角色立绘就是这种 alpha：主体不透明、外面全透明。这里差一档，游戏里就是
    一圈半透明的毛边。BC3 把块内的最大和最小 alpha 原样存进去，所以只要
    端点取的是 max/min，这条就该恒成立——它守的是「有人把端点改成别的算法」。
    """
    # 边缘**故意不落在 4 的倍数上**：对齐的话每个块内部 alpha 都是均匀的，
    # 端点取 max 还是取均值都一样，这条测试就成了摆设
    pixels = np.zeros((32, 32, 4), np.uint8)
    pixels[..., :3] = 200
    pixels[9:23, 9:23, 3] = 255
    source = Image.fromarray(pixels, "RGBA")

    dds.write_dxt5_dds(source, tmp_path / "cutout.dds")
    decoded = np.asarray(Image.open(tmp_path / "cutout.dds").convert("RGBA"))

    assert np.array_equal(decoded[..., 3], pixels[..., 3])


def test_the_endpoints_are_the_farthest_pair_in_the_block(tmp_path: Path) -> None:
    """
    颜色端点要取块内**最远的那一对** / The colour endpoints span the block.

    随便取两个像素当端点，块内的极端色就没法表示了：这里的黑点和白点会一起
    塌成中灰。而整体误差看着不大——一块里只有两个像素错，平均下来很好看，
    所以只按平均误差判分的测试挡不住这个。
    """
    pixels = np.full((4, 4, 4), 128, np.uint8)
    pixels[..., 3] = 255
    pixels[1, 1, :3] = 0
    pixels[2, 2, :3] = 255

    dds.write_dxt5_dds(Image.fromarray(pixels, "RGBA"), tmp_path / "block.dds")
    decoded = np.asarray(Image.open(tmp_path / "block.dds").convert("RGBA"))

    assert decoded[1, 1, 0] < 60, "黑点被塌成灰了，说明端点没取到最暗那个"
    assert decoded[2, 2, 0] > 200, "白点被塌成灰了，说明端点没取到最亮那个"


def test_a_flat_colour_survives_untouched(tmp_path: Path) -> None:
    """
    纯色块不该被压出色差 / A flat colour must come back exactly.

    块内只有一种颜色时两个端点相同，插值出来的四档也都是它。压出偏差说明
    端点选取或 5:6:5 的还原写错了。
    """
    flat = Image.new("RGBA", (16, 16), (32, 64, 96, 255))
    dds.write_dxt5_dds(flat, tmp_path / "t.dds")

    decoded = np.asarray(Image.open(tmp_path / "t.dds").convert("RGBA"))[0, 0]
    # 5:6:5 只能表示 8 的倍数，所以比的是量化之后的值
    assert abs(int(decoded[0]) - 32) <= 8
    assert abs(int(decoded[1]) - 64) <= 4
    assert abs(int(decoded[2]) - 96) <= 8
    assert decoded[3] == 255


def test_a_size_that_is_not_a_multiple_of_four_still_works(tmp_path: Path) -> None:
    """
    边长不是 4 的倍数也要能压 / Sizes that do not divide by four still encode.

    1080 就不是 4 的倍数（1080 = 4 × 270 刚好整除，但它的 mipmap 会走到 135、
    67 这些奇数），补齐那段代码一直在被用到。
    """
    dds.write_dxt5_dds(_gradient(30), tmp_path / "t.dds")
    decoded = Image.open(tmp_path / "t.dds")
    assert decoded.size == (30, 30)


@pytest.mark.parametrize("zoom, offset_x, offset_y, expected", [
    (1.0, 0.0, 0.0, (0.0, 50.0, 300.0)),         # 短边整个进框，横向没有余量
    (2.0, -100.0, -100.0, (0.0, 0.0, 150.0)),    # 顶到左上角
    (2.0, 100.0, 100.0, (150.0, 250.0, 150.0)),  # 顶到右下角
])
def test_the_crop_box_never_leaves_the_image(zoom, offset_x, offset_y, expected) -> None:
    """
    取景框永远在图里面 / The crop box can never slide off the image.

    越界的话生成出来的贴图边上会出现一条透明带，而预览里看不出来。
    """
    assert dds.crop_box(300, 400, zoom, offset_x, offset_y) == expected


def test_the_zoom_is_clamped() -> None:
    """缩放要夹在区间内 / Zoom is clamped to the supported range."""
    _, _, tiny = dds.crop_box(400, 400, 1000.0, 0, 0)
    _, _, huge = dds.crop_box(400, 400, 0.01, 0, 0)
    assert tiny == pytest.approx(400 / dds.MAX_ZOOM)
    assert huge == pytest.approx(400 / dds.MIN_ZOOM)


def test_three_textures_come_out_at_the_sizes_the_game_wants(tmp_path: Path) -> None:
    """
    一张源图出三张贴图，尺寸固定 / One source, three textures at fixed sizes.

    1080 / 512 / 128 是游戏认的尺寸，不是可以商量的参数。
    """
    source = tmp_path / "source.png"
    _gradient(600).save(source)

    written = dds.generate_character_textures(
        source, tmp_path / "out", {"big": CropSettings(1.0, 0, 0)})

    assert set(written) == {"big", "small", "thumb"}
    for key, file_name, size in dds.TEXTURE_SIZES:
        assert Image.open(tmp_path / "out" / file_name).size == (size, size)


def test_a_missing_source_image_is_reported(tmp_path: Path) -> None:
    """源图不在要报出来 / A missing source image raises, it does not write junk."""
    with pytest.raises(FileNotFoundError):
        dds.generate_character_textures(tmp_path / "nope.png", tmp_path / "out")
