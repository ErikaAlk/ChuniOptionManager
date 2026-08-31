# -*- coding: utf-8 -*-
"""扫描、排查、保存、软删除、新增角色 / The repository layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import repository, xmlio
from core.repository import AddCharacterRequest
from tests.conftest import write_character, write_song, write_works


def _song(catalog, title: str, package: str = None):
    """按标题（和包名）取一首歌 / Find one song in a catalog."""
    for song in catalog.songs:
        if song.title == title and (package is None or song.package == package):
            return song
    raise AssertionError("假树里没有 {}".format(title))


# --- 扫描 -------------------------------------------------------------------

def test_the_scan_finds_everything_in_the_tree(option_root: Path) -> None:
    """扫描要把两个包里的歌和角色都找出来 / Both packages are scanned."""
    catalog = repository.scan(option_root)
    assert len(catalog.songs) == 4
    assert {song.package for song in catalog.songs} == {"A001", "A300"}
    assert {item.name for item in catalog.characters} == {"乳蛙", "无图角色"}


def test_a_broken_xml_only_loses_itself(option_root: Path) -> None:
    """
    坏掉的 XML 只影响它自己 / One bad file must not close the catalog.

    option 里塞的是各路自定义包，总会有一份写坏的。为了它打不开整个目录，
    是这个工具最不该有的失败方式。
    """
    broken = option_root / "A001" / "music" / "music000404"
    broken.mkdir(parents=True)
    (broken / "Music.xml").write_bytes(b"<MusicData><unclosed>")

    catalog = repository.scan(option_root)
    assert len(catalog.songs) == 4


def test_the_difficulties_come_back_normalised(option_root: Path) -> None:
    """``ID_0x`` / ``WorldsEnd`` 都要归一 / Raw forms are normalised on the way in."""
    song = _song(repository.scan(option_root), "Song One", "A001")
    assert [chart.difficulty for chart in song.charts] == [
        "BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA", "WORLD'S END"]


def test_the_card_shows_the_hardest_playable_chart(option_root: Path) -> None:
    """
    卡面代表难度取「开着且文件在」的最高档 / The card shows the hardest playable chart.

    ULTIMA 在假树里是关着的，所以代表难度应该是 MASTER 而不是 ULTIMA。
    """
    song = _song(repository.scan(option_root), "Song One", "A001")
    assert song.primary_difficulty == "MASTER"
    assert song.primary_level == "14"


def test_the_level_decimal_reads_as_a_fraction(option_root: Path) -> None:
    """``levelDecimal=50`` 是 ``.5``，不是 ``.50`` / Level decimals are tenths."""
    song = _song(repository.scan(option_root), "Song One", "A001")
    expert = next(chart for chart in song.charts if chart.difficulty == "EXPERT")
    assert expert.level_text == "12.5"


def test_a_character_prefers_the_texture_in_its_own_package(option_root: Path) -> None:
    """
    同名贴图优先取同包的那份 / Same-package textures win.

    跨包同名是常见的覆盖手法。取错包，角色就顶着别人的立绘。
    """
    write_character(option_root, "A300", 114514, "冒牌乳蛙")
    catalog = repository.scan(option_root)
    original = next(item for item in catalog.characters if item.package == "AZUR")
    assert "AZUR" in original.dds_xml_path


def test_the_recycle_area_is_not_scanned(option_root: Path) -> None:
    """软删除掉的东西不该再出现 / Deleted items stay out of the catalog."""
    catalog = repository.scan(option_root)
    repository.delete_music(option_root, _song(catalog, "Song Three"))
    assert len(repository.scan(option_root).songs) == 3


# --- 排查 -------------------------------------------------------------------

def test_missing_chart_files_merge_into_one_row(option_root: Path) -> None:
    """
    一首歌缺几个难度只报一条 / One row per song, not per difficulty.

    「Song Two」四个难度全缺，逐条报就是四行——排查页会被一首歌刷满。
    """
    issues = repository.scan(option_root).issues
    high = [issue for issue in issues if issue.severity == "High"]
    assert len(high) == 1
    assert "BASIC, ADVANCED, EXPERT, MASTER" in high[0].title


def test_a_duplicate_with_fewer_difficulties_is_flagged(option_root: Path) -> None:
    """同 ID 的重复项难度对不齐要报出来 / Inconsistent duplicates are flagged."""
    medium = [issue for issue in repository.scan(option_root).issues
              if issue.severity == "Medium"]
    assert len(medium) == 1
    assert "ADVANCED, EXPERT, MASTER" in medium[0].detail


def test_worlds_end_splits_are_not_flagged(option_root: Path) -> None:
    """
    WORLD'S END 拆成独立条目是正常的 / A WORLD'S END split is not a problem.

    游戏本来就把它拆开发。报出来就是天天有一屏假警报。
    """
    write_song(option_root, "A300", 77, "WE Song",
               fumens=((5, "WorldsEnd", "WORLD'S END", True, 0, 0),))
    write_song(option_root, "A001", 77, "WE Song",
               fumens=((0, "Basic", "BASIC", True, 5, 0),
                       (3, "Master", "MASTER", True, 14, 0)))

    titles = [issue.title for issue in repository.scan(option_root).issues]
    assert not any("WE Song" in title and "缺少" in title for title in titles)


def test_songs_without_a_valid_id_are_not_grouped(option_root: Path) -> None:
    """
    ID 为 0 的歌不算重复 / id=0 means "missing", not "the same song".

    把它们归成一组，会凭空刷出一大堆假的「重复项少难度」。
    """
    for index in range(3):
        song = write_song(option_root, "A001", 0, "No Id {}".format(index))
        directory = song.parent.with_name("noid{}".format(index))
        song.parent.rename(directory)

    medium = [issue for issue in repository.scan(option_root).issues
              if issue.severity == "Medium"]
    assert len(medium) == 1  # 只有假树本来那一条


def test_a_character_without_textures_is_flagged(option_root: Path) -> None:
    """贴图文件不在要报 Low / A character with no texture file is a Low issue."""
    low = [issue for issue in repository.scan(option_root).issues if issue.severity == "Low"]
    assert [issue.title for issue in low] == ["无图角色 缺少角色图索引"]


# --- 保存 -------------------------------------------------------------------

def test_saving_the_toggles_writes_them_back(option_root: Path) -> None:
    """开关要真的写回文件 / The toggles actually reach the file."""
    catalog = repository.scan(option_root)
    song = _song(catalog, "Song One", "A001")
    song.charts[4].enabled = True
    repository.save_chart_enable_states(song)

    again = _song(repository.scan(option_root), "Song One", "A001")
    assert again.charts[4].enabled


def test_saving_the_toggles_does_not_reformat_the_file(option_root: Path) -> None:
    """
    保存开关不许顺带重排格式 / Saving toggles must not reflow the rest of the file.

    ``Music.xml`` 是游戏自己发出来的文件，保存一次开关就重排一遍缩进，
    「到底改了什么」立刻变得没法看——而且改动是不可逆的，下次再存也回不去。
    走的是不是字节级那条路，只有这条测试看得出来：整份重写同样能把开关写对，
    功能测试全绿，差别只在别的字节动没动。
    """
    catalog = repository.scan(option_root)
    song = _song(catalog, "Song One", "A001")
    before = Path(song.xml_path).read_bytes()

    song.charts[4].enabled = True
    repository.save_chart_enable_states(song)

    after = Path(song.xml_path).read_bytes()
    expected = before.replace(b"<enable>false</enable>", b"<enable>true</enable>", 1)
    assert after == expected


def test_saving_the_toggles_leaves_a_backup(option_root: Path) -> None:
    """第一次保存要留 .bak / The first save leaves a backup behind."""
    song = _song(repository.scan(option_root), "Song One", "A001")
    repository.save_chart_enable_states(song)
    assert Path(song.xml_path + ".bak").is_file()


def test_saving_character_settings_writes_every_field(option_root: Path) -> None:
    """角色的字段要一个不落地写回 / Every edited field lands in Chara.xml."""
    catalog = repository.scan(option_root)
    character = next(item for item in catalog.characters if item.name == "乳蛙")
    character.name = "改名了"
    character.priority = 999
    character.works_id = 12345
    character.works = "新作品"
    character.default_have = False
    repository.save_character_settings(character)

    again = next(item for item in repository.scan(option_root).characters
                 if item.character_id == 114514)
    assert (again.name, again.priority, again.works_id, again.works, again.default_have) == \
        ("改名了", 999, 12345, "新作品", False)


# --- 软删除 -----------------------------------------------------------------

def test_deleting_moves_instead_of_removing(option_root: Path) -> None:
    """删除是搬家不是消失 / Deleting moves the folder, it never removes it."""
    catalog = repository.scan(option_root)
    song = _song(catalog, "Song Three")
    archive = repository.delete_music(option_root, song)

    assert Path(archive).is_dir()
    assert (Path(archive) / "A300" / "music" / "music000003" / "Music.xml").is_file()


def test_deleting_a_character_takes_its_textures_along(option_root: Path) -> None:
    """同包的贴图目录跟着走 / Same-package textures go with the character."""
    character = next(item for item in repository.scan(option_root).characters
                     if item.character_id == 114514)
    archive = Path(repository.delete_character(option_root, character))
    assert (archive / "AZUR" / "ddsImage" / "ddsImage114514").is_dir()


def test_a_borrowed_texture_directory_is_left_alone(option_root: Path) -> None:
    """
    跨包借来的贴图目录不连带删 / A texture folder in another package is not touched.

    它可能被别的角色共用，删了就是误伤——而误伤的是别人的立绘，还不容易发现。
    """
    write_character(option_root, "A300", 990000, "借图的", with_textures=True)
    # 把贴图挪去别的包，制造「角色在 A300、贴图在 AZUR」
    borrowed = option_root / "AZUR" / "ddsImage" / "ddsImage990000"
    (option_root / "A300" / "ddsImage" / "ddsImage990000").rename(borrowed)

    character = next(item for item in repository.scan(option_root).characters
                     if item.character_id == 990000)
    assert "AZUR" in character.dds_xml_path
    repository.delete_character(option_root, character)
    assert borrowed.is_dir()


def test_the_option_root_itself_cannot_be_deleted(option_root: Path) -> None:
    """根目录本身不许移走 / Refuse to move the option root itself."""
    with pytest.raises(ValueError):
        repository._move_to_deleted(option_root, "song", 1, "x", [option_root])


def test_nothing_outside_the_option_root_can_be_deleted(option_root: Path, tmp_path: Path) -> None:
    """
    外面的目录一律拒绝 / Anything outside the option root is refused.

    这道闸是整个删除路径唯一的护栏：只要构造得出一条指向外面的路径，
    没有它就能删掉 option 之外的东西。
    """
    outside = tmp_path / "somewhere-else"
    outside.mkdir()
    with pytest.raises(ValueError):
        repository._move_to_deleted(option_root, "song", 1, "x", [outside])
    assert outside.is_dir()


def test_two_deletes_in_the_same_second_do_not_collide(option_root: Path) -> None:
    """
    同一秒删两个同名条目不能撞目录 / Same-second deletes get separate folders.

    归档目录名只精确到秒。撞名之后 ``shutil.move`` 会把第二个塞进第一个里面，
    看上去删成功了，恢复时才发现结构错了。
    """
    write_song(option_root, "A001", 501, "Twin")
    write_song(option_root, "A300", 501, "Twin")
    catalog = repository.scan(option_root)
    twins = [song for song in catalog.songs if song.title == "Twin"]

    first = repository.delete_music(option_root, twins[0])
    second = repository.delete_music(option_root, twins[1])
    assert first != second
    assert Path(first).is_dir() and Path(second).is_dir()


# --- 作品库 -----------------------------------------------------------------

def test_a_new_works_entry_lands_in_the_chosen_package(option_root: Path) -> None:
    """作品要写进选定的包 / A works entry goes into the package that was picked."""
    works = repository.add_works(option_root, "A001", 900001, "新作品", "")
    assert works.package == "A001"
    assert Path(works.xml_path).is_file()
    assert works.priority == repository.DEFAULT_CUSTOM_PRIORITY


def test_a_duplicate_works_id_is_refused(option_root: Path) -> None:
    """作品 ID 撞号要拦下 / A duplicate works id is refused."""
    with pytest.raises(ValueError):
        repository.add_works(option_root, "A001", 11451, "撞号", "")


def test_a_new_works_entry_goes_first_in_the_sort_list(option_root: Path) -> None:
    """新作品插在排序表最前面 / A new entry is put first, so it is findable."""
    repository.add_works(option_root, "AZUR", 900002, "排前面", "")
    sort_path = option_root / "AZUR" / "charaWorks" / "WorksSort.xml"
    root = xmlio.parse(sort_path).getroot()
    ids = [xmlio.int_of(item, "id") for item in root.find("SortList").findall("StringID")]
    assert ids[0] == 900002


def test_the_sort_list_never_holds_the_same_id_twice(option_root: Path) -> None:
    """同一个 ID 不能在排序表里出现两次 / No duplicates in the sort list."""
    sort_path = option_root / "AZUR" / "charaWorks" / "WorksSort.xml"
    repository.add_works_to_sort_first(sort_path, 4242)
    repository.add_works_to_sort_first(sort_path, 4242)

    root = xmlio.parse(sort_path).getroot()
    ids = [xmlio.int_of(item, "id") for item in root.find("SortList").findall("StringID")]
    assert ids.count(4242) == 1


def test_a_created_sort_list_carries_the_namespaces(option_root: Path) -> None:
    """新建的 WorksSort.xml 要带命名空间声明 / A fresh sort list gets the xmlns lines."""
    sort_path = option_root / "A300" / "charaWorks" / "WorksSort.xml"
    repository.add_works_to_sort_first(sort_path, 7)
    text = sort_path.read_text(encoding="utf-8")
    assert "xmlns:xsd" in text and "xmlns:xsi" in text


def test_deleting_a_works_entry_takes_its_characters(option_root: Path) -> None:
    """
    删作品连带删属于它的角色 / Deleting a works entry cascades to its characters.

    这是整个应用破坏性最强的一步，所以它必须**真的**发生：留下一批指向已删作品
    的孤儿角色，游戏里同样翻不出来，还更难查。
    """
    works = next(item for item in repository.list_works(option_root) if item.works_id == 11451)
    repository.delete_works(option_root, works)

    remaining = repository.scan(option_root).characters
    assert all(item.works_id != 11451 for item in remaining)


def test_an_invalid_works_id_does_not_cascade(option_root: Path) -> None:
    """
    works id 为 0 时不许连带 / id=0 must not sweep up every unassigned character.

    0 表示「没有作品 / 解析失败」。放任 cascade，一次删除就会带走所有没填作品的
    角色——「无图角色」正是这种。
    """
    orphan = write_works(option_root, "A300", 0, "空作品")
    works = next(item for item in repository.list_works(option_root)
                 if item.xml_path == str(orphan))
    repository.delete_works(option_root, works)

    names = {item.name for item in repository.scan(option_root).characters}
    assert "无图角色" in names


# --- 新增角色 ---------------------------------------------------------------

def test_a_new_character_is_written_from_the_template(option_root: Path) -> None:
    """新角色按模板生成 / A new character is cloned from the AZUR template."""
    new_id = repository.add_character(option_root, AddCharacterRequest(
        name="测试角色", works_id=11451, works_name="アズールレーン"))

    created = next(item for item in repository.scan(option_root).characters
                   if item.character_id == new_id)
    assert created.name == "测试角色"
    assert created.priority == repository.DEFAULT_CUSTOM_PRIORITY
    assert created.image_key == "chara{}_00".format(new_id)


def test_an_auto_allocated_id_starts_above_the_game_range(option_root: Path) -> None:
    """自动分配的 ID 不占游戏本体的号段 / Auto ids stay in the custom range."""
    new_id = repository.add_character(option_root, AddCharacterRequest(name="自动号"))
    assert new_id >= repository.MIN_CUSTOM_CHARACTER_ID


def test_an_id_already_in_the_recycle_area_is_refused(option_root: Path) -> None:
    """
    回收区里的 ID 不能重新发出去 / Ids in the recycle area are still taken.

    软删除的角色随时可能被恢复。重用它的号，恢复的那一刻就撞车了。
    """
    character = next(item for item in repository.scan(option_root).characters
                     if item.character_id == 20540)
    repository.delete_character(option_root, character)

    with pytest.raises(ValueError):
        repository.add_character(option_root, AddCharacterRequest(
            character_id=20540, name="抢号"))


def test_no_texture_means_no_dds_file(option_root: Path) -> None:
    """
    不给源图就不写任何 DDS / Without a source image, no texture is written.

    套模板的贴图会让新角色顶着乳蛙的脸——那比没有立绘更让人困惑。
    """
    new_id = repository.add_character(option_root, AddCharacterRequest(name="没有立绘"))
    folder = option_root / "AZUR" / "ddsImage" / "ddsImage{}".format(new_id)
    assert folder.is_dir()
    assert not (folder / "big.dds").exists()


def test_a_source_image_becomes_three_textures(option_root: Path, tmp_path: Path) -> None:
    """
    给了源图就写出三张贴图 / A source image produces all three textures.

    这条把「写 XML」和「生成 DDS」这两半连起来测：两边各自的单元测试都过，
    但接线接错（比如把取景传给了错的那一张）只有整条走一遍才看得出来。
    """
    from PIL import Image

    source = tmp_path / "portrait.png"
    Image.new("RGBA", (600, 800), (200, 120, 40, 255)).save(source)

    new_id = repository.add_character(option_root, AddCharacterRequest(
        name="有立绘", source_image_path=str(source)))

    folder = option_root / "AZUR" / "ddsImage" / "ddsImage{}".format(new_id)
    for file_name, size in (("big.dds", 1080), ("small.dds", 512), ("thumb.dds", 128)):
        assert Image.open(folder / file_name).size == (size, size)


def test_a_failed_creation_leaves_nothing_behind(option_root: Path) -> None:
    """
    半路失败要回滚 / A failure rolls the new directories back.

    否则 option 里会留下一个没有贴图的残缺角色，而那个 ID 从此被永久占用——
    下次想用同一个号还会被自己拦下来。
    """
    before = set(repository.collect_character_ids(option_root))
    with pytest.raises((OSError, ValueError)):
        repository.add_character(option_root, AddCharacterRequest(
            name="会失败", source_image_path=str(option_root / "does-not-exist.png")))
    assert set(repository.collect_character_ids(option_root)) == before


def test_an_empty_name_is_refused(option_root: Path) -> None:
    """角色名不能空 / An unnamed character is refused."""
    with pytest.raises(ValueError):
        repository.add_character(option_root, AddCharacterRequest(name="   "))


@pytest.mark.parametrize("base, skin, expected", [
    ("11451", "4", 114514),
    ("2469", "0", 24690),
    ("2469", "", 24690),
    ("0", "0", None),
    ("-5", "0", None),
    ("2469", "10", None),
    ("abc", "0", None),
])
def test_the_character_id_is_composed_from_base_and_skin(base, skin, expected) -> None:
    """最终 ID = 基 ID × 10 + 皮肤 ID / The id is composed, not typed whole."""
    assert repository.compose_character_id(base, skin) == expected


def test_the_package_list_puts_the_template_package_first(option_root: Path) -> None:
    """AZUR 排最前 / The template package leads the list; it is the default target."""
    assert repository.list_packages(option_root)[0] == "AZUR"


def test_the_recycle_area_is_not_a_package(option_root: Path) -> None:
    """``_deleted`` 不是一个可写入的包 / The recycle area is not offered as a target."""
    catalog = repository.scan(option_root)
    repository.delete_music(option_root, _song(catalog, "Song Three"))
    assert "_deleted" not in repository.list_packages(option_root)


def test_the_scan_can_report_determinate_progress(option_root) -> None:
    """
    扫描能报出「第几个 / 一共几个」/ The scan reports a determinate ratio.

    规范 5.1：可计算完成比例时显示 Determinate Progress，不可计算时才用不确定的
    转圈。总数要走完目录才知道，所以前几次回调的总数是 0——界面据此先转圈，
    拿到总数之后再切成确定进度。
    """
    ticks = []
    catalog = repository.scan(str(option_root), lambda done, total: ticks.append((done, total)))

    assert ticks[0] == (0, 0)
    determinate = [tick for tick in ticks if tick[1] > 0]
    assert determinate, "走完目录之后一次确定进度都没报"

    total = determinate[-1][1]
    assert determinate[-1][0] == total
    # 歌曲和角色两段都要报，少一段的表现是进度条走到一半忽然跳到底
    assert [done for done, _ in determinate] == list(range(0, total + 1))
    assert total >= len(catalog.songs) + len(catalog.characters)


def test_a_broken_progress_callback_does_not_break_the_scan(option_root) -> None:
    """
    进度回调炸了不能带着扫描一起炸 / A bad progress callback must not kill the scan.

    进度是锦上添花的东西，它出问题的代价不该是「整个目录打不开」。
    """
    def explode(_done, _total):
        raise RuntimeError("界面那边出事了")

    catalog = repository.scan(str(option_root), explode)
    assert catalog.songs
