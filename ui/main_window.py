# -*- coding: utf-8 -*-
"""
主窗口 / The main window.

左边三页（歌曲 / 角色 / 排查），右边按需展开检查器面板。扫描在后台线程跑，
界面只负责发起和收结果——option 树有一万多个文件，在界面线程扫会白屏一秒多。

三个列表都是数据页，八种状态各有各的样子：扫描时是带进度的 Loading，
扫完没东西是 Empty（还给一个最相关的下一步），扫失败是 Error（带重试），
解析失败的条目落到排查页当 Partial。
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
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import difficulty, paths, repository
from core.models import CharacterItem, MusicItem, OptionCatalog
from ui import cards, imagecache, theme, tokens
from ui.add_character import AddCharacterDialog
from ui.cards import CharacterDelegate, IssueDelegate, ObjectListModel, SongDelegate
from ui.editors import CharacterInspector, SongInspector
from ui.first_run import OptionRootDialog

#: 列表最多摆多少条。再多就不是「找东西」而是「刷屏」了，搜索框才是出路。
MAX_ROWS = 2000

#: 状态提示停留多久（毫秒）。成功的短，出错的**根本不自动消失**——
#: 规范 5.1 要求错误保留到用户处理或关闭为止。
STATUS_TIMEOUT = {"success": 2000, "warning": 6000, "error": 0}

#: 扫描进度每隔多少个文件报一次。一万多个文件逐个发信号会把事件循环塞满。
PROGRESS_STEP = 25

#: 状态条的宽度。**必须先钉死宽度再算高度**：里面是会换行的富文本标签，
#: 宽度不定时 ``heightForWidth`` 算不出来，``adjustSize`` 给回一个偏矮的高度，
#: 摆到右下角就有一截露在窗口外面。
TOAST_WIDTH = 420

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
    progress = Signal(int, int)


class _ScanTask(QRunnable):
    """在后台扫一遍 option / Scan the option tree off the UI thread."""

    def __init__(self, root: str, signals: _ScanSignals) -> None:
        super().__init__()
        self._root = root
        self._signals = signals
        self._last = -1

    def _report(self, done: int, total: int) -> None:
        """
        往界面线程报进度 / Push progress across to the UI thread.

        每 :data:`PROGRESS_STEP` 个报一次。一万多个文件逐个发信号，
        事件循环光处理信号就够呛，进度条反而更卡。
        """
        if total and done != total and done - self._last < PROGRESS_STEP:
            return
        self._last = done
        self._signals.progress.emit(done, total)

    def run(self) -> None:
        """扫 / Scan, reporting either a catalog or an error message."""
        try:
            self._signals.done.emit(repository.scan(self._root, self._report), "")
        except Exception as error:  # 扫描失败不该让程序退出，摆到状态条上
            log_crash("scan", error)
            self._signals.done.emit(None, str(error))


class StatusBanner(QFrame):
    """
    右下角那条状态提示 / The transient status line.

    成功的消息 2 秒就走，**错误一直留着**直到用户点掉——看错误要时间，
    而且错误里往往有下一步该做什么。它是临时浮层，走 surfaceElevated
    加 elevation.2，压在最上面一层（``tokens.LAYER_TOAST``）。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFixedWidth(TOAST_WIDTH)
        self.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.PADDING_CONTAINER, tokens.GAP_CONTROL,
                                  tokens.GAP_CONTROL, tokens.GAP_CONTROL)
        layout.setSpacing(tokens.GAP_CONTROL)

        texts = QVBoxLayout()
        texts.setSpacing(tokens.GAP_RELATED)
        self._title = theme.wrapped_label("", "sectionTitle")
        texts.addWidget(self._title)
        self._detail = theme.wrapped_label("", "secondary")
        texts.addWidget(self._detail)
        layout.addLayout(texts, 1)

        self._close = theme.CloseButton()
        self._close.clicked.connect(self.hide)
        layout.addWidget(self._close, 0, Qt.AlignTop)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        theme.apply_elevation(self, 2)
        theme.signals().changed.connect(self._restyle)
        self._level = "success"

    def _restyle(self) -> None:
        """按当前主题和级别重新配色 / Re-colour for the active theme and level."""
        p = theme.palette()
        family = {"success": "success", "warning": "warning", "error": "error"}.get(self._level)
        semantic = p.semantic(family) if family else None
        background = semantic.subtle if semantic else p.surface_elevated
        border = semantic.border if semantic else p.separator_subtle
        self.setStyleSheet(
            "QFrame#Toast {{ background: {}; border: 1px solid {}; border-radius: {}px; }}".format(
                background, border, tokens.RADIUS_MEDIUM))
        theme.apply_elevation(self, 2)

    def show_message(self, title: str, message: str, level: str = "success") -> None:
        """
        摆一条消息 / Show one message for a level-appropriate while.

        参数 / Parameters:
            title (str): 一句话说明发生了什么。
            message (str): 细节，出错时要写清影响和下一步。
            level (str): ``success`` / ``warning`` / ``error``。
        """
        self._level = level
        self._restyle()
        theme.set_wrapped_text(self._title, title)
        theme.set_wrapped_text(self._detail, message)
        self.setAccessibleName("{}：{}".format(title, message))
        self.setFixedHeight(self.sizeHint().height())
        self.show()
        self.raise_()
        timeout = STATUS_TIMEOUT.get(level, 6000)
        self._timer.stop()
        if timeout:
            self._timer.start(timeout)


class _PageState(QWidget):
    """
    列表页的非正常状态 / What a list page shows when it has no rows.

    Loading、Empty 和 Error 共用这一块：位置固定，切换时内容不跳。
    Loading 时那条进度条能算比例就走确定值——规范 5.1 说可计算完成比例时
    不该用不确定的转圈。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y,
                                  tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y)
        layout.setSpacing(tokens.GAP_CONTROL)
        layout.addStretch(1)

        self._title = theme.wrapped_label("", "sectionTitle")
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)

        self._detail = theme.wrapped_label("", "secondary")
        self._detail.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._detail)

        self._progress = QProgressBar()
        self._progress.setFixedWidth(280)
        self._progress.setTextVisible(False)
        self._progress.hide()
        bar_row = QHBoxLayout()
        bar_row.addStretch(1)
        bar_row.addWidget(self._progress)
        bar_row.addStretch(1)
        layout.addLayout(bar_row)

        self._action = QPushButton()
        self._action.hide()
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(self._action)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        layout.addStretch(1)

        self._handler: Optional[Callable[[], None]] = None
        self._action.clicked.connect(self._fire)

    def _fire(self) -> None:
        """跑那个「下一步」/ Run the one suggested next step."""
        if self._handler is not None:
            self._handler()

    def show_state(self, title: str, detail: str, action: str = "",
                   handler: Optional[Callable[[], None]] = None) -> None:
        """
        换一种状态 / Switch to another state.

        参数 / Parameters:
            title (str): 现在是什么情况。
            detail (str): 为什么，以及影响到什么。
            action (str): 一个最相关的下一步；空字符串表示没有。
            handler (Optional[Callable]): 点了那个按钮跑什么。
        """
        theme.set_wrapped_text(self._title, title)
        theme.set_wrapped_text(self._detail, detail)
        self._progress.hide()
        self._handler = handler
        self._action.setText(action)
        self._action.setVisible(bool(action))
        self.setAccessibleName("{}。{}".format(title, detail))

    def show_progress(self, done: int, total: int) -> None:
        """
        走一格进度 / Advance the determinate progress bar.

        参数 / Parameters:
            done (int): 已经解析了几个。
            total (int): 一共几个；还不知道时传 0，进度条转圈。
        """
        self._progress.show()
        if total <= 0:
            self._progress.setRange(0, 0)
            theme.set_wrapped_text(self._detail, "正在查找 option 包里的 XML。")
            return
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        theme.set_wrapped_text(self._detail, "已解析 {} / {} 个文件。".format(done, total))


class _ListPage(QWidget):
    """
    一页列表 / One list page, with its states.

    列表和状态页压在同一个 ``QStackedWidget`` 里，切换时位置不变——
    规范 06 要求状态切换保持内容位置尽量稳定。
    """

    def __init__(self, header: QHBoxLayout, view: QListView,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.GAP_CONTROL)
        layout.addLayout(header)

        self.view = view
        self.state = _PageState()
        self.stack = QStackedWidget()
        self.stack.addWidget(view)
        self.stack.addWidget(self.state)
        layout.addWidget(self.stack, 1)

    def show_rows(self) -> None:
        """摆列表 / Show the rows."""
        self.stack.setCurrentWidget(self.view)

    def show_state(self, *args, **kwargs) -> _PageState:
        """摆状态 / Show a state instead of the rows."""
        self.stack.setCurrentWidget(self.state)
        self.state.show_state(*args, **kwargs)
        return self.state


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
        self._scanning = False
        self._scan_signals = _ScanSignals()
        self._scan_signals.done.connect(self._on_scanned)
        self._scan_signals.progress.connect(self._on_progress)

        self._build()
        self._ready = True
        imagecache.instance().changed.connect(self._repaint_lists)
        theme.signals().changed.connect(self._repaint_lists)
        theme.apply_mica(self)
        self.reload()

    # -- 装配 -------------------------------------------------------------

    def _build(self) -> None:
        """把界面搭出来 / Assemble the window."""
        surface = QWidget()
        surface.setObjectName("Surface")
        self.setCentralWidget(surface)

        root_layout = QVBoxLayout(surface)
        root_layout.setContentsMargins(tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y,
                                       tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y)
        root_layout.setSpacing(tokens.GAP_GROUP)

        root_layout.addLayout(self._build_header())
        root_layout.addLayout(self._build_filters())

        columns = QHBoxLayout()
        columns.setSpacing(tokens.GAP_GROUP)

        self._nav = QListWidget()
        self._nav.setObjectName("Nav")
        self._nav.setFixedWidth(148)
        self._nav.setFrameShape(QFrame.NoFrame)
        self._nav.setAccessibleName("页面")
        for text in ("歌曲", "角色", "排查"):
            self._nav.addItem(QListWidgetItem(text))
        self._nav.setCurrentRow(0)
        self._nav.currentRowChanged.connect(self._on_page_changed)
        columns.addWidget(self._nav)
        # 导航和内容之间一条竖线就够，不必给导航整块底色
        columns.addWidget(theme.vertical_separator())

        self._pages = QStackedWidget()
        self._song_page = self._build_song_page()
        self._character_page = self._build_character_page()
        self._issue_page = self._build_issue_page()
        for page in (self._song_page, self._character_page, self._issue_page):
            self._pages.addWidget(page)
        columns.addWidget(self._pages, 1)

        self._inspector = QStackedWidget()
        self._inspector.setFixedWidth(468)
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
        row.setSpacing(tokens.GAP_CONTROL)
        row.addWidget(theme.label("CHUNITHM Option Manager", "pageTitle"))
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
        row.setSpacing(tokens.GAP_CONTROL)

        self._root_box = QLineEdit(self._root)
        self._root_box.setReadOnly(True)
        self._root_box.setAccessibleName("option 根目录")
        self._root_label = theme.label("option 根目录", "body")
        row.addLayout(_field_column(self._root_label, self._root_box), 3)

        self._search = QLineEdit()
        self._search.setPlaceholderText("标题 / ID / 曲师 / 角色名")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("搜索")
        self._search.textChanged.connect(self._apply_filters)
        self._search_label = theme.label("搜索", "body")
        row.addLayout(_field_column(self._search_label, self._search), 2)

        self._difficulty = QComboBox()
        self._difficulty.addItems(DIFFICULTY_FILTERS)
        self._difficulty.setAccessibleName("难度")
        self._difficulty.currentIndexChanged.connect(self._apply_filters)
        self._difficulty_label = theme.label("难度", "body")
        row.addLayout(_field_column(self._difficulty_label, self._difficulty), 1)
        return row

    def _build_song_page(self) -> _ListPage:
        """歌曲页 / The songs page."""
        header = QHBoxLayout()
        header.setSpacing(tokens.GAP_CONTROL)
        self._song_count = theme.label("", "secondary")
        header.addWidget(self._song_count)
        header.addStretch(1)
        self._song_sort = _sort_box(SONG_SORTS, self._apply_filters, "歌曲排序")
        header.addWidget(self._song_sort)

        self._song_model = ObjectListModel()
        self._song_view = _list_view(self._song_model, SongDelegate(self), "歌曲")
        self._song_view.clicked.connect(self._on_song_clicked)
        return _ListPage(header, self._song_view)

    def _build_character_page(self) -> _ListPage:
        """角色页 / The characters page."""
        header = QHBoxLayout()
        header.setSpacing(tokens.GAP_CONTROL)
        self._character_count = theme.label("", "secondary")
        header.addWidget(self._character_count)
        header.addStretch(1)
        self._character_sort = _sort_box(CHARACTER_SORTS, self._apply_filters, "角色排序")
        header.addWidget(self._character_sort)
        # 工具栏里的独立动作不因为高频就变成 Primary（规范 4.2）；
        # 这一屏唯一的 Primary 在右侧检查器上
        self._add_button = QPushButton("新增角色")
        self._add_button.clicked.connect(self._add_character)
        header.addWidget(self._add_button)

        self._character_model = ObjectListModel()
        self._character_view = _list_view(self._character_model, CharacterDelegate(self), "角色")
        self._character_view.setViewMode(QListView.IconMode)
        self._character_view.setResizeMode(QListView.Adjust)
        self._character_view.setWrapping(True)
        self._character_view.setSpacing(0)
        self._character_view.clicked.connect(self._on_character_clicked)
        return _ListPage(header, self._character_view)

    def _build_issue_page(self) -> _ListPage:
        """排查页 / The issues page."""
        header = QHBoxLayout()
        header.setSpacing(tokens.GAP_CONTROL)
        self._issue_count = theme.label("", "secondary")
        header.addWidget(self._issue_count)
        header.addStretch(1)

        self._issue_model = ObjectListModel()
        self._issue_view = _list_view(self._issue_model, IssueDelegate(self), "排查项")
        self._issue_view.setSelectionMode(QListView.NoSelection)
        return _ListPage(header, self._issue_view)

    # -- 扫描 -------------------------------------------------------------

    def reload(self) -> None:
        """重新扫一遍 / Rescan the option tree."""
        if not os.path.isdir(self._root):
            self._show_scan_error("option 目录不在了", self._root)
            return
        self._set_busy(True)
        for page in (self._song_page, self._character_page, self._issue_page):
            page.show_state("正在扫描", "正在查找 option 包里的 XML。")
        imagecache.instance().clear()
        QThreadPool.globalInstance().start(_ScanTask(self._root, self._scan_signals))

    def _on_progress(self, done: int, total: int) -> None:
        """收到一格进度 / One progress tick arrived."""
        if not self._scanning:
            return
        for page in (self._song_page, self._character_page, self._issue_page):
            page.state.show_progress(done, total)

    def _on_scanned(self, catalog: Optional[OptionCatalog], error: str) -> None:
        """收下扫描结果 / Take the scan result."""
        self._set_busy(False)
        if catalog is None:
            self._show_scan_error("扫描失败", error or "未知错误")
            return

        self._catalog = catalog
        self._apply_filters()
        self._issue_model.replace(catalog.issues)
        self._issue_count.setText("排查项 {} 条".format(len(catalog.issues)))
        if catalog.issues:
            self._issue_page.show_rows()
        else:
            self._issue_page.show_state(
                "没有排查项", "这个 option 目录里没有发现开着却缺文件、难度对不齐或配不到贴图的东西。")
        self._notify(
            "扫描完成",
            "歌曲 {} 首，角色 {} 个，排查项 {} 条。".format(
                len(catalog.songs), len(catalog.characters), len(catalog.issues)),
            "success")

    def _show_scan_error(self, title: str, detail: str) -> None:
        """
        扫描失败 / The scan did not produce a catalog.

        三页一起进 Error 状态，并且各给一个「重新扫描」——错误提示要说明发生
        什么、影响什么、怎么恢复，只弹一条状态条是不够的。
        """
        self._set_busy(False)
        for page in (self._song_page, self._character_page, self._issue_page):
            page.show_state(title, "{}\n列表暂时是空的。".format(detail), "重新扫描", self.reload)
        self._notify(title, detail, "error")

    def _set_busy(self, busy: bool) -> None:
        """
        扫描时把整组降级 / Degrade the whole unit while scanning.

        规范 06 要求「整个语义单元一起降级」，2.1 又明确禁止对整行容器统一设
        Opacity——所以是逐个控件和标签走各自的 Disabled Token，不是蒙一层半透明。
        """
        self._scanning = busy
        for widget in (self._search, self._difficulty, self._song_sort,
                       self._character_sort, self._song_view, self._character_view,
                       self._reload_button, self._add_button, self._root_box,
                       self._root_label, self._search_label, self._difficulty_label,
                       self._song_count, self._character_count, self._issue_count):
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
        filtering = bool(query) or wanted != "全部"

        songs = [song for song in self._catalog.songs if song.matches(query)]
        if wanted == "文件缺失":
            songs = [song for song in songs if song.has_missing_enabled_file]
        elif wanted != "全部":
            songs = [song for song in songs if song.has_enabled(wanted)]
        songs = _sort_songs(songs, self._song_sort.currentData())[:MAX_ROWS]
        self._song_model.replace(songs)
        self._song_count.setText("歌曲 {} / {} 首".format(len(songs), len(self._catalog.songs)))
        self._settle(self._song_page, len(songs), len(self._catalog.songs), filtering,
                     "歌曲", "这个 option 目录里没有找到 Music.xml。")

        characters = [item for item in self._catalog.characters if item.matches(query)]
        characters = _sort_characters(characters, self._character_sort.currentData())[:MAX_ROWS]
        self._character_model.replace(characters)
        self._character_count.setText("角色 {} / {} 个".format(
            len(characters), len(self._catalog.characters)))
        self._settle(self._character_page, len(characters), len(self._catalog.characters),
                     bool(query), "角色", "这个 option 目录里没有找到 Chara.xml。")

    def _settle(self, page: _ListPage, shown: int, total: int, filtering: bool,
                noun: str, nothing_at_all: str) -> None:
        """
        决定这一页摆列表还是摆空状态 / Rows or an empty state.

        「筛没了」和「本来就没有」是两回事，下一步也不一样：前者该清筛选，
        后者该换个目录。
        """
        if shown:
            page.show_rows()
        elif total and filtering:
            page.show_state("没有匹配的{}".format(noun),
                            "搜索和筛选把 {} 条都排除了。".format(total),
                            "清空搜索和筛选", self._clear_filters)
        else:
            page.show_state("没有{}".format(noun), nothing_at_all,
                            "切换 option 目录", self._pick_root)

    def _clear_filters(self) -> None:
        """把搜索和筛选收回默认 / Reset search and filters."""
        self._search.clear()
        self._difficulty.setCurrentIndex(0)
        self._apply_filters()

    def _repaint_lists(self) -> None:
        """有新贴图解好了，或者换了主题，重画一次 / Repaint after textures or theme change."""
        self._song_view.viewport().update()
        self._character_view.viewport().update()
        self._issue_view.viewport().update()

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
            max(tokens.PADDING_PAGE_X,
                surface.width() - self._status.width() - tokens.PADDING_PAGE_X),
            max(tokens.PADDING_PAGE_Y,
                surface.height() - self._status.height() - tokens.PADDING_PAGE_Y))

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

        默认按钮是「取消」：手滑连按回车不该删掉东西。按钮文字写的是具体动作
        （「移入回收区」）而不是「确定」，正文写清对象、范围和后果。
        """
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QMessageBox.Warning)
        move = box.addButton("移入回收区", QMessageBox.AcceptRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        theme.apply_titlebar(box)
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
        """
        新增角色 / Create a character.

        建完之后把新角色选中摆进检查器——规范 5.1 要求有结果位置的任务
        在原任务区域留一个结果入口，不能只弹一句「建好了」。
        """
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
        self._reload_and_reselect(str(new_id), self._reselect_new_character)

    def _reload_and_reselect(self, key: str, reselect: Callable[[str], None]) -> None:
        """
        存完重新扫描，并把刚才那条重新选中 / Rescan, then re-select what was edited.

        保存之后目录里的东西可能变了（比如谱面文件的存在与否），所以不复用内存里
        那份旧对象；重新扫完按 XML 路径找回来。
        """
        def once(catalog: Optional[OptionCatalog], error: str) -> None:
            self._scan_signals.done.disconnect(once)
            self._on_scanned(catalog, error)
            if catalog is not None:
                reselect(key)

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

    def _reselect_new_character(self, character_id: str) -> None:
        """把刚建的角色摆进检查器 / Open the character that was just created."""
        for character in self._catalog.characters:
            if str(character.character_id) == character_id:
                self._nav.setCurrentRow(1)
                self._character_inspector.show_character(character)
                self._inspector.setCurrentWidget(self._character_inspector)
                self._inspector.show()
                return


def _field_column(label: QLabel, widget: QWidget) -> QVBoxLayout:
    """
    一个带标签的输入框 / A labelled input.

    标签用 ``body`` 加 ``text.primary``：规范 3.4 禁止把正常的字段标题
    渲染成小号灰字。
    """
    column = QVBoxLayout()
    column.setSpacing(tokens.GAP_RELATED)
    column.addWidget(label)
    column.addWidget(widget)
    if hasattr(label, "setBuddy"):
        label.setBuddy(widget)
    return column


def _sort_box(options: Sequence, on_change, name: str) -> QComboBox:
    """排序下拉 / A sort combo box."""
    box = QComboBox()
    for text, key in options:
        box.addItem(text, key)
    box.setMinimumWidth(150)
    box.setAccessibleName(name)
    box.currentIndexChanged.connect(on_change)
    return box


def _list_view(model, delegate, name: str) -> QListView:
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
    view.setAccessibleName(name)
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
