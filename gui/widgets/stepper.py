"""流水线步骤条：4 节点横向进度，进行中节点带呼吸灯动画。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QWidget

from gui import theme

PENDING, ACTIVE, DONE = 0, 1, 2

NODE_R = 11          # 节点半径
GLOW_MAX = 7         # 呼吸光晕最大外扩


class PipelineStepper(QWidget):
    """set_stages() 设定标签；set_state(i, state) 推进；reset() 清零。"""

    def __init__(self, stages: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._stages = stages or ["语义解析", "PatternPlan", "色码图", "视觉预览"]
        self._states = [PENDING] * len(self._stages)
        self._pulse = 0.0
        self._pulse_dir = 1
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self.setMinimumHeight(88)

    # ---------- API ----------

    def set_stages(self, stages: list[str]):
        self._stages = list(stages)
        self.reset()

    def reset(self):
        self._states = [PENDING] * len(self._stages)
        self._timer.stop()
        self.update()

    def set_state(self, index: int, state: int):
        if 0 <= index < len(self._states):
            # DONE 不允许回退为 ACTIVE（日志锚点可能乱序触发）
            if self._states[index] == DONE and state == ACTIVE:
                return
            self._states[index] = state
            if any(s == ACTIVE for s in self._states):
                if not self._timer.isActive():
                    self._timer.start()
            else:
                self._timer.stop()
            self.update()

    def start_running(self):
        self.reset()
        self.set_state(0, ACTIVE)

    # ---------- 绘制 ----------

    def _tick(self):
        self._pulse += 0.08 * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse, self._pulse_dir = 1.0, -1
        elif self._pulse <= 0.0:
            self._pulse, self._pulse_dir = 0.0, 1
        self.update()

    def paintEvent(self, _event):
        if not self._stages:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        n = len(self._stages)
        margin = 36
        w = self.width() - margin * 2
        cy = self.height() // 2 - 8
        xs = [margin + (w * i) // (n - 1) for i in range(n)] if n > 1 else [self.width() // 2]

        coral = QColor(theme.CORAL)
        coral_light = QColor(theme.CORAL_LIGHT)
        gray = QColor(theme.BORDER)
        brown = QColor(theme.WARM_BROWN)
        text_main = QColor(theme.TEXT_MAIN)

        # 连接线：两端节点都非 PENDING 则用珊瑚橘
        for i in range(n - 1):
            lit = self._states[i] == DONE and self._states[i + 1] != PENDING
            pen = QPen(coral if lit else gray, 2)
            p.setPen(pen)
            p.drawLine(xs[i] + NODE_R + 3, cy, xs[i + 1] - NODE_R - 3, cy)

        label_font = QFont(self.font())
        label_font.setPointSize(11)

        # 标签框宽取节点间距（首尾夹回控件内）并允许换行：
        # 放大字号后若仍用固定 120px 居中框，窄左栏里长标签
        # （如「载入基础 Plan」）会出界裁切并与邻标签互撞
        cell = min((w / (n - 1)) if n > 1 else float(self.width()),
                   self.width() - 4)
        top = cy + NODE_R + 6

        for i, x in enumerate(xs):
            state = self._states[i]
            if state == ACTIVE:
                # 呼吸光晕
                glow = QColor(coral_light)
                glow.setAlphaF(0.25 + 0.35 * self._pulse)
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                r = NODE_R + 2 + GLOW_MAX * self._pulse
                p.drawEllipse(QRectF(x - r, cy - r, 2 * r, 2 * r))
                p.setBrush(coral)
                p.drawEllipse(QRectF(x - NODE_R, cy - NODE_R, 2 * NODE_R, 2 * NODE_R))
            elif state == DONE:
                p.setPen(Qt.NoPen)
                p.setBrush(coral)
                p.drawEllipse(QRectF(x - NODE_R, cy - NODE_R, 2 * NODE_R, 2 * NODE_R))
                # 白色对勾
                p.setPen(QPen(QColor("#FFFFFF"), 2))
                p.drawLine(x - 5, cy, x - 1, cy + 4)
                p.drawLine(x - 1, cy + 4, x + 5, cy - 4)
            else:
                p.setPen(QPen(gray, 2))
                p.setBrush(QColor(theme.CARD_BG))
                p.drawEllipse(QRectF(x - NODE_R, cy - NODE_R, 2 * NODE_R, 2 * NODE_R))

            # 标签
            p.setFont(label_font)
            p.setPen(text_main if state != PENDING else brown)
            left = max(2.0, min(x - cell / 2, self.width() - 2 - cell))
            rect = QRectF(left, top, cell, 34)
            p.drawText(rect, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       self._stages[i])
        p.end()
