"""
实验 F：提取所有消融案例的 N_e / N_t 并核查 N_t > N_e 的情况。
输出：
  1. 终端打印汇总表
  2. outputs/runs/ablation/ne_nt_audit.json
"""
import json, glob, os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "outputs", "runs", "ablation")

results = []
for stats_path in sorted(glob.glob(os.path.join(ROOT, "abl_*", "color_map", "*_stats.json"))):
    rel = os.path.relpath(stats_path, ROOT)          # abl_01_full/color_map/abl_01_stats.json
    case_dir = rel.split(os.sep)[0]                   # abl_01_full
    with open(stats_path, encoding="utf-8") as f:
        d = json.load(f)
    n_e = d.get("total_events", "?")
    n_t = d.get("layer_clip_audit", {}).get("texture_actions", "?")
    flag = ""
    if isinstance(n_e, (int, float)) and isinstance(n_t, (int, float)):
        if n_t > n_e:
            flag = f"  ← N_t > N_e (×{n_t/n_e:.1f})"
    results.append({
        "case": case_dir,
        "N_e": n_e,
        "N_t": n_t,
        "diff": n_t - n_e if isinstance(n_e, (int, float)) and isinstance(n_t, (int, float)) else None,
        "flag": bool(flag),
    })

# ── 终端打印 ──
print(f"{'case':<35} {'N_e':>6} {'N_t':>6} {'N_t-N_e':>8}  flag")
print("-" * 75)
anomaly_count = 0
for r in results:
    diff_str = str(r["diff"]) if r["diff"] is not None else "?"
    flag_str = "  ← N_t > N_e" if r["flag"] else ""
    print(f"{r['case']:<35} {str(r['N_e']):>6} {str(r['N_t']):>6} {diff_str:>8}{flag_str}")
    if r["flag"]:
        anomaly_count += 1

print(f"\n共 {len(results)} 条，其中 N_t > N_e 的有 {anomaly_count} 条。")

# ── 保存 JSON ──
out_path = os.path.join(ROOT, "ne_nt_audit.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"total": len(results), "anomaly_count": anomaly_count, "entries": results}, f, ensure_ascii=False, indent=2)
print(f"已保存到 {out_path}")
