"""主窗口：FluentWindow + 左侧导航（工作台 / 历史库 / 设置）。"""

from __future__ import annotations

from PySide6.QtGui import QColor
from qfluentwidgets import FluentIcon as FIF, FluentWindow, NavigationItemPosition

from gui import theme
from gui.pages.history_page import HistoryPage
from gui.pages.settings_page import SettingsPage
from gui.pages.workspace_page import WorkspacePage
from gui.services.runs_repository import RunInfo


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Knit Studio · 针织图案设计工作台")
        self.resize(1440, 900)
        # 米白暖底（旧版本 qfluentwidgets 无此 API 时静默跳过）
        try:
            self.setCustomBackgroundColor(
                QColor(theme.CREAM_BG), QColor(theme.LOG_BG))
        except AttributeError:
            pass

        self.workspace = WorkspacePage(self)
        self.history = HistoryPage(self)
        self.settings = SettingsPage(self)

        self.addSubInterface(self.workspace, FIF.BRUSH, "工作台")
        self.addSubInterface(self.history, FIF.HISTORY, "历史库")
        self.addSubInterface(
            self.settings, FIF.SETTING, "设置", NavigationItemPosition.BOTTOM)

        # 历史页 → 工作台联动
        self.history.loadRequested.connect(self._load_from_history)
        self.history.editRequested.connect(self._edit_from_history)

    def _load_from_history(self, info: RunInfo):
        self.workspace.exit_edit_mode()
        self.workspace.load_run(info)
        self.switchTo(self.workspace)

    def _edit_from_history(self, info: RunInfo):
        self.workspace.enter_edit_mode(info)
        self.switchTo(self.workspace)
