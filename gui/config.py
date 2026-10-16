"""GUI 配置：解释器路径、默认生成参数，QSettings 持久化。"""

import sys
from pathlib import Path

from PySide6.QtCore import QSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = PROJECT_ROOT / "outputs" / "runs"
GUI_RUNS_CATEGORY = "gui"  # GUI 发起的 run 统一放在 outputs/runs/gui/ 下

# 执行模式：本机直接跑，或 SSH 下发到服务器跑（推理靠 GPU，界面留本地）
EXEC_LOCAL = "local"
EXEC_REMOTE = "remote"

# 远程默认值：已核实的服务器环境
DEFAULT_SSH_HOST = "10.177.11.65"
DEFAULT_REMOTE_ROOT = "/data/wr/knitting_pattern_generator"
DEFAULT_REMOTE_PYTHON = "/data/conda/envs/knitting/bin/python"


class AppConfig:
    """薄封装 QSettings，GUI 各处共享一份实例。"""

    def __init__(self):
        self._s = QSettings("KnitStudio", "gui")

    # ---- 流水线解释器（默认与 GUI 同一 Python） ----
    @property
    def python_path(self) -> str:
        return self._s.value("pipeline/python", sys.executable)

    @python_path.setter
    def python_path(self, value: str):
        self._s.setValue("pipeline/python", value)

    # ---- 默认生成参数 ----
    @property
    def device(self) -> str:
        return self._s.value("pipeline/device", "auto")

    @device.setter
    def device(self, value: str):
        self._s.setValue("pipeline/device", value)

    @property
    def stage(self) -> int:
        return int(self._s.value("pipeline/stage", 4))

    @stage.setter
    def stage(self, value: int):
        self._s.setValue("pipeline/stage", int(value))

    @property
    def seed(self) -> int:
        return int(self._s.value("pipeline/seed", 42))

    @seed.setter
    def seed(self, value: int):
        self._s.setValue("pipeline/seed", int(value))

    # ---- 执行模式与远程配置 ----
    @property
    def exec_mode(self) -> str:
        return self._s.value("exec/mode", EXEC_REMOTE)

    @exec_mode.setter
    def exec_mode(self, value: str):
        self._s.setValue("exec/mode", value)

    @property
    def is_remote(self) -> bool:
        return self.exec_mode == EXEC_REMOTE

    @property
    def ssh_host(self) -> str:
        """SSH 目标（可是 ~/.ssh/config 里的 Host 别名或 user@ip）。"""
        return self._s.value("exec/ssh_host", DEFAULT_SSH_HOST)

    @ssh_host.setter
    def ssh_host(self, value: str):
        self._s.setValue("exec/ssh_host", value)

    @property
    def remote_root(self) -> str:
        return self._s.value("exec/remote_root", DEFAULT_REMOTE_ROOT)

    @remote_root.setter
    def remote_root(self, value: str):
        self._s.setValue("exec/remote_root", value)

    @property
    def remote_python(self) -> str:
        return self._s.value("exec/remote_python", DEFAULT_REMOTE_PYTHON)

    @remote_python.setter
    def remote_python(self, value: str):
        self._s.setValue("exec/remote_python", value)


config = AppConfig()
