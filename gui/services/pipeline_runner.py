"""后台流水线执行：QProcess 调用 run_pipeline.py，流式回传日志与阶段进度。

两种执行模式（设置页切换）：
- 本地：python run_pipeline.py all "<prompt>" --run-name gui/<ts> ...
- 远程：ssh <host> "cd <远端根> && <远端python> run_pipeline.py ..."，
        跑完再 scp 把该 run 目录拉回本地镜像，最后一节点为「回传产物」。

编辑模式追加 --plan-in <上一版 pattern_plan.json>（远程模式自动换算为远端路径）。

阶段判定基于已有日志锚点（generator_one/pipeline.py 与 run_pipeline.py 的固定输出），
不改动任何后端代码。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from gui.config import PROJECT_ROOT, RUNS_DIR, GUI_RUNS_CATEGORY, config
from gui.services import remote

RUN_PIPELINE = PROJECT_ROOT / "run_pipeline.py"

GEN_STAGES = ["语义解析", "PatternPlan", "色码图", "视觉预览"]
# 编辑态左栏窄（格宽约 89px），标签须控在四字内才能单行不互撞；
# 编辑语义由「编辑模式」横幅承担，此处不再叠 Plan/LLM 字样
EDIT_STAGES = ["载入基础", "增量编辑", "色码图", "视觉预览"]
SYNC_STAGE = "回传产物"

# 阶段状态
PENDING, ACTIVE, DONE = 0, 1, 2


class PipelineRunner(QObject):
    """封装一次流水线执行；同一实例可复用（串行）。"""

    started = Signal(list)            # 阶段标签列表
    logLine = Signal(str)
    stageChanged = Signal(int, int)   # (阶段下标, 状态)
    finished = Signal(bool, object)   # (是否成功, run_dir: Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._run_dir: Path | None = None
        self._run_name = ""
        self._is_edit = False
        self._color_only = False
        self._remote = False
        self._syncing = False          # 当前进程是否为 scp 回传
        self._finished_sent = False    # 本轮是否已发过 finished（防重复收尾）
        self._buffer = b""

    # ---------- 对外入口 ----------

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start_generate(self, prompt: str, *, color_only=False, device=None,
                       stage=None, seed=None, num_candidates=1):
        self._is_edit = False
        self._finished_sent = False
        opts = self._common_opts(color_only, device, stage, seed, num_candidates)
        self._start(prompt, opts, GEN_STAGES)

    def start_edit(self, prompt: str, plan_in: Path, *, color_only=False, device=None,
                   stage=None, seed=None, num_candidates=1):
        self._is_edit = True
        self._finished_sent = False
        if plan_in is None:
            self.logLine.emit("[GUI] 无法编辑：基础版本缺少 pattern_plan.json")
            self._emit_finished(False, None)
            return
        if config.is_remote:
            try:
                plan_arg = remote.to_remote_path(plan_in)
            except (ValueError, TypeError) as exc:
                self.logLine.emit(f"[GUI] 无法编辑：{exc}")
                self._emit_finished(False, None)
                return
        else:
            plan_arg = str(plan_in)
        opts = self._common_opts(color_only, device, stage, seed, num_candidates)
        opts += ["--plan-in", plan_arg]
        self._start(prompt, opts, EDIT_STAGES)

    def stop(self):
        if self.is_running():
            self._proc.kill()

    @property
    def run_dir(self) -> Path | None:
        return self._run_dir

    # ---------- 内部 ----------

    def _emit_finished(self, success: bool, run_dir):
        """唯一的收尾出口：保证每轮只发一次，且任何异常路径都能解锁界面。"""
        if self._finished_sent:
            return
        self._finished_sent = True
        self.finished.emit(success, run_dir)

    def _common_opts(self, color_only, device, stage, seed, num_candidates):
        """run_pipeline.py 的可选参数（不含子命令与 prompt）。"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._run_name = f"{GUI_RUNS_CATEGORY}/{ts}"
        self._run_dir = RUNS_DIR / GUI_RUNS_CATEGORY / ts
        self._color_only = color_only
        return [
            "--run-name", self._run_name,
            "--device", device or config.device,
            "--stage", str(stage or config.stage),
            "--seed", str(seed if seed is not None else config.seed),
            "--num_candidates", str(num_candidates),
        ]

    def _start(self, prompt: str, opts: list[str], stage_labels: list[str]):
        if self.is_running():
            # 必须回一个 finished，否则调用方置灰的按钮再也回不来
            self.logLine.emit("[GUI] 已有任务在运行，忽略本次请求")
            self._emit_finished(False, None)
            return

        self._remote = config.is_remote
        self._syncing = False
        mode = "color" if self._color_only else "all"

        labels = list(stage_labels)
        if self._color_only:
            # 仅色码图：不跑视觉预览，去掉末节点，保持下标与 _last_pipeline_stage 一致
            labels = labels[:3]
        if self._remote:
            labels.append(SYNC_STAGE)   # 远程模式多一节点：产物回传
        self.started.emit(labels)
        self.stageChanged.emit(0, ACTIVE)

        if self._remote:
            cmd = remote.build_remote_command(mode, prompt, opts)
            program, args = "ssh", remote.ssh_args(cmd)
            self.logLine.emit(f"[GUI] 远程执行 @ {config.ssh_host}")
            self.logLine.emit(f"[GUI] $ {cmd}")
        else:
            program = config.python_path
            args = [str(RUN_PIPELINE), mode, prompt] + opts
            self.logLine.emit(f"[GUI] $ {program} " + " ".join(args))

        self._spawn(program, args)

    def _spawn(self, program: str, args: list[str]):
        self._buffer = b""
        self._discard_proc()
        proc = QProcess(self)
        proc.setWorkingDirectory(str(PROJECT_ROOT))
        proc.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(self._on_output)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        proc.start(program, args)

    def _discard_proc(self):
        """丢弃上一个已结束的进程对象：断信号 + 交给 Qt 回收，避免陈旧回调。"""
        old = self._proc
        self._proc = None
        if old is None:
            return
        try:
            old.readyReadStandardOutput.disconnect(self._on_output)
            old.finished.disconnect(self._on_finished)
            old.errorOccurred.disconnect(self._on_error)
        except (RuntimeError, TypeError):
            pass
        old.deleteLater()

    def _on_output(self):
        self._buffer += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\n", 1)
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            if line:
                self.logLine.emit(line)
                self._match_stage(line)

    def _match_stage(self, line: str):
        """根据后端日志锚点推进步骤条。"""
        if self._is_edit and "Loaded current pattern plan" in line:
            # 编辑模式：基础 Plan 载入完成，进入 LLM 增量编辑
            self.stageChanged.emit(0, DONE)
            self.stageChanged.emit(1, ACTIVE)
        elif "Saved pattern plan to" in line:
            # Plan 落盘：前两个阶段完成（语义解析+Plan / 载入+增量编辑）
            self.stageChanged.emit(0, DONE)
            self.stageChanged.emit(1, DONE)
        elif "Saved simulation input PNG" in line:
            # 色码图产物就绪
            self.stageChanged.emit(0, DONE)
            self.stageChanged.emit(1, DONE)
            self.stageChanged.emit(2, DONE)
            if not self._color_only:
                self.stageChanged.emit(3, ACTIVE)
        elif "inference.py" in line and "cmd:" in line:
            # run_pipeline 开始调用视觉预览推理
            self.stageChanged.emit(3, ACTIVE)

    def _last_pipeline_stage(self) -> int:
        return 2 if self._color_only else 3

    def _on_finished(self, exit_code: int, _status):
        success = exit_code == 0

        # 阶段一：scp 回传结束
        if self._syncing:
            self._syncing = False
            sync_index = self._last_pipeline_stage() + 1
            if success:
                self.stageChanged.emit(sync_index, DONE)
                self.logLine.emit("[GUI] 产物已回传本地 ✓")
            else:
                self.logLine.emit(f"[GUI] 产物回传失败，退出码 {exit_code}")
            self._emit_finished(success, self._run_dir)
            return

        # 阶段二：流水线本体结束
        if not success:
            self.logLine.emit(f"[GUI] 任务失败，退出码 {exit_code}")
            self._emit_finished(False, self._run_dir)
            return

        for i in range(self._last_pipeline_stage() + 1):
            self.stageChanged.emit(i, DONE)
        self.logLine.emit("[GUI] 远端任务完成 ✓" if self._remote else "[GUI] 任务完成 ✓")

        if self._remote:
            self._start_pull()
        else:
            self._emit_finished(True, self._run_dir)

    def _start_pull(self):
        """把远端 run 目录拉回本地镜像（本地父目录须先存在）。"""
        local_parent = self._run_dir.parent
        local_parent.mkdir(parents=True, exist_ok=True)
        remote_dir = remote.remote_run_dir(self._run_name)

        self._syncing = True
        self.stageChanged.emit(self._last_pipeline_stage() + 1, ACTIVE)
        self.logLine.emit(f"[GUI] 回传产物: {remote_dir} → {local_parent}")
        self._spawn("scp", remote.scp_pull_args(remote_dir, local_parent))

    def _on_error(self, error):
        self.logLine.emit(f"[GUI] 进程错误: {error}")
        if error == QProcess.FailedToStart:
            program = "scp" if self._syncing else ("ssh" if self._remote else "python")
            self.logLine.emit(
                f"[GUI] 无法启动 {program}，请确认它在 PATH 中（Windows 10+ 自带 OpenSSH 客户端）")
            self._syncing = False
            self._emit_finished(False, self._run_dir)
        elif not self.is_running():
            # 进程已不在运行却没走 finished（异常退出等），补一次收尾解锁界面
            self._syncing = False
            self._emit_finished(False, self._run_dir)
