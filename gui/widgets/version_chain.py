"""版本链组件：横向展示一次设计的迭代版本（v1 → v2 → …），节点可点击回载。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from gui import theme
from gui.services.runs_repository import RunInfo

THUMB = 64


class _VersionNode(QFrame):
    clicked = Signal(object)  # RunInfo

    def __init__(self, info: RunInfo, label: str, current: bool, parent=None):
        super().__init__(parent)
        self._info = info
        self.setCursor(Qt.PointingHandCursor)
        # 当前版本用珊瑚橘描边 + 极浅暖底；历史版本用发丝线，不抢视线
        if current:
            border, bg, width = theme.CORAL, theme.CORAL_TINT, 2
        else:
            border, bg, width = "rgba(139, 111, 92, 40)", theme.CARD_BG, 1
        self.setStyleSheet(
            f"_VersionNode {{ background: {bg}; border: {width}px solid {border};"
            f" border-radius: 10px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(2)

        thumb = QLabel()
        thumb.setFixedSize(THUMB, THUMB)
        thumb.setAlignment(Qt.AlignCenter)
        pix_src = info.sim_input or info.preview
        if pix_src is not None and pix_src.exists():
            pix = QPixmap(str(pix_src)).scaled(
                THUMB, THUMB, Qt.KeepAspectRatio, Qt.FastTransformation)
            thumb.setPixmap(pix)
        else:
            thumb.setText("--")
        layout.addWidget(thumb, 0, Qt.AlignCenter)

        cap = QLabel(label)
        cap.setAlignment(Qt.AlignCenter)
        color = theme.CORAL if current else theme.WARM_BROWN
        weight = "bold" if current else "normal"
        cap.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: {weight};")
        layout.addWidget(cap)

        tip = info.prompt if len(info.prompt) < 120 else info.prompt[:120] + "…"
        self.setToolTip(f"{label}\n{tip}\n{info.run_dir}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._info)
        super().mousePressEvent(event)


class VersionChain(QWidget):
    """rebuild(chain, current_dir) 重建；点击节点发 versionSelected。"""

    versionSelected = Signal(object)  # RunInfo

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._row = QHBoxLayout(self._container)
        self._row.setContentsMargins(4, 2, 4, 2)
        self._row.setSpacing(4)
        self._row.addStretch(1)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)
        self.setFixedHeight(THUMB + 62)
        self.hide()  # 无链时不占位

    def clear(self):
        while self._row.count() > 1:
            item = self._row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.hide()

    def rebuild(self, chain: list[RunInfo], current_dir):
        self.clear()
        if len(chain) <= 1:
            return
        current_key = str(current_dir)
        for i, info in enumerate(chain):
            if i > 0:
                arrow = QLabel("→")
                arrow.setStyleSheet(
                    f"color: rgba(139, 111, 92, 130); font-size: 18px;")
                self._row.insertWidget(self._row.count() - 1, arrow)
            node = _VersionNode(
                info, f"v{i + 1}", str(info.run_dir) == current_key, self._container)
            node.clicked.connect(self.versionSelected)
            self._row.insertWidget(self._row.count() - 1, node)
        self.show()
