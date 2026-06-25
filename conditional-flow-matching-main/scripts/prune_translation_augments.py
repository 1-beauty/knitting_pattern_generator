"""Prune translation-augmented raw image pairs by filename.

The raw dataset uses paired files:
  dataset_raw/color_maps/<category>/<stem>.png
  dataset_raw/simulations/<category>/<stem>.jpg

Many stems end with two numeric translation offsets, for example:
  Cable1_048_0_0
  Cable1_048_6_11

This script removes unpaired files first. For categories with enough paired
images, it then groups files by the stem without the final two offsets
(`Cable1_048` above), keeps the original `_0_0` when present, and keeps
a configurable number of additional translated variants. Small categories are
kept intact so rare stitch types do not get thinned further.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


STEM_RE = re.compile(r"^(?P<base>.+)_(?P<dy>\d+)_(?P<dx>\d+)$")


@dataclass(frozen=True)
class Pair:
    category: str
    base: str
    dy: int
    dx: int
    stem: str
    color_path: Path
    sim_path: Path


@dataclass(frozen=True)
class FileAction:
    action: str
    reason: str
    category: str
    base: str
    dy: str
    dx: str
    stem: str
    color_path: str
    sim_path: str
    paths: tuple[Path, ...]


def parse_stem(stem: str):
    match = STEM_RE.match(stem)
    if match is None:
        return None
    return match.group("base"), int(match.group("dy")), int(match.group("dx"))


def category_from_raw_path(path: Path, raw_dir: Path) -> str:
    try:
        rel = path.relative_to(raw_dir)
    except ValueError:
        return ""
    return rel.parts[1] if len(rel.parts) >= 3 else ""


def collect_pairs(raw_dir: Path) -> tuple[list[Pair], list[Path], list[Path], list[Path]]:
    color_root = raw_dir / "color_maps"
    sim_root = raw_dir / "simulations"
    pairs: list[Pair] = []
    unmatched_names: list[Path] = []
    missing_sim: list[Path] = []
    matched_sim_paths: set[Path] = set()

    for color_path in sorted(color_root.rglob("*.png")):
        rel = color_path.relative_to(color_root)
        if len(rel.parts) < 2:
            unmatched_names.append(color_path)
            continue

        category = rel.parts[0]
        parsed = parse_stem(color_path.stem)
        if parsed is None:
            unmatched_names.append(color_path)
            continue

        base, dy, dx = parsed
        sim_path = sim_root / category / f"{color_path.stem}.jpg"
        if not sim_path.exists():
            missing_sim.append(color_path)
            continue

        matched_sim_paths.add(sim_path)
        pairs.append(
            Pair(
                category=category,
                base=base,
                dy=dy,
                dx=dx,
                stem=color_path.stem,
                color_path=color_path,
                sim_path=sim_path,
            )
        )

    orphan_sims = [
        sim_path
        for sim_path in sorted(sim_root.rglob("*.jpg"))
        if sim_path not in matched_sim_paths
    ]

    return pairs, unmatched_names, missing_sim, orphan_sims


def choose_keep(group: list[Pair], keep_shifts: int) -> set[str]:
    originals = [p for p in group if p.dy == 0 and p.dx == 0]
    shifted = [p for p in group if not (p.dy == 0 and p.dx == 0)]

    keep: list[Pair] = []
    if originals:
        keep.append(sorted(originals, key=lambda p: p.stem)[0])

    # Keep small offsets first; they are usually the least distorted variants.
    shifted = sorted(shifted, key=lambda p: (p.dy * p.dy + p.dx * p.dx, p.dy, p.dx, p.stem))
    keep.extend(shifted[: max(0, keep_shifts)])

    # If there is no `_0_0` file, still keep one representative.
    if not keep and group:
        keep.append(sorted(group, key=lambda p: (p.dy * p.dy + p.dx * p.dx, p.stem))[0])

    return {p.stem for p in keep}


def move_file(src: Path, raw_dir: Path, backup_dir: Path) -> Path:
    rel = src.relative_to(raw_dir)
    dst = backup_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"Backup target already exists: {dst}")
    shutil.move(str(src), str(dst))
    return dst


def file_action_from_pair(action: str, reason: str, pair: Pair) -> FileAction:
    return FileAction(
        action=action,
        reason=reason,
        category=pair.category,
        base=pair.base,
        dy=str(pair.dy),
        dx=str(pair.dx),
        stem=pair.stem,
        color_path=str(pair.color_path),
        sim_path=str(pair.sim_path),
        paths=(pair.color_path, pair.sim_path),
    )


def file_action_for_single(action: str, reason: str, path: Path, raw_dir: Path) -> FileAction:
    parsed = parse_stem(path.stem)
    base, dy, dx = ("", "", "")
    if parsed is not None:
        base, dy_i, dx_i = parsed
        dy, dx = str(dy_i), str(dx_i)

    rel = path.relative_to(raw_dir)
    color_path = str(path) if rel.parts[0] == "color_maps" else ""
    sim_path = str(path) if rel.parts[0] == "simulations" else ""
    return FileAction(
        action=action,
        reason=reason,
        category=category_from_raw_path(path, raw_dir),
        base=base,
        dy=dy,
        dx=dx,
        stem=path.stem,
        color_path=color_path,
        sim_path=sim_path,
        paths=(path,),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune translation-augmented raw dataset image pairs."
    )
    parser.add_argument("--raw-dir", default="dataset_raw", type=Path)
    parser.add_argument("--manifest", default="translation_prune_manifest.csv", type=Path)
    parser.add_argument(
        "--keep-shifts",
        default=2,
        type=int,
        help="Number of non-zero translation variants to keep per base image.",
    )
    parser.add_argument(
        "--min-group-size",
        default=2,
        type=int,
        help="Only prune groups with at least this many paired files.",
    )
    parser.add_argument(
        "--min-category-pairs",
        default=1000,
        type=int,
        help=(
            "Only prune translation variants in categories with at least this "
            "many valid pairs. Smaller categories are kept intact."
        ),
    )
    parser.add_argument(
        "--keep-unpaired",
        action="store_true",
        help="Keep unpaired files instead of pruning them.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually move/delete files.")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete files instead of moving them to --backup-dir. Requires --apply.",
    )
    parser.add_argument(
        "--backup-dir",
        default=Path("dataset_raw_pruned_backup"),
        type=Path,
        help="Where pruned files are moved when --apply is used without --delete.",
    )
    args = parser.parse_args()

    raw_dir = args.raw_dir.resolve()
    backup_dir = args.backup_dir.resolve()
    pairs, unmatched_names, missing_sim, orphan_sims = collect_pairs(raw_dir)

    groups: dict[tuple[str, str], list[Pair]] = defaultdict(list)
    category_counts = Counter(pair.category for pair in pairs)
    for pair in pairs:
        groups[(pair.category, pair.base)].append(pair)

    actions: list[FileAction] = []
    kept_pairs = 0
    pruned_pairs = 0
    kept_small_category_pairs = 0

    for (category, base), group in sorted(groups.items()):
        if category_counts[category] < args.min_category_pairs:
            keep_stems = {p.stem for p in group}
            reason = "small_category"
            kept_small_category_pairs += len(group)
        elif len(group) < args.min_group_size:
            keep_stems = {p.stem for p in group}
            reason = "small_group"
        else:
            keep_stems = choose_keep(group, args.keep_shifts)
            reason = "translation_prune"

        for pair in sorted(group, key=lambda p: (p.dy, p.dx, p.stem)):
            action = "keep" if pair.stem in keep_stems else "prune"
            if action == "keep":
                kept_pairs += 1
            else:
                pruned_pairs += 1
            actions.append(file_action_from_pair(action, reason, pair))

    unpaired_action = "keep" if args.keep_unpaired else "prune"
    for path in unmatched_names:
        actions.append(
            file_action_for_single(unpaired_action, "unmatched_color_name", path, raw_dir)
        )
    for path in missing_sim:
        actions.append(
            file_action_for_single(unpaired_action, "missing_simulation", path, raw_dir)
        )
    for path in orphan_sims:
        actions.append(
            file_action_for_single(unpaired_action, "orphan_simulation", path, raw_dir)
        )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "action",
                "reason",
                "category",
                "base",
                "dy",
                "dx",
                "stem",
                "color_path",
                "sim_path",
            ]
        )
        for item in actions:
            writer.writerow(
                [
                    item.action,
                    item.reason,
                    item.category,
                    item.base,
                    item.dy,
                    item.dx,
                    item.stem,
                    item.color_path,
                    item.sim_path,
                ]
            )

    if args.apply:
        for item in actions:
            if item.action != "prune":
                continue
            for path in item.paths:
                if args.delete:
                    path.unlink()
                else:
                    move_file(path, raw_dir, backup_dir)

    mode = "APPLY" if args.apply else "DRY RUN"
    disposition = "deleted" if args.delete else f"moved to {backup_dir}"
    print(f"Mode: {mode}")
    print(f"Paired files found: {len(pairs)}")
    print(f"Groups found: {len(groups)}")
    print(f"Category prune threshold: {args.min_category_pairs} pairs")
    print("Category pair counts:")
    for category, count in sorted(category_counts.items()):
        policy = "prune translations" if count >= args.min_category_pairs else "keep category"
        print(f"  {category}: {count} ({policy})")
    print(f"Kept pairs: {kept_pairs}")
    print(f"Pruned pairs: {pruned_pairs}")
    print(f"Kept pairs due to small categories: {kept_small_category_pairs}")
    print(f"Unmatched color-map names: {len(unmatched_names)} ({unpaired_action})")
    print(f"Color maps missing simulations: {len(missing_sim)} ({unpaired_action})")
    print(f"Orphan simulations: {len(orphan_sims)} ({unpaired_action})")
    print(f"Manifest: {args.manifest.resolve()}")
    if args.apply:
        print(f"Pruned files were {disposition}.")
    else:
        print("No files changed. Re-run with --apply after checking the manifest.")
    print("After pruning, regenerate dataset_processed/dataset.h5 with data/preprocess.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
