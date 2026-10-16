"""outputs/runs 扫描与版本链（lineage）管理。

约定（与 run_pipeline.py 产物一致）：
  <run_dir>/color_map/<prefix>_output.bmp          色码图
  <run_dir>/color_map/<prefix>_sim_input.png       仿真输入（缩略图来源）
  <run_dir>/color_map/<prefix>_pattern_plan.json   PatternPlan（编辑基础，--plan-in 入参）
  <run_dir>/simulation/stage<k>_result.png         视觉预览图
GUI 发起的 run 额外写 <run_dir>/gui_meta.json 记录 prompt 与父版本，用于版本链。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from gui.config import RUNS_DIR


@dataclass
class RunInfo:
    run_dir: Path
    prefix: str = "pattern"
    prompt: str = ""
    category: str = ""
    mtime: float = 0.0
    parent: str = ""              # 父 run 目录（gui_meta.json 提供，绝对路径字符串）
    color_bmp: Path | None = None
    sim_input: Path | None = None
    preview: Path | None = None
    plan_path: Path | None = None
    stats_path: Path | None = None
    edit_history: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.run_dir.name

    @property
    def has_preview(self) -> bool:
        return self.preview is not None and self.preview.exists()


def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_run(run_dir: Path) -> RunInfo | None:
    """解析单个 run 目录；无 color_map 产物则返回 None。"""
    run_dir = Path(run_dir)
    color_dir = run_dir / "color_map"
    if not color_dir.is_dir():
        return None
    sim_inputs = sorted(color_dir.glob("*_sim_input.png"))
    if not sim_inputs:
        return None
    sim_input = sim_inputs[0]
    prefix = sim_input.name[: -len("_sim_input.png")]

    info = RunInfo(run_dir=run_dir, prefix=prefix, sim_input=sim_input)
    info.mtime = sim_input.stat().st_mtime

    bmp = color_dir / f"{prefix}_output.bmp"
    info.color_bmp = bmp if bmp.exists() else None
    plan = color_dir / f"{prefix}_pattern_plan.json"
    info.plan_path = plan if plan.exists() else None
    stats = color_dir / f"{prefix}_stats.json"
    info.stats_path = stats if stats.exists() else None

    # 视觉预览：优先 stage4，其次任意 stage 结果/候选网格（兼容 simulation/ 与 sim/ 两种目录名）
    for sim_dir_name in ("simulation", "sim"):
        sim_dir = run_dir / sim_dir_name
        if not sim_dir.is_dir():
            continue
        candidates = sorted(sim_dir.glob("stage*_result.png"), reverse=True)
        candidates += sorted(sim_dir.glob("stage*_candidates_grid.png"), reverse=True)
        if candidates:
            info.preview = candidates[0]
            break

    # prompt 提取：gui_meta.json 优先，其次 PatternPlan.history
    meta = _read_json(run_dir / "gui_meta.json")
    if meta:
        info.prompt = meta.get("prompt", "")
        info.parent = meta.get("parent", "")
    if info.plan_path:
        plan_data = _read_json(info.plan_path)
        if plan_data:
            history = plan_data.get("history") or []
            info.edit_history = history
            if not info.prompt and history:
                info.prompt = str(history[-1].get("input", ""))
    if not info.prompt:
        info.prompt = run_dir.name

    try:
        info.category = str(run_dir.parent.relative_to(RUNS_DIR))
        if info.category == ".":
            info.category = ""
    except ValueError:
        info.category = ""
    return info


def scan_runs() -> list[RunInfo]:
    """扫描 outputs/runs 下的所有 run（支持 <name>/ 与 <category>/<name>/ 两级布局），按时间倒序。"""
    if not RUNS_DIR.is_dir():
        return []
    run_dirs = {p.parent for p in RUNS_DIR.glob("*/color_map")}
    run_dirs |= {p.parent for p in RUNS_DIR.glob("*/*/color_map")}
    runs = []
    for d in run_dirs:
        info = load_run(d)
        if info is not None:
            runs.append(info)
    runs.sort(key=lambda r: r.mtime, reverse=True)
    return runs


def write_meta(run_dir: Path, prompt: str, parent: Path | None = None):
    """GUI 生成完成后写元信息，供版本链与历史卡片使用。"""
    meta = {"prompt": prompt, "parent": str(parent) if parent else ""}
    try:
        with open(Path(run_dir) / "gui_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def lineage(current: RunInfo) -> list[RunInfo]:
    """构建版本链：沿 gui_meta.parent 上溯祖先，再收集当前节点的后代（按时间排序）。"""
    all_runs = {str(r.run_dir.resolve()): r for r in scan_runs()}
    key = str(current.run_dir.resolve())
    all_runs[key] = current

    # 上溯祖先
    chain: list[RunInfo] = []
    node, seen = current, {key}
    while node.parent:
        parent = all_runs.get(str(Path(node.parent).resolve()))
        if parent is None or str(parent.run_dir.resolve()) in seen:
            break
        chain.insert(0, parent)
        seen.add(str(parent.run_dir.resolve()))
        node = parent
    chain.append(current)

    # 收集后代（线性链假设：按 mtime 顺序追加所有以链内节点为父的 run）
    changed = True
    while changed:
        changed = False
        tail_keys = {str(r.run_dir.resolve()) for r in chain}
        children = [
            r for r in all_runs.values()
            if r.parent and str(Path(r.parent).resolve()) in tail_keys
            and str(r.run_dir.resolve()) not in tail_keys
        ]
        if children:
            children.sort(key=lambda r: r.mtime)
            chain.append(children[0])
            changed = True
    return chain
