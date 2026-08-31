# -*- coding: utf-8 -*-
"""
单图快速生成三张贴图 / One image, three character textures.

一张源图，三个格子（全身 / 半身 / 大头）各自拖拽和缩放，确认后按各自的取景
生成 ``big.dds`` / ``small.dds`` / ``thumb.dds``。

**预览和真正的裁剪必须用同一套算法**，所以取景框一律从
:func:`core.dds.crop_box` 算，这个窗口不自己写一份——写两份的下场是拖出来的
位置和生成出来的贴图对不上，而这种偏差要生成一次才看得见。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core import dds
from core.repository import CropSettings
from ui import theme, tokens

#: 三个格子：``(键, 标签, 文件名, 输出边长, 默认取景)``。
#: 默认取景是实测出来的：半身要往上抬一点才不会切到下巴，大头要抬更多。
PANES: Tuple[Tuple[str, str, str, int, CropSettings], ...] = (
    ("big", "全身", "big.dds", 1080, CropSettings(1.0, 0.0, 0.0)),
    ("small", "半身", "small.dds", 512, CropSettings(1.45, 0.0, -28.0)),
    ("thumb", "大头", "thumb.dds", 128, CropSettings(3.0, 0.0, -62.0)),
)

#: 每格预览的边长。
PREVIEW_SIZE = 380


class CropPane(QWidget):
    """
    一个可拖拽缩放的取景格 / One draggable, zoomable crop pane.

    拖拽移动取景框，滚轮缩放。底下压着模板贴图，上面的源图透明度可调，
    用来对位。
    """

    def __init__(self, crop: CropSettings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.crop = crop
        self._source: Optional[QPixmap] = None
        self._template: Optional[QPixmap] = None
        self._opacity = 0.67
        self._last_point: Optional[QPoint] = None
        self.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.setCursor(Qt.OpenHandCursor)

    def set_source(self, pixmap: Optional[QPixmap]) -> None:
        """换一张源图 / Swap the source image."""
        self._source = pixmap
        self.update()

    def set_template(self, pixmap: Optional[QPixmap]) -> None:
        """垫在底下的模板贴图 / The reference texture underneath."""
        self._template = pixmap
        self.update()

    def set_opacity(self, value: float) -> None:
        """源图的不透明度 / How solid the source image is drawn."""
        self._opacity = max(0.2, min(1.0, value))
        self.update()

    def _box(self) -> Tuple[float, float, float]:
        """当前取景框 / The current crop box, in source pixels."""
        if self._source is None:
            return 0.0, 0.0, 1.0
        return dds.crop_box(
            self._source.width(), self._source.height(),
            self.crop.zoom, self.crop.offset_x, self.crop.offset_y)

    def paintEvent(self, event) -> None:  # noqa: D102 - Qt 的绘制回调
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        area = QRectF(0, 0, self.width(), self.height())

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tokens.IMAGE_BACKDROP))
        painter.drawRect(area)

        if self._template is not None and not self._template.isNull():
            painter.drawPixmap(area, self._template, QRectF(self._template.rect()))

        if self._source is not None and not self._source.isNull():
            left, top, size = self._box()
            painter.setOpacity(self._opacity)
            painter.drawPixmap(area, self._source, QRectF(left, top, size, size))
            painter.setOpacity(1.0)
        else:
            painter.setPen(QPen(QColor(theme.palette().text_tertiary)))
            painter.setFont(theme.font("body"))
            painter.drawText(area, Qt.AlignCenter, "还没有选图")

        painter.setPen(QPen(QColor(theme.palette().separator_subtle)))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(area.adjusted(0.5, 0.5, -0.5, -0.5))

        badge = QRectF(self.width() - 62, 8, 54, 20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(badge, tokens.RADIUS_SMALL, tokens.RADIUS_SMALL)
        painter.setPen(QPen(QColor(tokens.GAME_CARD["name_bar"])))
        painter.setFont(theme.font("caption"))
        painter.drawText(badge, Qt.AlignCenter, "{:.2f}x".format(self.crop.zoom))

    def mousePressEvent(self, event) -> None:  # noqa: D102
        if self._source is None:
            return
        self._last_point = event.position().toPoint()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: D102
        if self._source is None or self._last_point is None:
            return
        point = event.position().toPoint()
        delta = point - self._last_point
        self._last_point = point
        self._move(delta.x(), delta.y())

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102
        self._last_point = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event) -> None:  # noqa: D102
        if self._source is None:
            return
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self.crop.zoom = max(dds.MIN_ZOOM, min(dds.MAX_ZOOM, self.crop.zoom * factor))
        self.update()

    def _move(self, delta_x: float, delta_y: float) -> None:
        """
        拖着走 / Drag the crop box.

        鼠标往右拖，取景框要往**左**移（看到的内容跟着手走）。位移要除以当前
        缩放比，不然放大之后拖一格会飞出去半张图。
        """
        if self._source is None:
            return
        left, top, size = self._box()
        scale = self.width() / size
        max_x = max(0.0, self._source.width() - size)
        max_y = max(0.0, self._source.height() - size)

        new_left = left - delta_x / scale
        new_top = top - delta_y / scale
        self.crop.offset_x = 0.0 if max_x <= 0 else max(
            -100.0, min(100.0, (new_left / max_x) * 200.0 - 100.0))
        self.crop.offset_y = 0.0 if max_y <= 0 else max(
            -100.0, min(100.0, (new_top / max_y) * 200.0 - 100.0))
        self.update()


class CropDialog(QDialog):
    """
    「单图快速生成」窗口 / The quick-crop window.

    确认后并不落盘，只把源图路径和三个取景带回去——真正生成 DDS 是在
    :func:`core.repository.add_character` 里，和写 XML 在同一个事务里，
    半路失败能一起回滚。
    """

    def __init__(
        self,
        crops: Dict[str, CropSettings],
        source_path: str = "",
        template_dir: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("单图快速生成角色贴图")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)

        # 在副本上改，取消就整个丢掉，不会把调好的原设置弄脏
        self._crops = {key: CropSettings(item.zoom, item.offset_x, item.offset_y)
                       for key, item in crops.items()}
        self._source_path = source_path
        self._panes: Dict[str, CropPane] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y,
                                  tokens.PADDING_PAGE_X, tokens.PADDING_PAGE_Y)
        layout.setSpacing(tokens.GAP_GROUP)

        layout.addWidget(theme.wrapped_label(
            "选一张图之后，在三个格子里分别拖拽移动、滚轮缩放。"
            "底下垫着的是模板贴图，用来对位；上面那张的透明度可以调。", "secondary"))

        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(tokens.GAP_CONTROL)
        opacity_row.addWidget(theme.label("覆盖图透明度", "body"))
        self._opacity = QSlider(Qt.Horizontal)
        self._opacity.setRange(20, 100)
        self._opacity.setValue(67)
        self._opacity.setAccessibleName("覆盖图透明度")
        self._opacity.valueChanged.connect(self._apply_opacity)
        opacity_row.addWidget(self._opacity, 1)
        layout.addLayout(opacity_row)

        panes_row = QHBoxLayout()
        panes_row.setSpacing(tokens.GAP_GROUP)
        for key, label, file_name, size, default in PANES:
            self._crops.setdefault(key, CropSettings(default.zoom, default.offset_x, default.offset_y))
            column = QVBoxLayout()
            column.setSpacing(tokens.GAP_RELATED)
            pane = CropPane(self._crops[key])
            self._panes[key] = pane
            column.addWidget(pane, 0, Qt.AlignHCenter)

            caption = theme.label(label, "sectionTitle")
            caption.setAlignment(Qt.AlignHCenter)
            column.addWidget(caption)
            pane.setAccessibleName("{} 取景".format(label))

            column.addWidget(theme.label("{} · {}x{}".format(file_name, size, size), "caption"),
                             0, Qt.AlignHCenter)
            panes_row.addLayout(column)
        layout.addLayout(panes_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.GAP_CONTROL)
        upload = QPushButton("选择图片…")
        upload.clicked.connect(self._pick_image)
        buttons.addWidget(upload)
        self._file_label = theme.label("", "caption")
        buttons.addWidget(self._file_label, 1)

        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self._confirm = QPushButton("生成并回填")
        self._confirm.setObjectName("Primary")
        self._confirm.setDefault(True)
        self._confirm.clicked.connect(self.accept)
        buttons.addWidget(self._confirm)
        layout.addLayout(buttons)

        self._load_template(template_dir)
        self._load_source(source_path)
        self._apply_opacity(self._opacity.value())
        theme.apply_titlebar(self)

    def _load_template(self, template_dir: Optional[Path]) -> None:
        """把模板贴图垫到三个格子底下 / Put the reference texture under each pane."""
        if not template_dir:
            return
        from core import ddspreview

        for key, _label, file_name, _size, _default in PANES:
            preview = ddspreview.preview_path(Path(template_dir) / file_name, PREVIEW_SIZE)
            if preview:
                self._panes[key].set_template(QPixmap(preview))

    def _load_source(self, path: str) -> None:
        """读源图 / Load the source image into every pane."""
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        self._source_path = path
        self._file_label.setText(Path(path).name)
        for pane in self._panes.values():
            pane.set_source(pixmap)

    def _pick_image(self) -> None:
        """选一张源图 / Ask for the source image."""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择角色立绘", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._file_label.setText("这张图读不了，换一张")
            return
        self._load_source(path)

    def _apply_opacity(self, value: int) -> None:
        """透明度滑杆 / Push the slider value into every pane."""
        for pane in self._panes.values():
            pane.set_opacity(value / 100.0)

    def result_data(self) -> Tuple[str, Dict[str, CropSettings]]:
        """
        拿走结果 / The chosen image and the three crops.

        返回 / Returns:
            Tuple[str, Dict[str, CropSettings]]: ``(源图路径, 取景)``；
            没选图时路径是空串。
        """
        return self._source_path, self._crops
