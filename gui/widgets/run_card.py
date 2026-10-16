"""历史库卡片：缩略图 + 指令摘要 + 载入 / 继续编辑。"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from qfluentwidgets import PrimaryPushButton, PushButton

from gui import theme
from gui.services.runs_repository import RunInfo
from gui.widgets.warm_card import WarmCard

THUMB = 96


class RunCard(WarmCard):
    loadRequested = Signal(object)   # RunInfo
    editRequested = Signal(object)   # RunInfo

    def __init__(self, info: RunInfo, parent=None):
        # 历史库可能同屏上百张卡片，不挂投影特效（会拖累滚动），
        # 改用发丝描边 + hover 高亮作区分。
        super().__init__(parent, shadow=False, hover_accent=True)
        self.info = info
        self.setFixedWidth(240)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # 双缩略图：色码图 + 视觉预览图
        thumbs = QHBoxLayout()
        thumbs.setSpacing(6)
        for src, caption in ((info.sim_input, "色码图"), (info.preview, "视觉预览")):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            img = QLabel()
            img.setFixedSize(THUMB, THUMB)
            img.setAlignment(Qt.AlignCenter)
            img.setStyleSheet(
                f"background: {theme.WELL_BG}; border: none;"
                f" border-radius: 8px;")
            if src is not None and src.exists():
                pix = QPixmap(str(src)).scaled(
                    THUMB, THUMB, Qt.KeepAspectRatio, Qt.FastTransformation)
                img.setPixmap(pix)
            else:
                img.setText("--")
            cap = QLabel(caption)
            cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet(f"color: {theme.WARM_BROWN}; font-size: 13px;")
            cell.addWidget(img)
            cell.addWidget(cap)
            thumbs.addLayout(cell)
        root.addLayout(thumbs)

        # 指令摘要
        prompt = QLabel(info.prompt)
        prompt.setWordWrap(True)
        # 默认垂直居中会在超行时上下各裁半行；截断只允许发生在底部
        prompt.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        prompt.setStyleSheet(f"color: {theme.TEXT_MAIN}; font-size: 15px;")
        # 按实际字体度量截整行（3 行）：n 行文本块高 = height + (n-1)*lineSpacing，
        # 用 lineSpacing*n 会多出一行残影；避免放大字号后卡在半行或挤压重叠
        fm = prompt.fontMetrics()
        prompt.setMaximumHeight(fm.height() + 2 * fm.lineSpacing())
        prompt.setToolTip(info.prompt)
        root.addWidget(prompt)

        # 分类 + 时间
        when = datetime.fromtimestamp(info.mtime).strftime("%m-%d %H:%M")
        sub = QLabel(f"{info.category or 'runs'} / {info.name} · {when}")
        sub.setStyleSheet(f"color: {theme.WARM_BROWN}; font-size: 13px;")
        sub.setToolTip(str(info.run_dir))
        root.addWidget(sub)

        # 操作按钮
        btns = QHBoxLayout()
        btns.setSpacing(8)
        load_btn = PushButton("载入", self)
        load_btn.clicked.connect(lambda: self.loadRequested.emit(self.info))
        btns.addWidget(load_btn)
        edit_btn = PrimaryPushButton("✏ 继续编辑", self)
        edit_btn.setEnabled(info.plan_path is not None)
        if info.plan_path is None:
            edit_btn.setToolTip("该 run 缺少 pattern_plan.json，无法增量编辑")
        edit_btn.clicked.connect(lambda: self.editRequested.emit(self.info))
        btns.addWidget(edit_btn)
        root.addLayout(btns)

    def sizeHint(self):
        """固定宽下的真实高度。

        不换行的 sub 行会把默认 sizeHint 宽度撑到远超 240，
        FlowLayout 按该 hint 排布后再把宽夹回 240，
        指令摘要在真实宽度下换行更多 → 卡高不足 → 子控件重叠。
        这里按固定宽重算高度，保证 hint 与实际几何一致。
        """
        hint = super().sizeHint()
        lay = self.layout()
        m = lay.contentsMargins()
        inner = 240 - m.left() - m.right()
        h = lay.heightForWidth(inner)
        if h > 0:
            hint.setHeight(h + m.top() + m.bottom())
        hint.setWidth(240)
        return hint
