"""暖色卡片与区块标题。

WarmCard    : 覆写 CardWidget 的绘制——纯白填充 + 暖棕发丝描边 + 大圆角，
              配合 theme.apply_card_shadow 的柔和暖色投影，替代 Fluent
              默认的「半透明底 + 系统灰硬边」（那是 Windows 面板观感的来源）。
SectionTitle: 珊瑚橘小竖条 + 标题文字，用极小面积的强调色点睛。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
from qfluentwidgets import CardWidget

from gui import theme


class WarmCard(CardWidget):
    """纯白卡片：发丝描边 + 可选柔和投影。"""

    def __init__(self, parent=None, *, shadow=True, radius=theme.CARD_RADIUS,
                 hover_accent=False):
        super().__init__(parent)
        self.setBorderRadius(radius)
        self._hairline = theme.HAIRLINE
        self._hover_accent = hover_accent
        if shadow:
            theme.apply_card_shadow(self)

    # 关闭 Fluent 的 hover 变色，保持纯白稳定底色
    def _normalBackgroundColor(self):
        return QColor(theme.CARD_BG)

    def _hoverBackgroundColor(self):
        return QColor(theme.CARD_BG)

    def _pressedBackgroundColor(self):
        return QColor(theme.CARD_BG)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        r = self.borderRadius
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        p.setPen(Qt.NoPen)
        p.setBrush(self.backgroundColor)
        p.drawRoundedRect(rect, r, r)

        # hover 时描边转珊瑚橘，给无投影的卡片（如历史库）提供反馈
        pen_color = self._hairline
        if self._hover_accent and self.isHover:
            pen_color = QColor(theme.CORAL)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(pen_color, 1))
        p.drawRoundedRect(rect, r, r)
        p.end()


class AccentCard(WarmCard):
    """强调态卡片：珊瑚橘描边 + 极浅暖底，用于编辑模式横幅等。"""

    def __init__(self, parent=None, *, shadow=True, radius=theme.CARD_RADIUS):
        super().__init__(parent, shadow=shadow, radius=radius)
        self._hairline = QColor(theme.CORAL)

    def _normalBackgroundColor(self):
        return QColor(theme.CORAL_TINT)

    _hoverBackgroundColor = _normalBackgroundColor
    _pressedBackgroundColor = _normalBackgroundColor


class SectionTitle(QWidget):
    """珊瑚橘竖条 + 标题，替代纯文字标题以增加设计感。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        bar = QWidget(self)
        bar.setFixedSize(3, 14)
        bar.setStyleSheet(
            f"background: {theme.CORAL}; border-radius: 1px;")
        layout.addWidget(bar)

        self.label = QLabel(text, self)
        self.label.setObjectName("sectionTitle")
        layout.addWidget(self.label)
        layout.addStretch(1)

    def setText(self, text: str):
        self.label.setText(text)
