# -*- coding: utf-8 -*-
"""
贴图的异步加载与内存缓存 / Loading textures off the UI thread.

歌曲页一屏能出现十几张曲绘，角色页几十张立绘，全是要解码的 DDS。在界面线程
上解码的话，滚动会一格一格地卡。这里的做法是：

* 画的时候只问 :meth:`ImageCache.pixmap`，有就画，没有就画占位；
* 没有的那些丢进线程池，解码完发信号，视图重画一次。

**解码线程只碰 QImage，QPixmap 一律在界面线程构造**——QPixmap 不是线程安全的，
在工作线程里 new 一个出来是会崩的那种错。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional, Set, Tuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

from core import ddspreview

#: 内存里最多留多少张。一张 256px 的 RGBA 约 256KB，600 张约 150MB——
#: 再多就该让系统去换页了，不如让它自然淘汰。
MAX_CACHED = 600


class _Signals(QObject):
    """工作线程往回发的信号 / What a worker sends back."""

    done = Signal(str, int, object)


class _DecodeTask(QRunnable):
    """把一张 DDS 解成 QImage / Decode one texture into a QImage."""

    def __init__(self, path: str, size: int, signals: _Signals) -> None:
        super().__init__()
        self._path = path
        self._size = size
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        """解码 / Decode; 失败就回一个 ``None``，让调用方记下「这张没有」。"""
        image: Optional[QImage] = None
        try:
            preview = ddspreview.preview_path(self._path, self._size)
            if preview:
                loaded = QImage(preview)
                if not loaded.isNull():
                    image = loaded
        except Exception:
            image = None
        self._signals.done.emit(self._path, self._size, image)


class ImageCache(QObject):
    """
    一份进程内的图片缓存 / One process-wide texture cache.

    信号 / Signals:
        changed: 有新图解好了，视图该重画。刻意不带参数——视图只需要知道
            「有东西变了」，逐张精确重绘省不下什么，反而容易漏。
    """

    changed = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cache: "OrderedDict[Tuple[str, int], Optional[QPixmap]]" = OrderedDict()
        self._pending: Set[Tuple[str, int]] = set()
        self._signals = _Signals()
        self._signals.done.connect(self._store)
        self._pool = QThreadPool(self)
        # 解码是 CPU 活，但界面线程也要吃 CPU；留一个核给它，滚动才不会顿。
        self._pool.setMaxThreadCount(max(1, QThreadPool.globalInstance().maxThreadCount() - 1))

    def pixmap(self, path: str, size: int) -> Optional[QPixmap]:
        """
        取一张图 / Get a texture, scheduling the decode if it is not ready.

        参数 / Parameters:
            path (str): ``.dds`` 或普通图片的路径。
            size (int): 长边上限。

        返回 / Returns:
            Optional[QPixmap]: 解好了就是图；还没好、或者这张根本解不开，
            都是 ``None``——调用方画占位就行，不必区分。
        """
        if not path:
            return None
        key = (path, size)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if key not in self._pending:
            self._pending.add(key)
            self._pool.start(_DecodeTask(path, size, self._signals))
        return None

    def _store(self, path: str, size: int, image: Optional[QImage]) -> None:
        """收下解码结果 / Take the decoded image, on the UI thread."""
        key = (path, size)
        self._pending.discard(key)
        # 解不开的也要记进来（记成 None），否则每次重画都会再排一次队，
        # 一张坏图能把线程池占满。
        self._cache[key] = QPixmap.fromImage(image) if image is not None else None
        self._cache.move_to_end(key)
        while len(self._cache) > MAX_CACHED:
            self._cache.popitem(last=False)
        self.changed.emit()

    def clear(self) -> None:
        """清空 / Drop everything; 重新扫描目录之后调用。"""
        self._cache.clear()


_INSTANCE: Optional[ImageCache] = None


def instance() -> ImageCache:
    """全局唯一的那份缓存 / The one cache everybody shares."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ImageCache()
    return _INSTANCE
