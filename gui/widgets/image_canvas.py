"""可缩放图像画布与图像展示面板。

ImageCanvas : QGraphicsView，滚轮缩放 / 拖拽平移，40x40 色码图用最近邻放大保持像素锐利。
ImagePanel  : 卡片容器（标题 + 工具按钮 + 画布），双击全屏查看，支持导出源文件 / 打开目录。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QPainter
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QVBoxLayout,
)
from qfluentwidgets import FluentIcon as FIF, InfoBar, TransparentToolButton

from gui import theme
from gui.widgets.warm_card import SectionTitle, WarmCard


class ImageCanvas(QGraphicsView):
    """滚轮缩放 + 拖拽平移；load() 后自动适应窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: QGraphicsPixmapItem | None = None
        self._source: Path | None = None
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setFrameShape(QGraphicsView.NoFrame)
        # 凹陷暖底 + 无描边：比虚线框更克制，突出图像本身
        self.setStyleSheet(
            f"QGraphicsView {{ background: {theme.WELL_BG}; border: none;"
            f" border-radius: 10px; }}"
        )

    @property
    def source(self) -> Path | None:
        return self._source

    def load(self, path: Path | None) -> bool:
        self._scene.clear()
        self._item = None
        self._source = None
        if path is None or not Path(path).exists():
            return False
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return False
        self._item = self._scene.addPixmap(pixmap)
        # 小尺寸色码图放大时保持像素边缘锐利
        self._item.setTransformationMode(Qt.FastTransformation)
        self._scene.setSceneRect(self._item.boundingRect())
        self._source = Path(path)
        self.fit()
        return True

    def fit(self):
        if self._item is not None:
            self.fitInView(self._item, Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        if self._item is None:
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 未手动缩放前保持自适应
        if self._item is not None and self.transform().m11() <= 1.0:
            self.fit()


class _FullViewDialog(QDialog):
    """双击弹出的全屏查看对话框。"""

    def __init__(self, title: str, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 900)
        layout = QVBoxLayout(self)
        canvas = ImageCanvas(self)
        canvas.load(path)
        layout.addWidget(canvas)


class ImagePanel(WarmCard):
    """标题栏 + 工具按钮 + 画布 的成品面板。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        self._label = SectionTitle(title, self)
        header.addWidget(self._label)
        header.addStretch(1)

        self._btn_fit = TransparentToolButton(FIF.FIT_PAGE, self)
        self._btn_fit.setToolTip("适应窗口")
        self._btn_fit.clicked.connect(lambda: self.canvas.fit())
        self._btn_save = TransparentToolButton(FIF.SAVE_AS, self)
        self._btn_save.setToolTip("导出源文件")
        self._btn_save.clicked.connect(self._export)
        self._btn_folder = TransparentToolButton(FIF.FOLDER, self)
        self._btn_folder.setToolTip("打开所在目录")
        self._btn_folder.clicked.connect(self._open_folder)
        for b in (self._btn_fit, self._btn_save, self._btn_folder):
            header.addWidget(b)
        root.addLayout(header)

        self.canvas = ImageCanvas(self)
        self.canvas.setMinimumSize(220, 220)
        root.addWidget(self.canvas, 1)

        self._hint = QLabel("等待生成…")
        self._hint.setObjectName("hintText")
        self._hint.setAlignment(Qt.AlignCenter)
        root.addWidget(self._hint)

    # ---------- API ----------

    def load(self, path: Path | None):
        ok = self.canvas.load(path)
        if ok:
            self._hint.setText(str(Path(path).name))
        else:
            self._hint.setText("暂无图像")

    def clear(self):
        self.canvas.load(None)
        self._hint.setText("等待生成…")

    # ---------- 交互 ----------

    def mouseDoubleClickEvent(self, event):
        if self.canvas.source is not None:
            _FullViewDialog(self._title, self.canvas.source, self).exec()
        super().mouseDoubleClickEvent(event)

    def _export(self):
        src = self.canvas.source
        if src is None:
            InfoBar.warning("无内容", "当前没有可导出的图像", parent=self.window())
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "导出源文件", src.name, f"图像 (*{src.suffix})")
        if target:
            shutil.copyfile(src, target)
            InfoBar.success("已导出", target, parent=self.window())

    def _open_folder(self):
        src = self.canvas.source
        if src is not None:
            # 跨平台打开目录（Windows 本地 / Linux 服务器），不用 os.startfile
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(src.parent)))
