# -*- coding: utf-8 -*-
"""Paired statistics for the expanded Protocol-B controlled comparison.

Pairs region_metrics rows by (input, motif_id) between the event arm (Ours) and
the dense arm (Plan-Grid). Reports Wilcoxon signed-rank p, bootstrap 95% CI of
the mean paired difference, Cohen's d_z, and achieved power, both overall and
for the nested subgroup (motifs that have a parent_id -> hierarchical regions,
which is what the original ABL-01..08 cases all exercised).
"""
from __future__ import annotations
import csv, math, sys
from collections import defaultdict
import numpy as np

OURS = sys.argv[1] if len(sys.argv) > 1 else "outputs/analysis/region_expand_ours.csv"
PG = sys.argv[2] if len(sys.argv) > 2 else "outputs/analysis/region_expand_plangrid.csv"
METRICS = ["region_iou", "leakage", "wave_pair_rate", "containment"]


def load(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    out = {}
    for r in rows:
        case = r["case"]                       # sem_XX_event / sem_XX_dense
        sem = case.rsplit("_", 1)[0]           # strip arm suffix
        key = (sem, r["motif_id"])
        out[key] = r
    return out


def fnum(r, k):
    v = r.get(k, "")
    return float(v) if v not in ("", None) else None


def wilcoxon(d):
    d = np.asarray([x for x in d if x != 0.0])
    n = len(d)
    if n < 6:
        return float("nan"), n
    r = np.argsort(np.argsort(np.abs(d))) + 1
    # average ranks for ties
    absd = np.abs(d)
    ranks = np.empty(n)
    i = 0
    order = np.argsort(absd)
    while i < n:
        j = i
        while j + 1 < n and absd[order[j + 1]] == absd[order[i]]:
            j += 1
        avg = np.mean([k + 1 for k in range(i, j + 1)])
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    wpos = ranks[d > 0].sum()
    wneg = ranks[d < 0].sum()
    W = min(wpos, wneg)
    mu = n * (n + 1) / 4.0
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    z = (W - mu) / sd if sd else float("nan")
    # two-sided normal approx
    p = math.erfc(abs(z) / math.sqrt(2)) if not math.isnan(z) else float("nan")
    return p, n


def boot_ci(d, iters=10000, seed=0):
    d = np.asarray(d, float)
    rng = np.random.default_rng(seed)
    n = len(d)
    means = rng.choice(d, size=(iters, n), replace=True).mean(axis=1)
    return np.percentile(means, 2.5), np.percentile(means, 97.5)


def report(label, keys, ours, pg):
    print(f"\n===== {label}  (n_motifs paired = {len(keys)}) =====")
    for m in METRICS:
        pairs = []
        for k in keys:
            a = fnum(ours[k], m) if k in ours else None
            b = fnum(pg[k], m) if k in pg else None
            if a is not None and b is not None:
                pairs.append((a, b))
        if len(pairs) < 3:
            print(f"  {m:16s}: insufficient pairs ({len(pairs)})")
            continue
        a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
        diff = a - b
        nz = diff[diff != 0]
        md = diff.mean()
        lo, hi = boot_ci(diff) if len(diff) >= 8 else (float('nan'), float('nan'))
        p, nn = wilcoxon(diff.tolist())
        dz = md / diff.std(ddof=1) if diff.std(ddof=1) > 0 else float("nan")
        # power for paired t at alpha .05 given observed dz, n
        try:
            from scipy import stats as st
            ncp = abs(dz) * math.sqrt(len(diff))
            pw = 1 - st.t.cdf(st.t.ppf(0.975, len(diff) - 1), len(diff) - 1, ncp) if not math.isnan(dz) else float('nan')
        except Exception:
            pw = float("nan")
        print(f"  {m:16s}: Ours={a.mean():.3f} PG={b.mean():.3f} diff={md:+.3f} "
              f"CI95=({lo:+.3f},{hi:+.3f}) Wilcoxon p={p:.4g} (n={nn}, nonzero={len(nz)}) "
              f"d_z={dz:+.2f} power~{pw:.2f}")


def main():
    ours = load(OURS); pg = load(PG)
    all_keys = sorted(set(ours) & set(pg))
    # nested subgroup: motif has parent_id in ours arm
    nested = [k for k in all_keys if (ours[k].get("parent_id") or "").strip()]
    report("ALL paired scoped-textured motifs", all_keys, ours, pg)
    report("NESTED subgroup (motif has parent_id)", nested, ours, pg)
    # per-input aggregate of region_iou (mean over motifs), inputs present in both
    inputs = sorted({k[0] for k in all_keys})
    print(f"\ninputs paired: {len(inputs)}; nested-motif inputs: {len({k[0] for k in nested})}")


if __name__ == "__main__":
    main()
