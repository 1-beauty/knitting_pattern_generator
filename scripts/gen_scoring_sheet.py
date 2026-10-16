"""
实验 B.3：从 100 个 pattern_plan.json 生成人工评分表 JSON。

输出：outputs/runs/semantic/scoring_sheet.json
结构：
[
  {
    "id": "sem_01",
    "prompt": "圆形结构，内部波浪吊目，外部矩形边框，背景稀疏网眼",
    "motifs": [
      {
        "motif_id": "circle_1",
        "motif_type": "circle",
        "effect": "plain",
        "parent_id": null,
        "has_params": true,
        "param_keys": ["thickness"]
      },
      ...
    ],
    "scoring": {
      "layout": null,   // 标注者填: true=正确, false=错误
      "shape": null,
      "texture": null,
      "position": null,
      "parent": null,
      "params": null,
      "error_type": "",  // G/S/H/D/N/T
      "note": ""
    }
  },
  ...
]
"""
import json, glob, os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "runs", "semantic")

entries = []
for plan_path in sorted(glob.glob(os.path.join(ROOT, "sem_*", "color_map", "*_pattern_plan.json"))):
    # 提取 sem_XX
    parts = plan_path.replace("\\", "/").split("/")
    sem_dir = [p for p in parts if p.startswith("sem_")][0]
    sem_id = sem_dir  # e.g. "sem_01"

    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    prompt = ""
    history = plan.get("history", [])
    if history:
        prompt = history[0].get("input", "")

    motifs_summary = []
    for m in plan.get("motifs", []):
        motifs_summary.append({
            "motif_id": m.get("motif_id", ""),
            "motif_type": m.get("motif_type", ""),
            "effect": m.get("effect", ""),
            "parent_id": m.get("parent_id"),
            "has_params": bool(m.get("params")),
            "param_keys": sorted(m.get("params", {}).keys()),
        })

    entries.append({
        "id": sem_id,
        "prompt": prompt,
        "motifs": motifs_summary,
        "scoring": {
            "layout": None,
            "shape": None,
            "texture": None,
            "position": None,
            "parent": None,
            "params": None,
            "error_type": "",
            "note": "",
        },
    })

# 按 sem_XX 数字排序
entries.sort(key=lambda e: int(e["id"].split("_")[1]))

out_path = os.path.join(ROOT, "scoring_sheet.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(entries, f, ensure_ascii=False, indent=2)

print(f"共生成 {len(entries)} 条评分记录 → {out_path}")
