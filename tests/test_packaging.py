# -*- coding: utf-8 -*-
"""打包用的那几个文件本身 / The packaging files themselves."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_requirements_stays_ascii() -> None:
    """
    requirements.txt 必须是纯 ASCII / The requirements file must stay ASCII-only.

    **没有 BOM 时 pip 按「本机 locale 编码」去解 requirements 文件**，不是 UTF-8。
    在中文 Windows 上，文件里有一个中文注释就会让 ``pip install -r`` 在装第一个包
    之前直接抛 ``'gbk' codec can't decode byte``——而报错信息完全看不出是注释的锅。
    实测踩过一次。
    """
    raw = (ROOT / "requirements.txt").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "别加 BOM，直接写成 ASCII"
    raw.decode("ascii")


def test_the_installer_script_keeps_its_bom() -> None:
    """
    installer.iss 必须带 UTF-8 BOM / The Inno script must keep its BOM.

    没有 BOM 的话 ISCC 按 ANSI 读，安装器里所有中文都是乱码——**而且它不报错**，
    要装一遍才看得见。
    """
    raw = (ROOT / "packaging" / "installer.iss").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "选择 option 文件夹" in raw.decode("utf-8-sig")


def test_the_version_is_the_single_source() -> None:
    """
    版本号只有一处 / The version lives in exactly one place.

    exe 的版本资源、安装包文件名、控制面板里显示的版本全从 ``core/version.py`` 读。
    再写一份就迟早对不上。
    """
    from core.version import __version__

    spec = (ROOT / "packaging" / "app.spec").read_text(encoding="utf-8")
    installer = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8-sig")

    assert 'core" / "version.py"' in spec
    assert '#define AppVersion "0.0.0"' in installer, "只允许作为兜底默认值出现"
    assert __version__ not in installer, "版本号不许写死在 iss 里，靠 /DAppVersion 传"
