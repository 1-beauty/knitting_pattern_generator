"""Knit Studio 入口。

启动:
  E:\\ProgramData\\miniconda3\\python.exe e:\\DeskTop\\knitting_pattern_generator\\gui\\main.py
"""

import sys
from pathlib import Path

# 保证 "gui.*" 包可从任意工作目录导入
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402
from qfluentwidgets import InfoBar, InfoBarPosition  # noqa: E402

from gui.main_window import MainWindow  # noqa: E402
from gui.services import crashlog  # noqa: E402
from gui.theme import apply_theme  # noqa: E402


def main():
    crashlog.install()
    app = QApplication(sys.argv)
    app.setApplicationName("Knit Studio")
    apply_theme(app)
    window = MainWindow()

    def show_error(message: str):
        InfoBar.error("出错了", message, parent=window,
                      position=InfoBarPosition.TOP_RIGHT, duration=10000)

    crashlog.bus.error.connect(show_error)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
