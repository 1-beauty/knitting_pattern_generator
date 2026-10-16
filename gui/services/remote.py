"""远程执行支撑：SSH/SCP 命令拼装与本地↔远端路径映射。

设计要点：
- 本地与远端保持**同名 run 目录**（outputs/runs/<相对路径>），互为镜像，
  因此路径换算只是根目录替换，增量编辑的 --plan-in 可直接算出远端路径。
- 中文指令不直接进命令行：先 base64 编码，远端 `base64 -d` 还原后传给
  run_pipeline.py。这样下发的命令是纯 ASCII，彻底规避 Windows 控制台
  代码页与 SSH 编码转换导致的乱码。
- 统一带 -o BatchMode=yes（免密失败时立刻报错而非挂起等密码）与
  -o ClearAllForwardings=yes（屏蔽 ~/.ssh/config 里 RemoteForward 的
  端口转发失败警告，避免污染日志）；再加 ServerAlive* 保活，网络中断时
  ssh 会在约 1 分钟内自行退出，不会让界面永久停在「运行中」。
"""

from __future__ import annotations

import base64
from pathlib import Path, PurePosixPath

from gui.config import RUNS_DIR, config

SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ClearAllForwardings=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=4",
]


def shq(text: str) -> str:
    """POSIX 单引号转义，用于把字面量安全嵌进远端 shell 命令。"""
    return "'" + text.replace("'", "'\\''") + "'"


def remote_runs_root() -> PurePosixPath:
    return PurePosixPath(config.remote_root) / "outputs" / "runs"


def to_remote_path(local_path: Path) -> str:
    """把本地 outputs/runs 下的路径换算成远端同名路径。"""
    try:
        rel = Path(local_path).resolve().relative_to(RUNS_DIR.resolve())
    except ValueError:
        raise ValueError(
            f"{local_path} 不在 outputs/runs 下，算不出对应的服务器路径") from None
    return str(remote_runs_root() / PurePosixPath(rel.as_posix()))


def remote_run_dir(run_name: str) -> str:
    """run_name 形如 gui/20260731_120000。"""
    return str(remote_runs_root() / PurePosixPath(run_name))


def build_remote_command(mode: str, prompt: str, opts: list[str]) -> str:
    """拼出在远端执行的单条 shell 命令。

    对应：run_pipeline.py <mode> "<prompt>" <opts...>
    prompt 单独用 base64 下发，其余参数逐个单引号转义。
    """
    prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    quoted_opts = " ".join(shq(a) for a in opts)
    return (
        f"cd {shq(config.remote_root)} && "
        f"KP_PROMPT=\"$(printf %s {shq(prompt_b64)} | base64 -d)\" && "
        f"PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 "
        f"{shq(config.remote_python)} run_pipeline.py "
        f"{shq(mode)} \"$KP_PROMPT\" {quoted_opts}"
    )


def ssh_args(remote_command: str) -> list[str]:
    return SSH_OPTS + [config.ssh_host, remote_command]


def scp_pull_args(remote_path: str, local_parent: Path) -> list[str]:
    """把远端目录整体拉到本地父目录下（同名合并）。"""
    return ["-r", "-q"] + SSH_OPTS + [
        f"{config.ssh_host}:{remote_path}", str(local_parent)]


def probe_command() -> str:
    """连通性自检：主机名、项目目录、解释器版本、run 数量。"""
    root = shq(config.remote_root)
    py = shq(config.remote_python)
    return (
        f"hostname && cd {root} && {py} -V && "
        f"ls outputs/runs | wc -l"
    )
