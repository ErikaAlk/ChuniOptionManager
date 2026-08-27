# -*- coding: utf-8 -*-
"""
主窗口 / The main window.

左边三页（歌曲 / 角色 / 排查），右边按需展开检查器面板。扫描在后台线程跑，
界面只负责发起和收结果——option 树有一万多个文件，在界面线程扫会白屏一秒多。
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import difficulty, paths, repository
from core.models import CharacterItem, MusicItem, OptionCatalog
from ui import cards, imagecache, theme
from ui.add_character import AddCharacterDialog
from ui.cards import CharacterDelegate, IssueDelegate, ObjectListModel, SongDelegate
from ui.editors import CharacterInspector, SongInspector
from ui.first_run import OptionRootDialog

#: 列表最多摆多少条。再多就不是「找东西」而是「刷屏」了，搜索框才是出路。
MAX_ROWS = 2000

#: 状态提示停留多久（毫秒），按严重程度分档。
STATUS_TIMEOUT = {"success": 4500, "warning": 6500, "error": 8000}

#: 歌曲排序的选项：``(显示名, 键)``。
SONG_SORTS = (
    ("按 sortName", "sort"),
    ("按 ID", "id"),
    ("按标题", "title"),
    ("按包名", "package"),
    ("按最高难度", "difficulty"),
    ("缺失优先", "missing"),
)

#: 角色排序的选项。
CHARACTER_SORTS = (
    ("按 sortName", "sort"),
    ("按 ID", "id"),
    ("按角色名", "name"),
    ("按作品", "works"),
    ("按 priority", "priority"),
    ("按包名", "package"),
)

#: 难度筛选。最后一项不是难度，是「只看有问题的」。
DIFFICULTY_FILTERS = ("全部",) + difficulty.ORDER + ("文件缺失",)


def log_crash(scope: str, error: BaseException) -> None:
    """
    把异常追加到日志 / Append a traceback to the log file.

    日志写在配置目录而不是安装目录：安装目录可能只读，写不进去就等于没有日志。
    记日志本身绝不能再抛异常，所以整段包着。
    """
    try:
        target = paths.log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("[{}] {}\n".format(
                __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"), scope))
            handle.write("".join(traceback.format_exception(
                type(error), error, error.__traceback__)))
            handle.write("\n")
    except Exception:
        pass


class _ScanSignals(QObject):
    """扫描线程发回来的东西 / What the scan worker reports."""

    done = Signal(object, str)


class _ScanTask(QRunnable):
    """在后台扫一遍 option / Scan the option tree off the UI thread."""

    def __init__(self, root: str, signals: _ScanSignals) -> None:
        super().__init__()
        self._root = root
        self._signals = signals

    def run(self) -> None:
        """扫 / Scan, reporting either a catalog or an error message."""
        try:
            self._signals.done.emit(repository.scan(self._root), "")
        except Exception as error:  # 扫描失败不该让程序退出，摆到状态条上
            log_crash("scan", error)
            self._signals.done.emit(None, str(error))


class StatusBanner(QLabel):
    """
    右下角那条状态提示 / The transient status line.

    成功的消息停留得短，错误停留得久——看错误要时间，看「保存好了」不用。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setMaximumWidth(460)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, title: str, message: str, level: str = "success") -> None:
        """摆一条消息 / Show one message for a level-appropriate while."""
        colour = {
            "success": theme.SYSTEM["green"],
            "warning": theme.SYSTEM["orange"],
            "error": theme.SYSTEM["red"],
        }.get(level, theme.SYSTEM["gray"])
        self.setText("<b>{}</b><br>{}".format(title, message))
        self.setStyleSheet(
            "background: {}; border: 1px solid {}; border-left: 3px solid {};"
            "border-radius: {}px; padding: 10px 14px; color: {};".format(
                theme.BG_GROUP, theme.SEPARATOR, colour, theme.RADIUS_CONTROL, theme.LABEL))
        self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(STATUS_TIMEOUT.get(level, 6000))


class MainWindow(QMainWindow):
    """整个应用就这一个窗口 / The one window this app has."""

    def __init__(self, option_root: str) -> None:
        super().__init__()
        self.setWindowTitle("CHUNITHM Option Manager")
        self.setWindowIcon(theme.app_icon())
        self.resize(1440, 900)
        self.setMinimumSize(QSize(1120, 720))

        self._root = option_root
        self._catalog = OptionCatalog()
        self._ready = False
        self._scan_signals = _ScanSignals()
        self._scan_signals.done.connect(self._on_scanned)

        self._build()
        self._ready = True
        imagecache.instance().changed.connect(self._repaint_lists)
        theme.apply_dark_titlebar(self)
        self.reload()

    # -- 装配 -------------------------------------------------------------

    def _build(self) -> None:
        """把界面搭出来 / Assemble the window."""
        surface = QWidget()
        surface.setObjectName("Surface")
        self.setCentralWidget(surface)

        root_layout = QVBoxLayout(surface)
        root_layout.setContentsMargins(theme.SPACE_WINDOW, theme.SPACE_WINDOW,
                                       theme.SPACE_WINDOW, theme.SPACE_WINDOW)
        root_layout.setSpacing(theme.SPACE_GROUP)

        root_layout.addLayout(self._build_header())
        root_layout.addLayout(self._build_filters())

        columns = QHBoxLayout()
        columns.setSpacing(theme.SPACE_GROUP)

        self._nav = QListWidget()
        self._nav.setObjectName("Sidebar")
        self._nav.setFixedWidth(168)
        for text in ("歌曲", "角色", "排查"):
            self._nav.addItem(QListWidgetItem(text))
        self._nav.setCurrentRow(0)
        self._nav.currentRowChanged.connect(self._on_page_changed)
        columns.addWidget(self._nav)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_song_page())
        self._pages.addWidget(self._build_character_page())
        self._pages.addWidget(self._build_issue_page())
        columns.addWidget(self._pages, 1)

        self._inspector = QStackedWidget()
        self._inspector.setFixedWidth(460)
        self._song_inspector = SongInspector()
        self._song_inspector.closed.connect(self._hide_inspector)
        self._song_inspector.save_requested.connect(self._save_song)
        self._song_inspector.delete_requested.connect(self._delete_song)
        self._song_inspector.open_requested.connect(
            lambda: self._open_folder(self._song_inspector.song))
        self._inspector.addWidget(self._song_inspector)

        self._character_inspector = CharacterInspector()
        self._character_inspector.closed.connect(self._hide_inspector)
        self._character_inspector.save_requested.connect(self._save_character)
        self._character_inspector.delete_requested.connect(self._delete_character)
        self._character_inspector.open_requested.connect(
            lambda: self._open_folder(self._character_inspector.character))
        self._inspector.addWidget(self._character_inspector)
        self._inspector.hide()
        columns.addWidget(self._inspector)

        root_layout.addLayout(columns, 1)

        self._status = StatusBanner(surface)

    def _build_header(self) -> QHBoxLayout:
        """顶上那一行 / The title row."""
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_ROW)
        title = QLabel("CHUNITHM Option Manager")
        title.setObjectName("Title")
        row.addWidget(title)
        row.addStretch(1)

        pick = QPushButton("切换 option 目录")
        pick.clicked.connect(self._pick_root)
        row.addWidget(pick)

        self._reload_button = QPushButton("重新扫描")
        self._reload_button.clicked.connect(self.reload)
        row.addWidget(self._reload_button)
        return row

    def _build_filters(self) -> QHBoxLayout:
        """搜索和筛选那一行 / The search and filter row."""
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_ROW)

        root_column = QVBoxLayout()
        root_column.setSpacing(4)
        root_column.addWidget(theme.field_label("option 根目录"))
        self._root_box = QLineEdit(self._root)
        self._root_box.setReadOnly(True)
        root_column.addWidget(self._root_box)
        row.addLayout(root_column, 3)

        search_column = QVBoxLayout()
        search_column.setSpacing(4)
        search_column.addWidget(theme.field_label("搜索"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("标题 / ID / 曲师 / 角色名")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filters)
        search_column.addWidget(self._search)
        row.addLayout(search_column, 2)

        difficulty_column = QVBoxLayout()
        difficulty_column.setSpacing(4)
        difficulty_column.addWidget(theme.field_label("难度"))
        self._difficulty = QComboBox()
        self._difficulty.addItems(DIFFICULTY_FILTERS)
        self._difficulty.currentIndexChanged.connect(self._apply_filters)
        difficulty_column.addWidget(self._difficulty)
        row.addLayout(difficulty_column, 1)
        return row

    def _build_song_page(self) -> QWidget:
        """歌曲页 / The songs page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_ROW)

        header = QHBoxLayout()
        self._song_count = theme.secondary_label("")
        header.addWidget(self._song_count)
        header.addStretch(1)
        self._song_sort = _sort_box(SONG_SORTS, self._apply_filters)
        header.addWidget(self._song_sort)
        layout.addLayout(header)

        self._song_model = ObjectListModel()
        self._song_view = _list_view(self._song_model, SongDelegate(page))
        self._song_view.clicked.connect(self._on_song_clicked)
        layout.addWidget(self._song_view, 1)
        return page

    def _build_character_page(self) -> QWidget:
        """角色页 / The characters page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_ROW)

        header = QHBoxLayout()
        self._character_count = theme.secondary_label("")
        header.addWidget(self._character_count)
        header.addStretch(1)
        self._character_sort = _sort_box(CHARACTER_SORTS, self._apply_filters)
        header.addWidget(self._character_sort)
        add = QPushButton("新增角色")
        add.setObjectName("Primary")
        add.clicked.connect(self._add_character)
        header.addWidget(add)
        layout.addLayout(header)

        self._character_model = ObjectListModel()
        self._character_view = _list_view(self._character_model, CharacterDelegate(page))
        self._character_view.setViewMode(QListView.IconMode)
        self._character_view.setResizeMode(QListView.Adjust)
        self._character_view.setWrapping(True)
        self._character_view.setSpacing(0)
        self._character_view.clicked.connect(self._on_character_clicked)
        layout.addWidget(self._character_view, 1)
        return page

    def _build_issue_page(self) -> QWidget:
        """排查页 / The issues page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_ROW)

        self._issue_count = theme.secondary_label("")
        layout.addWidget(self._issue_count)

        self._issue_model = ObjectListModel()
        self._issue_view = _list_view(self._issue_model, IssueDelegate(page))
        self._issue_view.setSelectionMode(QListView.NoSelection)
        layout.addWidget(self._issue_view, 1)
        return page

    # -- 扫描 -------------------------------------------------------------

    def reload(self) -> None:
        """重新扫一遍 / Rescan the option tree."""
        if not os.path.isdir(self._root):
            self._status.show_message("目录不在了", self._root, "error")
            return
        self._set_busy(True)
        imagecache.instance().clear()
        QThreadPool.globalInstance().start(_ScanTask(self._root, self._scan_signals))

    def _on_scanned(self, catalog: Optional[OptionCatalog], error: str) -> None:
        """收下扫描结果 / Take the scan result."""
        self._set_busy(False)
        if catalog is None:
            self._status.show_message("扫描失败", error or "未知错误", "error")
            return

        self._catalog = catalog
        self._apply_filters()
        self._issue_model.replace(catalog.issues)
        self._issue_count.setText("排查项 {} 条".format(len(catalog.issues)))
        self._status.show_message(
            "扫描完成",
            "歌曲 {} 首，角色 {} 个，排查项 {} 条。".format(
                len(catalog.songs), len(catalog.characters), len(catalog.issues)),
            "success")

    def _set_busy(self, busy: bool) -> None:
        """扫描时把交互关掉 / Disable interaction while scanning."""
        for widget in (self._search, self._difficulty, self._song_sort,
                       self._character_sort, self._song_view, self._character_view,
                       self._reload_button):
            widget.setEnabled(not busy)

    # -- 筛选与排序 -------------------------------------------------------

    def _apply_filters(self) -> None:
        """
        重新过一遍列表 / Re-filter and re-sort both lists.

        窗口还没搭完时不能跑：这里要读一串具名控件，早一步调用就是 AttributeError。
        """
        if not self._ready:
            return

        query = self._search.text().strip()
        wanted = self._difficulty.currentText()

        songs = [song for song in self._catalog.songs if song.matches(query)]
        if wanted == "文件缺失":
            songs = [song for song in songs if song.has_missing_enabled_file]
        elif wanted != "全部":
            songs = [song for song in songs if song.has_enabled(wanted)]
        songs = _sort_songs(songs, self._song_sort.currentData())[:MAX_ROWS]
        self._song_model.replace(songs)
        self._song_count.setText("歌曲 {} / {} 首".format(len(songs), len(self._catalog.songs)))

        characters = [item for item in self._catalog.characters if item.matches(query)]
        characters = _sort_characters(characters, self._character_sort.currentData())[:MAX_ROWS]
        self._character_model.replace(characters)
        self._character_count.setText("角色 {} / {} 个".format(
            len(characters), len(self._catalog.characters)))

    def _repaint_lists(self) -> None:
        """有新贴图解好了，重画一次 / A texture arrived; repaint."""
        self._song_view.viewport().update()
        self._character_view.viewport().update()

    # -- 页面与检查器 -----------------------------------------------------

    def _on_page_changed(self, row: int) -> None:
        """换页时收起检查器 / Switching pages closes the inspector."""
        self._pages.setCurrentIndex(max(0, row))
        self._hide_inspector()

    def _hide_inspector(self) -> None:
        """收起检查器 / Close the inspector."""
        self._inspector.hide()

    def _on_song_clicked(self, index) -> None:
        """选中一首歌 / A song was clicked."""
        song = index.data(cards.OBJECT_ROLE)
        if song is None:
            return
        self._song_inspector.show_song(song)
        self._inspector.setCurrentWidget(self._song_inspector)
        self._inspector.show()

    def _on_character_clicked(self, index) -> None:
        """选中一个角色 / A character was clicked."""
        character = index.data(cards.OBJECT_ROLE)
        if character is None:
            return
        self._character_inspector.show_character(character)
        self._inspector.setCurrentWidget(self._character_inspector)
        self._inspector.show()

    def resizeEvent(self, event) -> None:  # noqa: D102 - Qt 的回调
        super().resizeEvent(event)
        self._place_status()

    def _place_status(self) -> None:
        """把状态条钉在右下角 / Pin the status line to the bottom right."""
        surface = self.centralWidget()
        if not surface:
            return
        self._status.adjustSize()
        self._status.move(
            max(theme.SPACE_WINDOW, surface.width() - self._status.width() - theme.SPACE_WINDOW),
            max(theme.SPACE_WINDOW, surface.height() - self._status.height() - theme.SPACE_WINDOW))

    def _notify(self, title: str, message: str, level: str = "success") -> None:
        """摆一条状态 / Show a status message, positioned correctly."""
        self._status.show_message(title, message, level)
        self._place_status()

    # -- 动作 -------------------------------------------------------------

    def _pick_root(self) -> None:
        """换一个 option 目录 / Point the app at another option root."""
        dialog = OptionRootDialog(self._root, self)
        if dialog.exec() != QDialog.Accepted or not dialog.chosen:
            return
        self._root = dialog.chosen
        self._root_box.setText(self._root)
        self._hide_inspector()
        self.reload()

    def _open_folder(self, item) -> None:
        """在文件浏览器里打开 / Reveal the item's folder."""
        if item is None:
            self._notify("没有选中东西", "先在列表里点一个。", "warning")
            return
        folder = Path(item.xml_path).parent
        if not folder.is_dir():
            self._notify("目录不在了", str(folder), "error")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))  # noqa: S606 - 就是要交给资源管理器
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError as error:
            self._notify("打不开目录", str(error), "error")

    def _confirm(self, title: str, message: str) -> bool:
        """
        危险动作的确认 / Confirm a destructive action.

        默认按钮是「取消」：手滑连按回车不该删掉东西。
        """
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QMessageBox.Warning)
        move = box.addButton("移入回收区", QMessageBox.AcceptRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is move

    def _save_song(self) -> None:
        """保存谱面开关 / Write the enable toggles back."""
        song = self._song_inspector.song
        if song is None:
            self._notify("没有选中歌曲", "先在列表里点一首。", "warning")
            return
        try:
            repository.save_chart_enable_states(song)
        except (OSError, ValueError) as error:
            log_crash("save_song", error)
            self._notify("保存失败", str(error), "error")
            return
        self._notify("已保存", "写回 {}，第一次保存会留一份 .bak。".format(song.relative_path))
        self._reload_and_reselect(song.xml_path, self._reselect_song)

    def _delete_song(self) -> None:
        """软删除一首歌 / Move a song into the recycle area."""
        song = self._song_inspector.song
        if song is None:
            self._notify("没有选中歌曲", "先在列表里点一首。", "warning")
            return
        if not self._confirm("删除歌曲",
                             "把「{}」的歌曲目录移进 option\\_deleted。\n"
                             "文件不会被真删除，重新扫描时不再显示。".format(song.title)):
            return
        try:
            archive = repository.delete_music(self._root, song)
        except (OSError, ValueError) as error:
            log_crash("delete_song", error)
            self._notify("删除失败", str(error), "error")
            return
        self._hide_inspector()
        self._notify("已删除", "移到了 {}。".format(os.path.relpath(archive, self._root)))
        self.reload()

    def _save_character(self) -> None:
        """保存角色设置 / Write character metadata back."""
        problem = self._character_inspector.collect()
        if problem:
            self._notify("保存失败", problem, "warning")
            return
        character = self._character_inspector.character
        try:
            repository.save_character_settings(character)
        except (OSError, ValueError) as error:
            log_crash("save_character", error)
            self._notify("保存失败", str(error), "error")
            return
        self._notify("已保存", "写回 {}，第一次保存会留一份 .bak。".format(character.relative_path))
        self._reload_and_reselect(character.xml_path, self._reselect_character)

    def _delete_character(self) -> None:
        """软删除一个角色 / Move a character into the recycle area."""
        character = self._character_inspector.character
        if character is None:
            self._notify("没有选中角色", "先在列表里点一个。", "warning")
            return
        if not self._confirm("删除角色",
                             "把「{}」的 Chara 目录、以及同包的 DDSImage 目录移进 "
                             "option\\_deleted。\n文件不会被真删除。".format(character.name)):
            return
        try:
            archive = repository.delete_character(self._root, character)
        except (OSError, ValueError) as error:
            log_crash("delete_character", error)
            self._notify("删除失败", str(error), "error")
            return
        self._hide_inspector()
        self._notify("已删除", "移到了 {}。".format(os.path.relpath(archive, self._root)))
        self.reload()

    def _add_character(self) -> None:
        """新增角色 / Create a character."""
        dialog = AddCharacterDialog(self._root, self)
        if dialog.exec() != QDialog.Accepted:
            return
        request = dialog.request()
        try:
            new_id = repository.add_character(self._root, request)
        except (OSError, ValueError) as error:
            log_crash("add_character", error)
            self._notify("新增角色失败", str(error), "error")
            return
        self._notify("已新增角色", "{} 写进了 {}（ID {}，priority {}）。".format(
            request.name.strip(), repository.TEMPLATE_PACKAGE, new_id,
            repository.DEFAULT_CUSTOM_PRIORITY))
        self.reload()

    def _reload_and_reselect(self, xml_path: str, reselect: Callable[[str], None]) -> None:
        """
        存完重新扫描，并把刚才那条重新选中 / Rescan, then re-select what was edited.

        保存之后目录里的东西可能变了（比如谱面文件的存在与否），所以不复用内存里
        那份旧对象；重新扫完按 XML 路径找回来。
        """
        def once(catalog: Optional[OptionCatalog], error: str) -> None:
            self._scan_signals.done.disconnect(once)
            self._on_scanned(catalog, error)
            if catalog is not None:
                reselect(xml_path)

        self._scan_signals.done.connect(once)
        self.reload()

    def _reselect_song(self, xml_path: str) -> None:
        """把刚存过的歌重新摆进检查器 / Re-open the song that was just saved."""
        for song in self._catalog.songs:
            if os.path.normcase(song.xml_path) == os.path.normcase(xml_path):
                self._song_inspector.show_song(song)
                return

    def _reselect_character(self, xml_path: str) -> None:
        """把刚存过的角色重新摆进检查器 / Re-open the character that was just saved."""
        for character in self._catalog.characters:
            if os.path.normcase(character.xml_path) == os.path.normcase(xml_path):
                self._character_inspector.show_character(character)
                return


def _sort_box(options: Sequence, on_change) -> QComboBox:
    """排序下拉 / A sort combo box."""
    box = QComboBox()
    for label, key in options:
        box.addItem(label, key)
    box.setMinimumWidth(150)
    box.currentIndexChanged.connect(on_change)
    return box


def _list_view(model, delegate) -> QListView:
    """统一配置的列表视图 / A list view wired the same way everywhere."""
    view = QListView()
    view.setModel(model)
    view.setItemDelegate(delegate)
    view.setSelectionMode(QListView.SingleSelection)
    view.setMouseTracking(True)
    view.setUniformItemSizes(True)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    view.setVerticalScrollMode(QListView.ScrollPerPixel)
    view.setFrameShape(QFrame.NoFrame)
    return view


def _sort_songs(songs: List[MusicItem], key: str) -> List[MusicItem]:
    """给歌曲排序 / Sort songs by the chosen key."""
    if key == "id":
        return sorted(songs, key=lambda song: (song.song_id, song.sort_title.casefold()))
    if key == "title":
        return sorted(songs, key=lambda song: (song.title.casefold(), song.song_id))
    if key == "package":
        return sorted(songs, key=lambda song: (song.package.casefold(), song.sort_title.casefold()))
    if key == "difficulty":
        return sorted(songs, key=lambda song: (
            -(song.primary_chart.rank if song.primary_chart else -1),
            -(song.primary_chart.level if song.primary_chart else -1),
            song.sort_title.casefold()))
    if key == "missing":
        return sorted(songs, key=lambda song: (not song.has_missing_enabled_file,
                                               song.sort_title.casefold()))
    return sorted(songs, key=lambda song: (song.sort_title.casefold(), song.song_id))


def _sort_characters(items: List[CharacterItem], key: str) -> List[CharacterItem]:
    """给角色排序 / Sort characters by the chosen key."""
    if key == "id":
        return sorted(items, key=lambda item: (item.character_id, item.sort_name.casefold()))
    if key == "name":
        return sorted(items, key=lambda item: (item.name.casefold(), item.character_id))
    if key == "works":
        return sorted(items, key=lambda item: (item.works.casefold(), item.sort_name.casefold()))
    if key == "priority":
        return sorted(items, key=lambda item: (-item.priority, item.sort_name.casefold()))
    if key == "package":
        return sorted(items, key=lambda item: (item.package.casefold(), item.sort_name.casefold()))
    return sorted(items, key=lambda item: (item.sort_name.casefold(), item.character_id))
