# -*- coding: utf-8 -*-
"""
界面 / The Qt layer.

在 ``offscreen`` 平台上跑，不需要显示器。这里测的不是「好不好看」，而是
**画得出来、点得动、状态对得上**——自绘的 delegate 里一个属性名写错，
在源码里只会打印一行 Qt 警告，界面照样开，卡片却是空的。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import repository  # noqa: E402
from ui import theme  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    """
    整个测试会话共用一个 QApplication / One QApplication for the whole session.

    Qt 不允许一个进程里同时存在两个。
    """
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.stylesheet())
    return app


@pytest.fixture
def window(qt_app, option_root: Path):
    """一个扫描完毕的主窗口 / A main window that has finished its first scan."""
    from ui.main_window import MainWindow

    main = MainWindow(str(option_root))
    # 必须真的 show()：没显示出来的窗口，子控件的 isVisible() 一律是 False，
    # 「检查器展开了没有」就测不出来
    main.show()
    QThreadPool.globalInstance().waitForDone(30000)
    qt_app.processEvents()
    return main


def test_the_stylesheet_has_no_blanket_widget_rule() -> None:
    """
    样式表里不许有 ``QWidget {`` / No blanket QWidget rule in the stylesheet.

    QSS 的类型选择器连子类一起命中，一条 ``QWidget { background: … }`` 会把每个
    QLabel 都刷上底色，在卡片上显示成一条条横杠。这是这套界面上一代真实坏过的
    样子，所以钉一条测试守着。
    """
    import re

    # 只挡「选择器就是 QWidget」那一条；``QScrollArea > QWidget`` 这种带上下文的
    # 限定不在此列，它只命中滚动区自己的视口
    assert not re.search(r"(?m)^\s*QWidget\s*\{", theme.stylesheet())


def test_the_stylesheet_lets_mica_show_through() -> None:
    """
    挂上 Mica 的窗口不许自己画底 / A mica window must not paint its own background.

    DWM 的材质画在窗口下面。窗口自己再刷一层不透明底色，材质就永远看不见——
    而这在源码里完全看不出来，样式表照样合法、窗口照样开。
    """
    sheet = theme.stylesheet()
    assert 'QMainWindow[mica="true"], QDialog[mica="true"] { background: transparent; }' in sheet
    # 中间那层 #Surface 铺满整个客户区，它不透明的话上面那条就白设了
    assert 'QMainWindow[mica="true"] #Surface' in sheet


def test_mica_is_not_tried_below_windows_11(qt_app, monkeypatch) -> None:
    """
    Win10 上根本不去试 / Never even attempt Mica below Windows 11.

    那几个属性号在 Win10 上不认，硬设的结果是一个透明窗口罩在没有材质的桌面上。
    """
    from PySide6.QtWidgets import QWidget

    tried = []
    monkeypatch.setattr(theme, "windows_build", lambda: 19045)
    monkeypatch.setattr(theme, "_enable_backdrop", lambda handle: tried.append(handle))
    assert theme.supports_mica() is False

    widget = QWidget()
    assert theme.apply_mica(widget) is False
    # 断言「根本没去调」而不只是「返回了 False」：调用失败也会返回 False，
    # 那样这条测试就挡不住「把版本判断删掉」这种改法
    assert tried == []
    assert not widget.testAttribute(Qt.WA_TranslucentBackground)

    monkeypatch.setattr(theme, "windows_build", lambda: 22000)
    assert theme.supports_mica() is True


def test_the_backdrop_attribute_follows_the_build() -> None:
    """
    属性号按版本挑 / The right attribute for each build.

    22H2 起才有正式的 ``DWMWA_SYSTEMBACKDROP_TYPE``；21H2 只认没进文档的 1029。
    挑错的表现是调用返回错误码，窗口就那么透明着。
    """
    assert theme._backdrop_attribute(22631) == (theme.DWMWA_SYSTEMBACKDROP_TYPE,
                                                theme.DWMSBT_MAINWINDOW)
    assert theme._backdrop_attribute(22000) == (theme.DWMWA_MICA_EFFECT, 1)


def test_mica_marks_the_window_for_the_stylesheet(qt_app, monkeypatch) -> None:
    """挂上了就打上标记 / A successful backdrop marks the window."""
    from PySide6.QtWidgets import QWidget

    monkeypatch.setattr(theme, "supports_mica", lambda: True)
    monkeypatch.setattr(theme, "_enable_backdrop", lambda handle: None)

    widget = QWidget()
    assert theme.apply_mica(widget) is True
    assert widget.property("mica") is True
    assert widget.testAttribute(Qt.WA_TranslucentBackground)


def test_a_failed_backdrop_leaves_the_window_opaque(qt_app, monkeypatch) -> None:
    """
    DWM 不给就把透明收回去 / Roll the translucency back when DWM says no.

    透明属性留着而底下没有材质，用户看到的是一个黑窟窿——比没有 Mica 难看得多，
    而且只在那几台调用失败的机器上出现，这边永远复现不了。
    """
    from PySide6.QtWidgets import QWidget

    def refuse(handle):
        raise OSError("DwmSetWindowAttribute 返回 0x80070057")

    monkeypatch.setattr(theme, "supports_mica", lambda: True)
    monkeypatch.setattr(theme, "_enable_backdrop", refuse)

    widget = QWidget()
    assert theme.apply_mica(widget) is False
    assert not widget.testAttribute(Qt.WA_TranslucentBackground)
    assert not widget.property("mica")


def test_every_state_of_the_accent_colour_is_derived() -> None:
    """
    hover / pressed 都从主色推出来 / Every accent state derives from one constant.

    各写各的十六进制值，换主题色时漏改一处就花了。
    """
    assert theme.ACCENT_HOVER == theme.mix(theme.ACCENT, "#FFFFFF", 0.14)
    assert theme.ACCENT_PRESSED == theme.mix(theme.ACCENT, "#000000", 0.14)
    assert theme.ACCENT.upper() == "#B44BFF"


def test_the_switch_reports_what_it_shows(qt_app) -> None:
    """开关点一下要真的变 / The switch actually toggles."""
    switch = theme.Switch()
    assert not switch.isChecked()
    switch.setChecked(True)
    assert switch.isChecked()


def test_the_lists_fill_up_after_the_scan(window) -> None:
    """扫完之后三个列表都该有东西 / All three lists are populated after the scan."""
    assert window._song_model.rowCount() == 4
    assert window._character_model.rowCount() == 2
    assert window._issue_model.rowCount() >= 2


def test_every_page_paints(window, qt_app) -> None:
    """
    三页都要画得出来 / Every page paints without raising.

    自绘的 delegate 抛异常时 Qt 只在 stderr 打一行、照样把窗口开出来——
    不真画一遍，这种错在测试里是看不见的。
    """
    for row in (0, 1, 2):
        window._nav.setCurrentRow(row)
        qt_app.processEvents()
        assert not window.grab().isNull()


def test_the_inspector_opens_on_a_song(window, qt_app) -> None:
    """点一首歌就展开检查器 / Clicking a song opens the inspector."""
    window._on_song_clicked(window._song_model.index(0, 0))
    qt_app.processEvents()
    assert window._inspector.isVisible()
    assert window._song_inspector.song is not None
    assert not window.grab().isNull()


def test_the_inspector_opens_on_a_character(window, qt_app) -> None:
    """点一个角色就展开检查器 / Clicking a character opens the inspector."""
    window._nav.setCurrentRow(1)
    window._on_character_clicked(window._character_model.index(0, 0))
    qt_app.processEvents()
    assert window._character_inspector.character is not None
    assert not window.grab().isNull()


def test_the_search_box_narrows_the_list(window, qt_app) -> None:
    """搜索要真的筛掉东西 / Typing in the search box narrows the list."""
    window._search.setText("Song Two")
    qt_app.processEvents()
    assert window._song_model.rowCount() == 1


def test_the_difficulty_filter_narrows_the_list(window, qt_app) -> None:
    """
    难度筛选按「开着的难度」筛 / The filter matches enabled charts.

    假树里那首重复的「Song One」只开了 BASIC，所以按 MASTER 筛应该少一首。
    """
    window._difficulty.setCurrentText("MASTER")
    qt_app.processEvents()
    assert window._song_model.rowCount() == 3


def test_the_missing_filter_finds_the_broken_song(window, qt_app) -> None:
    """「文件缺失」筛出的正是那首缺谱面的歌 / The missing filter finds exactly that song."""
    window._difficulty.setCurrentText("文件缺失")
    qt_app.processEvents()
    assert window._song_model.rowCount() == 1
    assert window._song_model.items()[0].title == "Song Two"


def test_every_sort_order_works(window, qt_app) -> None:
    """六种排序都不能抛 / None of the sort orders raises."""
    for index in range(window._song_sort.count()):
        window._song_sort.setCurrentIndex(index)
        qt_app.processEvents()
        assert window._song_model.rowCount() == 4


def test_the_toggles_in_the_inspector_reach_the_model(window, qt_app) -> None:
    """
    面板上的开关要改到数据上 / Flipping a switch changes the chart object.

    只改界面不改数据的话，点了保存写回去的还是原样——而界面看上去是对的。
    """
    window._on_song_clicked(window._song_model.index(0, 0))
    qt_app.processEvents()
    song = window._song_inspector.song
    before = song.charts[4].enabled

    switch = _find_switch(window._song_inspector, index=4)
    switch.setChecked(not before)
    assert song.charts[4].enabled == (not before)


def test_the_character_form_refuses_a_non_integer(window, qt_app) -> None:
    """
    整数字段填了非整数要拦下 / A non-integer in a numeric field is refused.

    而且是**全有或全无**：拦下之后，同一次编辑里改过的名字也不能悄悄写进对象，
    否则点一次保存失败，数据已经被改了一半。
    """
    window._nav.setCurrentRow(1)
    window._on_character_clicked(window._character_model.index(0, 0))
    qt_app.processEvents()

    inspector = window._character_inspector
    original_name = inspector.character.name
    inspector._name.setText("改过的名字")
    inspector._priority.setText("不是数字")

    assert inspector.collect() is not None
    assert inspector.character.name == original_name


def test_an_empty_character_name_is_refused(window, qt_app) -> None:
    """角色名不能空 / An empty name is refused before it reaches the file."""
    window._nav.setCurrentRow(1)
    window._on_character_clicked(window._character_model.index(0, 0))
    qt_app.processEvents()

    window._character_inspector._name.setText("   ")
    assert window._character_inspector.collect() is not None


def test_the_add_character_dialog_offers_the_works_library(qt_app, option_root: Path) -> None:
    """
    新增角色时能选到作品 / The works library is reachable from the add dialog.

    作品选不对，角色在游戏里按分类就检索不到——这是这个对话框最容易被忽略、
    后果又最难查的一格。
    """
    from ui.add_character import AddCharacterDialog

    dialog = AddCharacterDialog(str(option_root))
    # 假树里一个作品，加上末尾那条「（不填）Invalid」
    assert dialog._works_box.count() == 2
    assert dialog.request().works_id == repository.DEFAULT_AZUR_WORKS_ID


def test_the_composed_id_is_echoed_as_it_is_typed(qt_app, option_root: Path) -> None:
    """最终 ID 要当场回显 / The composed id is echoed while typing."""
    from ui.add_character import AddCharacterDialog

    dialog = AddCharacterDialog(str(option_root))
    dialog._base_id.setText("2469")
    dialog._skin_id.setText("0")
    assert dialog._final_id.text() == "24690"

    dialog._skin_id.setText("99")
    assert dialog._final_id.text() == "无效"


def test_the_option_root_dialog_validates_as_you_type(qt_app, option_root: Path,
                                                      tmp_path: Path) -> None:
    """
    选目录窗口当场判断行不行 / The folder dialog validates before you commit.

    等点了「确定」再报错，就是让人多点一次才知道结果。
    """
    from ui.first_run import OptionRootDialog

    dialog = OptionRootDialog(str(option_root))
    assert dialog.chosen == str(option_root.resolve())

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    dialog._path.setText(str(elsewhere))
    assert dialog.chosen == ""


def _find_switch(widget, index: int):
    """找出面板里第 *index* 个开关 / The *index*-th switch inside a panel."""
    switches = widget.findChildren(theme.Switch)
    assert len(switches) > index
    return switches[index]
