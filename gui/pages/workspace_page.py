"""工作台页：左列（输入 + 步骤条 + 日志），右列（版本链 + 双图画布）。

普通生成与增量编辑共用本页：
  - 生成:  run_pipeline.py all "<prompt>"
  - 编辑:  载入某个历史 run 的 pattern_plan.json，run_pipeline.py all "<编辑指令>" --plan-in <plan>
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    ComboBox, CompactSpinBox, FluentIcon as FIF, InfoBar,
    InfoBarPosition, PrimaryPushButton, PushButton, TextEdit, TransparentPushButton,
)

from gui import theme
from gui.config import config
from gui.services import crashlog
from gui.services import runs_repository as repo
from gui.services.pipeline_runner import PipelineRunner, GEN_STAGES, EDIT_STAGES
from gui.services.runs_repository import RunInfo
from gui.widgets.image_canvas import ImagePanel
from gui.widgets.stepper import PipelineStepper
from gui.widgets.version_chain import VersionChain
from gui.widgets.warm_card import AccentCard, SectionTitle, WarmCard

MAX_LOG_BLOCKS = 3000


class WorkspacePage(QWidget):
    """主工作台。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workspacePage")
        theme.apply_page_background(self)

        self._current: RunInfo | None = None   # 当前展示的 run
        self._edit_base: RunInfo | None = None  # 编辑模式的基础 run（None=普通生成）
        self._pending_prompt = ""

        self.runner = PipelineRunner(self)
        self.runner.started.connect(self._on_started)
        self.runner.logLine.connect(self._append_log)
        self.runner.stageChanged.connect(self._on_stage)
        self.runner.finished.connect(self._on_finished)
        # 全局异常也进运行日志，不再靠 stderr（pythonw 启动时根本没有 stderr）
        crashlog.bus.error.connect(self._on_crash)

        self._build_ui()

    # ================= UI =================

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ---------- 左列 ----------
        left = QVBoxLayout()
        left.setSpacing(12)

        # 编辑模式横幅（默认隐藏）
        self.edit_banner = AccentCard(self)
        banner_lay = QHBoxLayout(self.edit_banner)
        banner_lay.setContentsMargins(14, 10, 10, 10)
        self.edit_banner_label = QLabel()
        self.edit_banner_label.setStyleSheet(
            f"color: {theme.CORAL}; font-weight: bold; font-size: 16px;")
        banner_lay.addWidget(self.edit_banner_label, 1)
        exit_btn = TransparentPushButton("退出编辑", self.edit_banner)
        exit_btn.clicked.connect(self.exit_edit_mode)
        banner_lay.addWidget(exit_btn)
        self.edit_banner.hide()
        left.addWidget(self.edit_banner)

        # 输入卡片
        input_card = WarmCard(self)
        input_lay = QVBoxLayout(input_card)
        input_lay.setContentsMargins(16, 14, 16, 16)
        input_lay.setSpacing(10)

        input_lay.addWidget(SectionTitle("设计指令", input_card))

        self.prompt_edit = TextEdit(input_card)
        self.prompt_edit.setPlaceholderText(
            "描述想要的针织图案，例如：\n矩形边框包裹中心圆形，圆形内部为波浪吊目，背景为平针")
        self.prompt_edit.setFixedHeight(116)
        input_lay.addWidget(self.prompt_edit)

        # 高级参数（默认收起）
        self.adv_toggle = TransparentPushButton("高级参数 ▾", input_card)
        self.adv_toggle.clicked.connect(self._toggle_advanced)
        input_lay.addWidget(self.adv_toggle, 0, Qt.AlignLeft)

        self.adv_panel = QWidget(input_card)
        adv_lay = QHBoxLayout(self.adv_panel)
        adv_lay.setContentsMargins(0, 0, 0, 0)
        adv_lay.setSpacing(8)

        self.mode_combo = ComboBox(self.adv_panel)
        self.mode_combo.addItems(["完整生成", "仅色码图"])
        self.device_combo = ComboBox(self.adv_panel)
        self.device_combo.addItems(["auto", "cuda", "cpu"])
        self.device_combo.setCurrentText(config.device)
        self.seed_spin = CompactSpinBox(self.adv_panel)
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.setValue(config.seed)
        self.cand_spin = CompactSpinBox(self.adv_panel)
        self.cand_spin.setRange(1, 9)
        self.cand_spin.setValue(1)

        for label, w in (("模式", self.mode_combo), ("设备", self.device_combo),
                         ("种子", self.seed_spin), ("候选", self.cand_spin)):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lab = QLabel(label)
            lab.setObjectName("hintText")
            cell.addWidget(lab)
            cell.addWidget(w)
            adv_lay.addLayout(cell)
        self.adv_panel.hide()
        input_lay.addWidget(self.adv_panel)

        self.run_btn = PrimaryPushButton(FIF.SEND, "✦ 生成", input_card)
        self.run_btn.clicked.connect(self._on_run_clicked)
        self.cancel_btn = PushButton(FIF.CLOSE, "中止任务", input_card)
        self.cancel_btn.setToolTip("结束当前进程（网络卡死、跟不到日志时用）")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.hide()
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.run_btn, 1)
        btn_row.addWidget(self.cancel_btn)
        input_lay.addLayout(btn_row)

        # 执行位置提示：本机还是服务器，一眼可见
        self.exec_hint = QLabel(input_card)
        self.exec_hint.setObjectName("hintText")
        input_lay.addWidget(self.exec_hint, 0, Qt.AlignRight)
        self.refresh_exec_hint()
        left.addWidget(input_card)

        # 步骤条卡片
        stepper_card = WarmCard(self)
        st_lay = QVBoxLayout(stepper_card)
        st_lay.setContentsMargins(16, 14, 16, 8)
        st_lay.addWidget(SectionTitle("流水线进度", stepper_card))
        self.stepper = PipelineStepper(GEN_STAGES, stepper_card)
        st_lay.addWidget(self.stepper)
        left.addWidget(stepper_card)

        # 日志卡片
        log_card = WarmCard(self)
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(16, 14, 16, 16)
        log_lay.setSpacing(10)
        log_lay.addWidget(SectionTitle("运行日志", log_card))
        self.log_view = QPlainTextEdit(log_card)
        self.log_view.setObjectName("logConsole")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_BLOCKS)
        log_lay.addWidget(self.log_view)
        left.addWidget(log_card, 1)

        left_wrap = QWidget(self)
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(400)
        root.addWidget(left_wrap)

        # ---------- 右列 ----------
        right = QVBoxLayout()
        right.setSpacing(12)

        self.version_chain = VersionChain(self)
        self.version_chain.versionSelected.connect(self._on_version_selected)
        right.addWidget(self.version_chain)

        images_row = QHBoxLayout()
        images_row.setSpacing(12)
        self.color_panel = ImagePanel("色码图", self)
        self.preview_panel = ImagePanel("视觉预览图", self)
        images_row.addWidget(self.color_panel, 1)
        images_row.addWidget(self.preview_panel, 1)
        right.addLayout(images_row, 1)

        root.addLayout(right, 1)

    def _toggle_advanced(self):
        show = self.adv_panel.isHidden()
        self.adv_panel.setVisible(show)
        self.adv_toggle.setText("高级参数 ▴" if show else "高级参数 ▾")

    # ================= 对外入口（历史页调用） =================

    def load_run(self, info: RunInfo):
        """载入历史 run 到画布（查看态）。"""
        self._current = info
        self.color_panel.load(info.sim_input)
        self.preview_panel.load(info.preview)
        self._refresh_chain()

    def enter_edit_mode(self, info: RunInfo):
        """进入增量编辑模式：以 info 为基础版本。"""
        if info.plan_path is None:
            InfoBar.warning("无法编辑", "该 run 缺少 pattern_plan.json",
                            parent=self, position=InfoBarPosition.TOP)
            return
        self.load_run(info)
        self._edit_base = info
        self.edit_banner_label.setText(f"✏ 编辑模式 · 基础版本: {info.name}")
        self.edit_banner.show()
        self.run_btn.setText("✦ 应用修改")
        self.stepper.set_stages(EDIT_STAGES)
        self.prompt_edit.setPlaceholderText(
            "描述要做的修改，例如：\n把边框加宽一格 / 中心纹理换成蜂窝 / 背景改为网眼")
        self.prompt_edit.setFocus()

    def exit_edit_mode(self):
        self._edit_base = None
        self.edit_banner.hide()
        self.run_btn.setText("✦ 生成")
        self.stepper.set_stages(GEN_STAGES)
        self.prompt_edit.setPlaceholderText(
            "描述想要的针织图案，例如：\n矩形边框包裹中心圆形，圆形内部为波浪吊目，背景为平针")

    # ================= 执行 =================

    def _on_run_clicked(self):
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            InfoBar.warning("指令为空", "请先输入设计指令",
                            parent=self, position=InfoBarPosition.TOP)
            return
        if self.runner.is_running():
            InfoBar.warning("任务进行中", "请等待当前任务完成，或点「中止任务」",
                            parent=self, position=InfoBarPosition.TOP)
            return

        self._pending_prompt = prompt
        kwargs = dict(
            color_only=self.mode_combo.currentIndex() == 1,
            device=self.device_combo.currentText(),
            seed=self.seed_spin.value(),
            num_candidates=self.cand_spin.value(),
        )
        self.log_view.clear()

        # 按钮置灰交由 started 信号驱动：启动路径万一抛异常，按钮不会被锁死
        try:
            if self._edit_base is not None:
                self.runner.start_edit(prompt, self._edit_base.plan_path, **kwargs)
            else:
                self.runner.start_generate(prompt, **kwargs)
        except Exception as exc:            # noqa: BLE001 启动失败必需兜底，否则界面卡死
            summary = crashlog.report(exc, "启动任务失败")
            self._reset_busy_ui()
            InfoBar.error("无法启动", summary,
                          parent=self, position=InfoBarPosition.TOP, duration=8000)

    def _on_cancel_clicked(self):
        if not self.runner.is_running():
            self._reset_busy_ui()
            return
        self._append_log("[GUI] 用户中止任务")
        if config.is_remote:
            self._append_log("[GUI] 注意：仅断开本地 ssh，服务器上已开始的推理仍会自行跑完")
        self.runner.stop()

    def _set_busy(self, busy: bool):
        self.run_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)

    def _reset_busy_ui(self):
        """无论经历了什么，只要没进程在跑，界面就必须可操作。"""
        self._set_busy(self.runner.is_running())

    def _on_crash(self, message: str):
        self._append_log(f"[异常] {message}")
        self._reset_busy_ui()

    def _on_started(self, labels: list):
        """阶段标签由 runner 给定（远程模式多一个「回传产物」节点）。"""
        self.stepper.set_stages(labels)
        self._set_busy(True)

    def _append_log(self, line: str):
        self.log_view.appendPlainText(line)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_stage(self, index: int, state: int):
        self.stepper.set_state(index, state)

    def _on_finished(self, success: bool, run_dir):
        self._set_busy(False)
        if not success:
            InfoBar.error("生成失败", "详见运行日志",
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return

        try:
            run_dir = Path(run_dir)
            parent = self._edit_base.run_dir if self._edit_base is not None else None
            repo.write_meta(run_dir, self._pending_prompt, parent)
            info = repo.load_run(run_dir)
        except Exception as exc:            # noqa: BLE001 读写产物失败不能连带界面
            summary = crashlog.report(exc, "载入结果失败")
            InfoBar.error("结果载入失败", summary,
                          parent=self, position=InfoBarPosition.TOP, duration=8000)
            return
        if info is None:
            InfoBar.error("产物缺失", f"未在 {run_dir} 找到色码图产物",
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return

        self.load_run(info)
        if self._edit_base is not None:
            # 编辑成功后，新版本成为下一次编辑的基础
            self._edit_base = info
            self.edit_banner_label.setText(f"✏ 编辑模式 · 基础版本: {info.name}")
            self.prompt_edit.clear()
        InfoBar.success("完成", f"结果已保存到 {run_dir}",
                        parent=self, position=InfoBarPosition.TOP, duration=4000)

    # ================= 版本链 =================

    def _refresh_chain(self):
        if self._current is None:
            self.version_chain.clear()
            return
        chain = repo.lineage(self._current)
        self.version_chain.rebuild(chain, self._current.run_dir)

    def _on_version_selected(self, info: RunInfo):
        """点击版本链节点：回载该版本；若处于编辑模式则同时切换编辑基础。"""
        self._current = info
        self.color_panel.load(info.sim_input)
        self.preview_panel.load(info.preview)
        if self._edit_base is not None and info.plan_path is not None:
            self._edit_base = info
            self.edit_banner_label.setText(f"✏ 编辑模式 · 基础版本: {info.name}")
        self._refresh_chain()

    # ================= 执行位置 =================

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_exec_hint()   # 设置页改过模式后回到本页跟随更新
        self._reset_busy_ui()      # 切页回来时自愈：没进程在跑就一定可点

    def refresh_exec_hint(self):
        if config.is_remote:
            text = f"执行位置：远程 {config.ssh_host} · 产物自动回传"
            color = theme.CORAL
        else:
            text = f"执行位置：本机 {Path(config.python_path).name}"
            color = theme.WARM_BROWN
        self.exec_hint.setText(text)
        self.exec_hint.setStyleSheet(f"color: {color}; font-size: 15px;")
