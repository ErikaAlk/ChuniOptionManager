# -*- coding: utf-8 -*-
"""找 option 目录、记住它 / Locating and remembering the option root."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import paths


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    把配置目录挪进临时目录 / Redirect the config directory.

    不隔离的话，跑一次测试就会改掉本机真正在用的那份配置——测试污染开发环境
    是最烦人的那种副作用。
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return tmp_path


def test_one_marker_is_not_enough(tmp_path: Path) -> None:
    """
    只有一个包不算 option 根目录 / One marker package is not enough.

    判据放宽到「有一个就算」的话，任何一个叫 A001 的文件夹都会被认成 option。
    """
    root = tmp_path / "half"
    (root / "A001" / "music" / "m1").mkdir(parents=True)
    (root / "A001" / "music" / "m1" / "Music.xml").write_text("<MusicData />")
    assert not paths.looks_like_option_root(root)


def test_markers_without_any_music_are_not_enough(tmp_path: Path) -> None:
    """
    空壳目录不算 / Empty marker folders are not an option root.

    只看目录名就认，会让人把一个刚建好、还没解压的空目录选进去，
    然后对着空列表纳闷。
    """
    root = tmp_path / "shell"
    for name in ("A001", "A300"):
        (root / name).mkdir(parents=True)
    assert not paths.looks_like_option_root(root)


def test_a_real_tree_is_recognised(option_root: Path) -> None:
    """真的 option 树要认得出来 / A real tree is recognised."""
    assert paths.looks_like_option_root(option_root)


def test_the_folder_above_option_works(option_root: Path) -> None:
    """
    选 option 的上一层也能认 / Picking the folder above option still works.

    让人在文件对话框里精确点中 ``option`` 才算数，是没必要的刁难。
    """
    assert paths.normalise_option_root(option_root.parent) == option_root.resolve()


def test_the_game_root_two_levels_up_works(tmp_path: Path) -> None:
    """选游戏根目录（option 在 bin 底下）也能认 / The game root resolves to bin\\option."""
    option = tmp_path / "CHUNITHM" / "bin" / "option"
    for name in ("A001", "A300"):
        (option / name).mkdir(parents=True)
    song = option / "A001" / "music" / "music000001"
    song.mkdir(parents=True)
    (song / "Music.xml").write_text("<MusicData />", encoding="utf-8")

    assert paths.normalise_option_root(tmp_path / "CHUNITHM") == option.resolve()


def test_picking_the_exe_works_too(option_root: Path) -> None:
    """直接选 exe 也认 / Pointing at a file resolves to its folder."""
    exe = option_root.parent / "chusanApp.exe"
    exe.write_bytes(b"MZ")
    assert paths.normalise_option_root(exe) == option_root.resolve()


def test_something_that_is_not_an_option_root_comes_back_empty(tmp_path: Path) -> None:
    """认不出来就是认不出来 / An unrelated folder resolves to nothing."""
    assert paths.normalise_option_root(tmp_path) is None


def test_the_choice_is_remembered(option_root: Path) -> None:
    """选过的目录要记住 / The chosen root is persisted and read back."""
    paths.remember_option_root(option_root)
    assert paths.stored_option_root() == option_root.resolve()


def test_a_remembered_root_that_moved_away_is_dropped(option_root: Path) -> None:
    """
    记着的目录不在了就当没记 / A remembered root that no longer exists is ignored.

    游戏搬了家之后应该重新去探测、去问人，而不是拿着一条死路径报「目录不存在」。
    """
    paths.remember_option_root(option_root)
    for item in option_root.iterdir():
        if item.name.startswith("A"):
            item.rename(item.with_name("x" + item.name))
    assert paths.stored_option_root() is None


def test_a_broken_config_does_not_stop_anything(isolated_config: Path) -> None:
    """
    配置文件损坏不该拦住启动 / A corrupt config must not block startup.

    磁盘满、断电、手改错，都会留下半截 JSON。为它打不开程序是不可接受的。
    """
    config = paths.config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("{ this is not json", encoding="utf-8")
    assert paths.load_config() == {}


def test_the_installer_seed_is_picked_up(option_root: Path) -> None:
    """
    安装程序留下的种子要能被读到 / The installer's seed file is honoured.

    安装器写的就是这一个文件——读不到它，安装时问的那一页就白问了。
    """
    seed = paths.config_dir() / paths.INSTALLER_SEED
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text(str(option_root), encoding="utf-8")
    assert paths.auto_detect_option_root() == option_root.resolve()


def test_the_config_wins_over_the_installer_seed(option_root: Path, tmp_path: Path) -> None:
    """
    应用里改过的设置压过安装器留下的种子 / The in-app choice beats the seed.

    否则每次升级安装都会把人在应用里换过的目录顶回去。
    """
    other = tmp_path / "other-option"
    (other / "A001" / "music" / "m1").mkdir(parents=True)
    (other / "A001" / "music" / "m1" / "Music.xml").write_text("<MusicData />")
    (other / "A300").mkdir(parents=True)

    paths.remember_option_root(other)
    seed = paths.config_dir() / paths.INSTALLER_SEED
    seed.write_text(str(option_root), encoding="utf-8")

    assert paths.auto_detect_option_root() == other.resolve()


def test_the_environment_variable_is_honoured(option_root: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量能指定目录 / The environment variable points the app at a tree."""
    monkeypatch.setenv(paths.ENV_OPTION_ROOT, str(option_root))
    assert paths.auto_detect_option_root() == option_root.resolve()


def test_saving_the_config_keeps_the_other_keys(option_root: Path) -> None:
    """
    存配置不能丢掉别的键 / Saving one setting keeps the rest.

    以后加窗口尺寸、上次选的排序之类的东西时，这条挡住「存一次丢一半」。
    """
    paths.save_config({"window": {"width": 1440}})
    paths.remember_option_root(option_root)
    assert paths.load_config()["window"] == {"width": 1440}
