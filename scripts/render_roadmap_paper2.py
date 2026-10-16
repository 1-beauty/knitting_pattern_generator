# -*- coding: utf-8 -*-
"""第二篇论文的三个新想法 · 简洁路线图（matplotlib）。"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(13, 7.6))
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(x, y, w, h, text, fc, ec, fs=11, tc="#1a1a1a", lw=1.8, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.35,rounding_size=1.6",
                 fc=fc, ec=ec, lw=lw, zorder=2))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc,
                zorder=3, fontweight="bold" if bold else "normal", linespacing=1.7)


def arrow(x1, y1, x2, y2, color="#444", lw=2.2, rad=0.0, ls="-", ms=20):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=ms,
                 color=color, lw=lw, linestyle=ls, connectionstyle=f"arc3,rad={rad}", zorder=1))


BLUE = ("#e3f0fb", "#1f6fb2")
PURPLE = ("#ece6f8", "#6a4fb0")
GREEN = ("#e7f6ec", "#2e9e5b")

# 标题
ax.text(50, 94, "第二篇论文的三个新想法", ha="center", va="center",
        fontsize=18, fontweight="bold", color="#123")
ax.text(50, 88, "在第一篇「文字 → 固定流水线 → 色码图」之上，让它变成人和 AI 一起做设计",
        ha="center", va="center", fontsize=11, color="#555")

# 主流程
box(3, 68, 20, 14, "草图 + 语言\n\n① 多模态输入", *BLUE, fs=12, bold=True)
box(27, 68, 46, 14, "AI Agent 主导\n理解 → 给草案 → 对话持续修改\n②③", *PURPLE, fs=12, bold=True)
box(77, 68, 20, 14, "色码图 + 针织图\n\n（可制造）", *GREEN, fs=12, bold=True)
arrow(23, 75, 27, 75)
arrow(73, 75, 77, 75)
ax.text(75, 80.5, "满意后", ha="center", va="center", fontsize=10, color="#2e7d32", fontweight="bold")
arrow(58, 68, 40, 68, color="#6a4fb0", lw=1.8, rad=-0.25, ls=(0, (4, 2.5)))
ax.text(49, 62.5, "多轮对话修改", ha="center", va="center", fontsize=10, color="#6a4fb0", fontweight="bold")

# 三个想法说明
box(3, 14, 30, 40,
    "①  多模态输入\n\n不再只能打字描述。\n画一张草图、配几句话，\n用视觉语言模型(VLM)\n把图和文字融合成\n一个可制造的设计意图。",
    *BLUE, fs=11)
box(35, 14, 30, 40,
    "②  持续修改 + 不同标准\n\n系统先给草案和示意图，\n不满意就继续聊、反复改，\n满意了才生成最终图。\n专业草图和随手涂鸦都收：\n看得懂就还原，\n看不懂就补全或主动问。",
    *PURPLE, fs=11)
box(67, 14, 30, 40,
    "③  让 AI 参与更多：Agent\n\n不再是写死的八步流水线。\n由一个 Agent 主导全程，\n自己决定何时补全、澄清、\n调用生成或修复、何时交付。\nAI 从被动一步\n变成主动决策的中枢。",
    *PURPLE, fs=11)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(BASE, "docs", "figures", "paper2_roadmap.png")
fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
print("saved:", out)
