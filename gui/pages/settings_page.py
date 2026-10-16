"""设置页：执行位置（本地／远程 SSH）、流水线解释器与默认参数。"""

from __future__ import annotations

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBox, CompactSpinBox, LineEdit, PrimaryPushButton, PushButton,
    FluentIcon as FIF,
)

from gui import theme
from gui.config import EXEC_LOCAL, EXEC_REMOTE, PROJECT_ROOT, RUNS_DIR, config
from gui.services import remote
from gui.widgets.warm_card import SectionTitle, WarmCard

_MODE_LABELS = {EXEC_REMOTE: "远程服务器（SSH）", EXEC_LOCAL: "本机"}


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        theme.apply_page_background(self)
        self._probe: QProcess | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("设置")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        root.addWidget(self._build_exec_card())
        root.addWidget(self._build_remote_card())

        # ---- 流水线解释器 ----
        py_card = WarmCard(self)
        self.py_card = py_card
        py_lay = QVBoxLayout(py_card)
        py_lay.setContentsMargins(16, 14, 16, 16)
        py_lay.addWidget(SectionTitle("本机流水线 Python 解释器", py_card))
        hint = QLabel("仅「本机」模式使用；需装好项目依赖（torch / LLM 客户端等）")
        hint.setObjectName("hintText")
        py_lay.addWidget(hint)

        row = QHBoxLayout()
        self.py_edit = LineEdit(py_card)
        self.py_edit.setText(config.python_path)
        self.py_edit.editingFinished.connect(
            lambda: setattr(config, "python_path", self.py_edit.text().strip()))
        row.addWidget(self.py_edit, 1)
        browse = PushButton(FIF.FOLDER, "浏览", py_card)
        browse.clicked.connect(self._browse_python)
        row.addWidget(browse)
        py_lay.addLayout(row)
        root.addWidget(py_card)

        # ---- 默认生成参数 ----
        param_card = WarmCard(self)
        pm_lay = QVBoxLayout(param_card)
        pm_lay.setContentsMargins(16, 14, 16, 16)
        pm_lay.addWidget(SectionTitle("默认生成参数", param_card))

        row2 = QHBoxLayout()
        self.device_combo = ComboBox(param_card)
        self.device_combo.addItems(["auto", "cuda", "cpu"])
        self.device_combo.setCurrentText(config.device)
        self.device_combo.currentTextChanged.connect(
            lambda v: setattr(config, "device", v))

        self.stage_combo = ComboBox(param_card)
        self.stage_combo.addItems(["1", "2", "3", "4"])
        self.stage_combo.setCurrentText(str(config.stage))
        self.stage_combo.currentTextChanged.connect(
            lambda v: setattr(config, "stage", int(v)))

        self.seed_spin = CompactSpinBox(param_card)
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.setValue(config.seed)
        self.seed_spin.valueChanged.connect(lambda v: setattr(config, "seed", v))

        for label, w in (("设备", self.device_combo),
                         ("视觉预览 Stage", self.stage_combo), ("默认种子", self.seed_spin)):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lab = QLabel(label)
            lab.setObjectName("hintText")
            cell.addWidget(lab)
            cell.addWidget(w)
            row2.addLayout(cell)
        row2.addStretch(1)
        pm_lay.addLayout(row2)
        root.addWidget(param_card)

        # ---- 路径信息 ----
        info_card = WarmCard(self)
        info_lay = QVBoxLayout(info_card)
        info_lay.setContentsMargins(16, 14, 16, 16)
        info_lay.addWidget(SectionTitle("路径", info_card))
        for text in (f"项目根目录：{PROJECT_ROOT}", f"输出目录：{RUNS_DIR}"):
            lab = QLabel(text)
            lab.setObjectName("hintText")
            lab.setTextInteractionFlags(lab.textInteractionFlags()
                                        | lab.textInteractionFlags().TextSelectableByMouse)
            info_lay.addWidget(lab)
        root.addWidget(info_card)

        root.addStretch(1)
        self._sync_mode_ui()

    # ---------- 卡片构建 ----------

    def _build_exec_card(self) -> WarmCard:
        card = WarmCard(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.addWidget(SectionTitle("执行位置", card))
        hint = QLabel("界面在本机渲染，推理下发到服务器 GPU；产物运行结束自动回传本地")
        hint.setObjectName("hintText")
        lay.addWidget(hint)

        self.mode_combo = ComboBox(card)
        for mode in (EXEC_REMOTE, EXEC_LOCAL):
            self.mode_combo.addItem(_MODE_LABELS[mode], userData=mode)
        self.mode_combo.setCurrentText(_MODE_LABELS.get(config.exec_mode,
                                                       _MODE_LABELS[EXEC_REMOTE]))
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        row = QHBoxLayout()
        row.addWidget(self.mode_combo)
        row.addStretch(1)
        lay.addLayout(row)
        return card

    def _build_remote_card(self) -> WarmCard:
        card = WarmCard(self)
        self.remote_card = card
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.addWidget(SectionTitle("远程服务器", card))
        hint = QLabel("需已配置 SSH 免密登录（公钥认证）；主机可填 IP、user@IP 或 ~/.ssh/config 别名")
        hint.setObjectName("hintText")
        lay.addWidget(hint)

        self.host_edit = self._add_field(lay, card, "SSH 主机", config.ssh_host, "ssh_host")
        self.root_edit = self._add_field(lay, card, "远端项目根目录",
                                        config.remote_root, "remote_root")
        self.rpy_edit = self._add_field(lay, card, "远端 Python 解释器",
                                       config.remote_python, "remote_python")

        row = QHBoxLayout()
        self.test_btn = PrimaryPushButton(FIF.CONNECT, "测试连接", card)
        self.test_btn.clicked.connect(self._test_connection)
        row.addWidget(self.test_btn)
        self.probe_label = QLabel("")
        self.probe_label.setObjectName("hintText")
        self.probe_label.setWordWrap(True)
        row.addWidget(self.probe_label, 1)
        lay.addSpacing(4)
        lay.addLayout(row)
        return card

    def _add_field(self, lay, card, label: str, value: str, attr: str) -> LineEdit:
        lab = QLabel(label)
        lab.setObjectName("hintText")
        lay.addWidget(lab)
        edit = LineEdit(card)
        edit.setText(value)
        edit.editingFinished.connect(
            lambda: setattr(config, attr, edit.text().strip()))
        lay.addWidget(edit)
        return edit

    # ---------- 交互 ----------

    def _on_mode_changed(self, index: int):
        config.exec_mode = self.mode_combo.itemData(index)
        self._sync_mode_ui()

    def _sync_mode_ui(self):
        """按当前模式禁用无关卡片，避免误改到不生效的字段。"""
        remote_on = config.is_remote
        self.remote_card.setEnabled(remote_on)
        self.py_card.setEnabled(not remote_on)

    def _test_connection(self):
        if self._probe is not None and self._probe.state() != QProcess.NotRunning:
            return
        # 用户可能刚输完还没触发 editingFinished，先落盘再测
        config.ssh_host = self.host_edit.text().strip()
        config.remote_root = self.root_edit.text().strip()
        config.remote_python = self.rpy_edit.text().strip()

        self.test_btn.setEnabled(False)
        self._set_probe_text(f"正在连接 {config.ssh_host} …", theme.WARM_BROWN)

        chunks: list[bytes] = []
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(
            lambda: chunks.append(bytes(proc.readAllStandardOutput())))
        proc.finished.connect(
            lambda code, _s: self._on_probe_done(
                code, b"".join(chunks).decode("utf-8", errors="replace")))
        proc.errorOccurred.connect(self._on_probe_error)
        self._probe = proc
        proc.start("ssh", remote.ssh_args(remote.probe_command()))

    def _on_probe_done(self, exit_code: int, output: str):
        self.test_btn.setEnabled(True)
        lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
        if exit_code == 0 and len(lines) >= 3:
            host, py_ver, run_count = lines[0], lines[1], lines[-1]
            self._set_probe_text(
                f"✓ {host} · {py_ver} · outputs/runs 下 {run_count} 项",
                theme.SAGE_GREEN)
        else:
            detail = lines[-1] if lines else f"退出码 {exit_code}"
            self._set_probe_text(f"✗ 连接失败：{detail}", theme.CLAY_RED)

    def _on_probe_error(self, error):
        self.test_btn.setEnabled(True)
        if error == QProcess.FailedToStart:
            self._set_probe_text(
                "✗ 找不到 ssh 命令，请安装 OpenSSH 客户端（Windows 可选功能）",
                theme.CLAY_RED)

    def _set_probe_text(self, text: str, color: str):
        self.probe_label.setText(text)
        self.probe_label.setStyleSheet(f"color: {color}; font-size: 15px;")

    def _browse_python(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Python 解释器", "", "python.exe (python*.exe);;所有文件 (*)")
        if path:
            self.py_edit.setText(path)
            config.python_path = path
