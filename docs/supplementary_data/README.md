# Supplementary Per-Case Data — PatternPlan (Computers in Industry submission)

This repository hosts the **raw per-case result tables** that accompany the paper
*"PatternPlan: a hierarchical manufacturing intermediate representation for
semantic-driven knitting pattern generation"* (submitted to **Computers in Industry**, Elsevier).

To keep the Supplementary Material PDF concise, the large case-by-case numeric tables
(Sections C.4 / C.6 / C.8 / C.10 and Appendix S) are externalized here as CSV files.
The **aggregate / summary tables (S1–S10, S17, S19–S21), Algorithm S1 and Eqs. (10)–(11)
remain in the Supplementary Material PDF**, because they are directly load-bearing for the
main-text arguments and are small.

Every CSV is a faithful transcription of the corresponding supplementary table; no values were
recomputed or altered. Files are UTF-8, comma-separated, with a single header row.

---

## Metric glossary

Full definitions are given in the paper (Section 3.4 for the constraint system, Section 4 for
the evaluation protocol). In brief:

| Symbol | Meaning | Direction |
|---|---|---|
| `V_h` | Number of **hard-constraint** violations (H1–H8). `V_h = 0` ⇒ structurally manufacturable. | lower is better |
| `V_c` | Number of **process-heuristic** constraint violations (C1–C6). | lower is better |
| `N_t` | Target-event count used by the locality/coverage diagnostics. | context-dependent |
| `T` | Texture/realization score reported per case in the baseline protocol. | higher is better |
| `Type-Coverage` | Fraction of requested action types actually realized. | higher is better |
| `TAP` | Type-And-Position agreement score. | higher is better |
| `Fidelity (strict / merged)` | Reconstruction fidelity under strict vs. family-merged action matching. | higher is better |
| `Manuf. rate` / `True-knit rate` | Share of cases that are manufacturable / truly knittable. | higher is better |
| `Region IoU` | Intersection-over-union between the intended motif region and the realized event scope. | higher is better |
| `Leakage` | Share of a motif's events falling outside its intended region. | lower is better |
| `∥R∥` (格) | Number of grid cells changed by an edit (edit magnitude). | — |
| `编辑影响率` / `非目标保持率` | Edit-impact rate / non-target preservation rate. | higher is better |

Where a column header stacks a group label and a metric (e.g. `full V_h`, `no_repair V_h`),
the prefix is the experimental **setting** and the suffix is the metric.

---

## File index

### C.4 — Baseline comparison (per-case)

| File | Source table | Rows × Cols | Description |
|---|---|---|---|
| `C4_baseline/S11_protocolA_inputs.csv` | 表 S11 | 11 × 2 | Protocol-A input set (N=10 historical inputs): 编号, 测试输入 |
| `C4_baseline/S11a_full_vs_llmdirect.csv` | 表 S11a | 31 × 7 | Full system vs. LLM-Direct vs. LLM-Direct+Repair, per case: 案例, 方法, V_h, V_c, T, Type-Coverage↑, TAP↑ |
| `C4_baseline/S11b_t2i_vs_random.csv` | 表 S11b | 21 × 7 | T2I + color quantization vs. Random Valid Map, per case (same columns as S11a) |
| `C4_baseline/S11c_plangrid.csv` | 表 S11c | 31 × 7 | Internal strong baseline (Plan-Grid series), per case (same columns as S11a) |
| `C4_baseline/S12_module_ablation.csv` | 表 S12 | 4 × 6 | Extra-module ablation summary (mean over Baseline Case 01–10): 方法, V_h, V_c, T, Type-Coverage↑, TAP↑ |

### C.6 — Stress testing (per-case)

| File | Source table | Rows × Cols | Description |
|---|---|---|---|
| `C6_stress/S13_stress_inputs.csv` | 表 S13 | 25 × 3 | Stress-test input set and risk scenario: 编号, 输入描述, 风险场景 |
| `C6_stress/S14_stress_percase.csv` | 表 S14 | 25 × 9 | Per-case results, 24 inputs × 2 settings (`full`, `no_repair`) × metrics {V_h, V_c, N_t, T} |

### C.8 — Ablation (per-case)

| File | Source table | Rows × Cols | Description |
|---|---|---|---|
| `C8_ablation/S15_ablation_inputs.csv` | 表 S15 | 9 × 3 | Ablation input set: 编号, 输入描述, 风险类型 |
| `C8_ablation/S15b_nested_inputs.csv` | 表 S15b | 4 × 3 | Nested input set for the event-level guard ablation: 编号, 层级结构（父→子）, 风险类型 |
| `C8_ablation/S16_ablation_percase.csv` | 表 S16 | 5 × 7 | Ablation per-case results + summary: 设置, 案例数, 案例数(V_h=0), 案例数(V_c=0), 案例数(V_h=V_c=0), 平均 V_c, 平均 T |
| `C8_ablation/S16b_repair_semantic_percase.csv` | 表 S16b | 10 × 7 | Semantic preservation before/after repair (`full` vs. `no_repair`): 案例, 逐格一致率, 事件保留率, 事件降级率, 事件删除率, V_h+V_c(full), V_h+V_c(no_repair) |
| `C8_ablation/S16c_control_percase_protocolB.csv` | 表 S16c | 47 × 6 | Internal-baseline controlled comparison (Protocol B): Case, Texture motif, Region IoU, Leakage, Grouping completeness, V_h — each as `Plan-Grid / (+Repair) / Ours` |
| `C8_ablation/S16d_event_guard_percase.csv` | 表 S16d | 11 × 8 | Event-level structural guard ablation: 案例, 纹理 motif(父级), 有效作用域格数, 归属格数, Region IoU, 泄漏率, 父子包含率, 成组完整率 |
| `C8_ablation/S16e_region_iou_sensitivity.csv` | 表 S16e | 4 × 5 | Region IoU sensitivity to closing structuring-element size: 设置, 无闭运算, 3×3, 5×5(正文设置), 7×7 |
| `C8_ablation/S16f_geometry_ownership_crosscheck.csv` | 表 S16f | 11 × 6 | Cross-check of geometric post-hoc ownership vs. compiler-internal event ownership: 案例, motif(纹理), IoU(几何/内部), 泄漏(几何/内部) |

### C.10 — Editable generation (per-case)

| File | Source table | Rows × Cols | Description |
|---|---|---|---|
| `C10_editable/S18_text_reparse_percase.csv` | 表 S18 | 7 × 8 | Group B — text-reparse editing: 案例, 编辑维度, V_h, V_c, ∥R∥(格), 编辑影响率, 非目标保持率, 主要变化 |
| `C10_editable/S18b_native_edit_percase.csv` | 表 S18b | 8 × 10 | Group A — native editing (direct PatternPlan field change, no re-parse): 案例, 编辑维度, 修改字段, V_h, V_c, ∥R∥(格), 内变化 R, 外变化 R, 编辑影响率, 非目标保持率 |

### Appendix S — External-baseline comparison (n = 30)

| File | Source table | Rows × Cols | Description |
|---|---|---|---|
| `appendixS_external/S22_external_full_metrics.csv` | Table S22 | 9 × 10 | Full metrics per method: Method, Tier, Manuf. rate↑, True-knit rate↑, Fidelity(merged)↑, Fidelity(strict), Type-Cov↑, Mean V_h↓, Mean V_c↓, t(s)↓ |
| `appendixS_external/S23_strict_vs_merged_fidelity.csv` | Table S23 | 9 × 5 | Strict vs. family-merged fidelity: Method, Tier, Fidelity(strict), Fidelity(merged), Δ |
| `appendixS_external/S24_quantizer_sensitivity.csv` | Table S24 | 6 × 9 | Q1 (15-color NN) vs. Q2 (k-means adaptive palette) sensitivity |
| `appendixS_external/S25_control.csv` | Table S25 | 6 × 8 | Third quantizer Q3 (human "semantic-friendly" assignment) as control |
| `appendixS_external/S26_unmanufacturable_cases.csv` | Table S26 | 3 × 6 | The two non-manufacturable cases of the full system: ID, Prompt(zh), V_h, V_c, Fidelity(strict), Attribution |
| `appendixS_external/S27_positive_control.csv` | Table S27 | 5 × 2 | Positive control — the quantizer itself is sound (30-case): Check, Result |
| `appendixS_external/S28_not_degenerate.csv` | Table S28 | 6 × 4 | Raw generations are not degenerate (5 models × 30): unique colors / pixel std (min/median/max) |
| `appendixS_external/S29_quantization_gap.csv` | Table S29 | 6 × 3 | Representation gap: pixel-to-nearest-action-color distance |
| `appendixS_external/S30_pixart_action_distribution.csv` | Table S30 | 9 × 2 | PixArt-Σ quantized action distribution over 30 cases (48,000 cells): Action, Share |
| `appendixS_external/S31_percase_locatable.csv` | Table S31 | 14 × 4 | Representative per-case checks (locatable in `outputs/runs/sota_final_table30/per_case/`) |
| `appendixS_external/S32_reproduction_shift25.csv` | Table S32 | 31 × 5 | Full per-case positive control — quantizer soundness; reproduction after ±25 shift |
| `appendixS_external/S33_external_percase_181rows.csv` | Table S33 | 181 × 10 | **Largest table.** Full per-case matrix (30 inputs × 6 metrics × 8 methods = 240 cells), transcribed from `outputs/runs/sota_final_table30/per_case/per_case_pivot30.csv`. Re-aggregating this grid reproduces Table 4 of the paper exactly. Columns: Case, Metric, SD3-medium, PixArt-Σ, VAR-d16, SD v1.5, SDXL-Turbo, LLM-Direct, Random, Ours |

---

## Notes

- The **181-row per-case matrix (`S33`)** belongs to **Appendix S (external-baseline comparison)**,
  not to Section C.8. Section C.8's largest per-case table is `S16c` (47 rows).
- `S33` is a tidy long-format grid: each row is one (Case, Metric) pair, and the 8 method columns
  hold that metric's value. Aggregating over the 30 cases reproduces the paper's Table 4.
- Case identifiers (`sem_*`, `Baseline Case NN`, `Stress Case NN`, `Ablation Case NN`,
  `Description-Edit Case NN`, `Field-Edit Case NN`) match the display-name mapping in
  Supplementary Table S21.
