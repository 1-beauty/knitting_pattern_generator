"""历史库页：扫描 outputs/runs，缩略图卡片瀑布流，支持筛选 / 载入 / 继续编辑。

远程模式下可一键把服务器的 outputs/runs 整体镜像到本地，之后完全离线浏览。
"""

from __future__ import annotations

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from qfluentwidgets import (
    FlowLayout, InfoBar, InfoBarPosition, PushButton, SearchLineEdit,
    SmoothScrollArea, FluentIcon as FIF,
)

from gui import theme
from gui.config import RUNS_DIR, config
from gui.services import remote
from gui.services import runs_repository as repo
from gui.services.runs_repository import RunInfo
from gui.widgets.run_card import RunCard


class HistoryPage(QWidget):
    loadRequested = Signal(object)   # RunInfo
    editRequested = Signal(object)   # RunInfo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("historyPage")
        theme.apply_page_background(self)
        self._runs: list[RunInfo] = []
        self._sync: QProcess | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("历史库")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText("按指令 / 目录名筛选…")
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(self._apply_filter)
        header.addWidget(self.search)

        self.sync_btn = PushButton(FIF.CLOUD_DOWNLOAD, "同步远端历史", self)
        self.sync_btn.setToolTip("把服务器 outputs/runs 整体拉回本地（仅远程模式）")
        self.sync_btn.clicked.connect(self._sync_remote)
        self.sync_btn.setEnabled(config.is_remote)
        header.addWidget(self.sync_btn)

        refresh_btn = PushButton(FIF.SYNC, "刷新", self)
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        self.count_label = QLabel("")
        self.count_label.setObjectName("hintText")
        root.addWidget(self.count_label)

        self._scroll = SmoothScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._flow = FlowLayout(self._container, needAni=False)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self._flow.setHorizontalSpacing(12)
        self._flow.setVerticalSpacing(12)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_btn.setEnabled(config.is_remote
                                 and not self._sync_running())
        if not self._runs:
            self.refresh()

    def refresh(self):
        self._runs = repo.scan_runs()
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str):
        text = (text or "").strip().lower()
        self._flow.takeAllWidgets()
        shown = 0
        for info in self._runs:
            if text and text not in info.prompt.lower() \
                    and text not in str(info.run_dir).lower():
                continue
            card = RunCard(info, self._container)
            card.loadRequested.connect(self.loadRequested)
            card.editRequested.connect(self.editRequested)
            self._flow.addWidget(card)
            shown += 1
        self.count_label.setText(f"共 {len(self._runs)} 条记录，当前显示 {shown} 条")

    # ---------- 远端同步 ----------

    def _sync_running(self) -> bool:
        return self._sync is not None and self._sync.state() != QProcess.NotRunning

    def _sync_remote(self):
        if self._sync_running():
            return
        if not config.is_remote:
            InfoBar.warning("当前为本机模式", "在设置页切到「远程服务器」后再同步",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("同步中…")
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

        chunks: list[bytes] = []
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(
            lambda: chunks.append(bytes(proc.readAllStandardOutput())))
        proc.finished.connect(
            lambda code, _s: self._on_sync_done(
                code, b"".join(chunks).decode("utf-8", errors="replace")))
        proc.errorOccurred.connect(self._on_sync_error)
        self._sync = proc
        # 拉到 outputs/ 下，scp 自动合入同名 runs 目录
        proc.start("scp", remote.scp_pull_args(
            str(remote.remote_runs_root()), RUNS_DIR.parent))

    def _reset_sync_btn(self):
        self.sync_btn.setText("同步远端历史")
        self.sync_btn.setEnabled(config.is_remote)

    def _on_sync_done(self, exit_code: int, output: str):
        self._reset_sync_btn()
        if exit_code == 0:
            self.refresh()
            InfoBar.success("同步完成", f"已镜像远端历史，共 {len(self._runs)} 条记录",
                            parent=self, position=InfoBarPosition.TOP, duration=3000)
        else:
            lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
            detail = lines[-1] if lines else f"退出码 {exit_code}"
            InfoBar.error("同步失败", detail, parent=self,
                          position=InfoBarPosition.TOP, duration=6000)

    def _on_sync_error(self, error):
        if error == QProcess.FailedToStart:
            self._reset_sync_btn()
            InfoBar.error("同步失败", "找不到 scp 命令，请安装 OpenSSH 客户端",
                          parent=self, position=InfoBarPosition.TOP, duration=6000)
