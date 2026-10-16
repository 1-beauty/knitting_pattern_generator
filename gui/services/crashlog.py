"""全局异常兜底：把未捕获异常写进日志文件，并广播给界面显示。

背景：pythonw.exe 启动时没有 stderr，槽函数里的异常会被静默吞掉；
若异常发生在「按钮已置灰、进程尚未启动」之间，界面就表现为按钮永久点不动
且毫无提示。这里统一收口，保证任何异常都留痕、可见、可定位。
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from gui.config import PROJECT_ROOT

LOG_PATH = PROJECT_ROOT / "outputs" / "gui_error.log"


class _CrashBus(QObject):
    error = Signal(str)   # 供界面弹提示 / 写运行日志的摘要


bus = _CrashBus()


def report(exc: BaseException, context: str = "") -> str:
    """记录异常并广播摘要，返回该摘要。"""
    summary = f"{type(exc).__name__}: {exc}"
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} · {context or '异常'} =====\n")
            fh.write(detail)
    except OSError:
        pass
    try:
        bus.error.emit(f"{context}｜{summary}" if context else summary)
    except Exception:      # 提示自身出错不能再抛，否则递归
        pass
    return summary


def install():
    """接管 sys.excepthook（PySide6 下槽函数内的异常也会走到这里）。"""

    def hook(exc_type, exc, tb):
        if exc.__traceback__ is None:
            exc.__traceback__ = tb
        report(exc, "未捕获异常")

    sys.excepthook = hook
