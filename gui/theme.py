"""暖色亮色主题：米白底 + 珊瑚橘强调色。

视觉基调「温暖工坊 + 精密仪器」：不用系统灰硬描边，改为暖棕发丝线 +
柔和暖色投影 + 大圆角，避免 Windows 设置面板的观感。
所有组件从这里取色，避免散落的硬编码。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from qfluentwidgets import setTheme, setThemeColor, Theme

# ---- 调色板（暖色亮色） ----
CREAM_BG = "#F7F2EA"        # 全局背景：略压暗的米白，让白卡片浮起来
CARD_BG = "#FFFFFF"         # 卡片背景：纯白
WELL_BG = "#F4EDE3"         # 画布凹陷底（替代虚线框）
CORAL = "#E8734A"           # 主强调色：珊瑚橘
CORAL_LIGHT = "#F5C4AE"     # 强调色浅化（进行中光晕/hover）
CORAL_TINT = "#FBF1EB"      # 选中态极浅底
WARM_BROWN = "#8B6F5C"      # 次级文字：暖棕
TEXT_MAIN = "#3A2E28"       # 主文字：暖黑
SAGE_GREEN = "#7FA184"      # 成功状态：鼠尾草绿
CLAY_RED = "#C2543D"        # 失败状态：陶土红（暖调，不用系统正红）
BORDER = "#EDE4D8"          # 浅分隔线（暖调，低对比）
LOG_BG = "#2E2A26"          # 日志终端：暖黑底
LOG_FG = "#E8DFD4"          # 日志文字

# ---- 发丝描边与投影：高级感的核心 ----
HAIRLINE = QColor(139, 111, 92, 40)         # 常态描边：暖棕 16% 透明
HAIRLINE_STRONG = QColor(139, 111, 92, 72)  # 强调描边（画布/选中）
SHADOW_COLOR = QColor(120, 88, 64, 34)      # 暖色投影（非中性灰）
CARD_RADIUS = 12
SHADOW_BLUR = 26
SHADOW_OFFSET_Y = 5

# ---- 跨平台字体：Windows 与 Linux 服务器各取其可用者 ----
_UI_FONT_CANDIDATES = [
    "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
    "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei",
]
_MONO_FONT_CANDIDATES = [
    "Consolas", "JetBrains Mono", "Cascadia Mono",
    "DejaVu Sans Mono", "Noto Sans Mono", "Liberation Mono", "Courier New",
]

_ui_font = None
_mono_font = None


def _pick_font(candidates, fallback):
    """选取系统中第一个可用字体族；需在 QApplication 创建后调用。"""
    available = set(QFontDatabase.families())
    if not available:
        # offscreen 等无头平台不暴露字体列表，退回首选交给 Qt 自行替代
        return candidates[0] if candidates else fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


def ui_font_family() -> str:
    global _ui_font
    if _ui_font is None:
        _ui_font = _pick_font(_UI_FONT_CANDIDATES, "sans-serif")
    return _ui_font


def mono_font_family() -> str:
    global _mono_font
    if _mono_font is None:
        _mono_font = _pick_font(_MONO_FONT_CANDIDATES, "monospace")
    return _mono_font


# 兼容旧引用（apply_theme 后会被刷新为真实可用字体）
MONO_FONT = "Consolas"


def qcolor(hex_str: str) -> QColor:
    return QColor(hex_str)


def apply_page_background(widget):
    """页面底色直接固定在控件自身。

    两重保障：
    1) palette + autoFillBackground：不依赖样式表，不会被 FluentWindow 自带的
       控件级样式表覆盖（否则页面透明，露出系统底色）；
    2) WA_StyledBackground + ID 选择器：QWidget 子类默认不绘制样式表背景，
       需显式开启；限定 ID 以免影响子控件取色。
    """
    name = widget.objectName()
    assert name, "apply_page_background 需先设置 objectName"

    pal = widget.palette()
    pal.setColor(QPalette.Window, QColor(CREAM_BG))
    widget.setPalette(pal)
    widget.setAutoFillBackground(True)

    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setStyleSheet(f"#{name} {{ background-color: {CREAM_BG}; }}")


def apply_card_shadow(widget, blur=SHADOW_BLUR, dy=SHADOW_OFFSET_Y,
                      color=None):
    """为卡片附加柔和暖色投影，营造纸片悬浮感。"""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setColor(color or SHADOW_COLOR)
    effect.setOffset(0, dy)
    widget.setGraphicsEffect(effect)
    return effect


# ---- 字号基线（截图可读性优先）----
# 论文截图按 160mm 印宽换算，正文级文字需尽量接近 6pt；
# 全局与各处硬编码字号统一按此基线放大约 1.3 倍。
BASE_PT = 12            # 全局默认字体（pt）
TITLE_PX = 28           # 页面标题
SECTION_PX = 18         # 卡片小节标题
HINT_PX = 15            # 说明/提示文字
LOG_PX = 14             # 日志终端


def build_qss() -> str:
    """构建全局 QSS；字体在运行时按平台可用性决定。"""
    ui = ui_font_family()
    mono = mono_font_family()
    return f"""
QWidget#pageRoot, QWidget#workspacePage, QWidget#historyPage, QWidget#settingsPage {{
    background-color: {CREAM_BG};
}}
QLabel#pageTitle {{
    font-size: {TITLE_PX}px;
    font-weight: bold;
    color: {TEXT_MAIN};
}}
QLabel#sectionTitle {{
    font-size: {SECTION_PX}px;
    font-weight: bold;
    color: {TEXT_MAIN};
    letter-spacing: 0.5px;
}}
QLabel#hintText {{
    color: {WARM_BROWN};
    font-size: {HINT_PX}px;
}}
QPlainTextEdit#logConsole {{
    background-color: {LOG_BG};
    color: {LOG_FG};
    border: none;
    border-radius: 10px;
    font-family: "{mono}";
    font-size: {LOG_PX}px;
    padding: 8px;
    selection-background-color: {CORAL};
}}
QToolTip {{
    background-color: {CARD_BG};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    font-family: "{ui}";
}}
"""


def apply_theme(app):
    """应用亮色暖主题：Fluent 亮色 + 珊瑚橘强调色 + 全局 QSS。"""
    global MONO_FONT
    setTheme(Theme.LIGHT)
    setThemeColor(CORAL)
    MONO_FONT = mono_font_family()
    app.setFont(QFont(ui_font_family(), BASE_PT))
    app.setStyleSheet(build_qss())
