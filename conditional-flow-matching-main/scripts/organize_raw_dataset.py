"""Organize raw paired dataset files into category folders.

Raw layout:
  dataset_raw/color_maps-raw/*.png
  dataset_raw/simulations-raw/*.jpg

Target layout:
  dataset_raw/color_maps/<Category>/*.png
  dataset_raw/simulations/<Category>/*.jpg

Only exact stem pairs are kept. Unpaired raw files are deleted when --apply is
used. Category is inferred from the existing target category folders by filename
prefix, e.g. Cable1_001_0_0 -> Cable.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTS_COLOR = {".png"}
IMAGE_EXTS_SIM = {".jpg", ".jpeg"}


@dataclass
class Plan:
    matched: list[tuple[Path, Path, str]]
    unpaired_colors: list[Path]
    unpaired_sims: list[Path]
    unknown_category: list[Path]


def collect_files(path: Path, exts: set[str]) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for item in path.iterdir():
        if not item.is_file():
            continue
        if item.suffix.lower() not in exts:
            continue
        files[item.stem] = item
    return files


def infer_category(stem: str, categories: list[str]) -> str | None:
    low = stem.lower()
    matches = [cat for cat in categories if low.startswith(cat.lower())]
    if not matches:
        return None
    return max(matches, key=len)


def build_plan(root: Path) -> Plan:
    color_raw = root / "color_maps-raw"
    sim_raw = root / "simulations-raw"
    color_target = root / "color_maps"

    if not color_raw.exists():
        raise FileNotFoundError(f"Missing raw color directory: {color_raw}")
    if not sim_raw.exists():
        raise FileNotFoundError(f"Missing raw simulation directory: {sim_raw}")
    if not color_target.exists():
        raise FileNotFoundError(f"Missing target color directory: {color_target}")

    categories = sorted([p.name for p in color_target.iterdir() if p.is_dir()])
    colors = collect_files(color_raw, IMAGE_EXTS_COLOR)
    sims = collect_files(sim_raw, IMAGE_EXTS_SIM)

    matched = []
    unknown_category = []
    paired_stems = sorted(set(colors) & set(sims))
    for stem in paired_stems:
        category = infer_category(stem, categories)
        if category is None:
            unknown_category.append(colors[stem])
            unknown_category.append(sims[stem])
            continue
        matched.append((colors[stem], sims[stem], category))

    matched_stems = {c.stem for c, _, _ in matched}
    unknown_stems = {p.stem for p in unknown_category}
    unpaired_colors = [
        p for stem, p in colors.items()
        if stem not in matched_stems and stem not in unknown_stems
    ]
    unpaired_sims = [
        p for stem, p in sims.items()
        if stem not in matched_stems and stem not in unknown_stems
    ]

    return Plan(
        matched=matched,
        unpaired_colors=sorted(unpaired_colors),
        unpaired_sims=sorted(unpaired_sims),
        unknown_category=sorted(unknown_category),
    )


def replace_move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))


def apply_plan(root: Path, plan: Plan) -> None:
    for color_path, sim_path, category in plan.matched:
        color_dst = root / "color_maps" / category / color_path.name
        sim_dst = root / "simulations" / category / sim_path.name
        replace_move(color_path, color_dst)
        replace_move(sim_path, sim_dst)

    for path in plan.unpaired_colors + plan.unpaired_sims + plan.unknown_category:
        if path.exists():
            path.unlink()


def print_plan(plan: Plan) -> None:
    print("Raw dataset organization plan")
    print(f"  matched pairs:       {len(plan.matched)}")
    print(f"  unpaired colors:     {len(plan.unpaired_colors)}")
    print(f"  unpaired simulations:{len(plan.unpaired_sims)}")
    print(f"  unknown category:    {len(plan.unknown_category)}")
    by_cat: dict[str, int] = {}
    for _, _, category in plan.matched:
        by_cat[category] = by_cat.get(category, 0) + 1
    print("  matched by category:")
    for category in sorted(by_cat):
        print(f"    {category}: {by_cat[category]}")

    for label, items in [
        ("unpaired color examples", plan.unpaired_colors),
        ("unpaired simulation examples", plan.unpaired_sims),
        ("unknown category examples", plan.unknown_category),
    ]:
        if items:
            print(f"  {label}:")
            for item in items[:10]:
                print(f"    {item.name}")
            if len(items) > 10:
                print(f"    ... {len(items) - 10} more")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("dataset_raw"),
        help="Path to dataset_raw",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Move matched files into category folders and delete unpaired raw files",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    plan = build_plan(root)
    print_plan(plan)

    if args.apply:
        apply_plan(root, plan)
        print("Applied: matched files moved, unpaired raw files deleted.")
    else:
        print("Dry run only. Re-run with --apply to modify files.")


if __name__ == "__main__":
    main()
