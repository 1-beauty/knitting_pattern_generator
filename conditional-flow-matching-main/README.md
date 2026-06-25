# Knitting Simulation via Conditional Flow Matching

This module maps knitting color-code maps to simulation-style knitted images.

It is the second stage of the full project:

```text
text prompt -> color-code map -> simulation image
```

## Main Files

- `knitting/train.py`: training entry point for Stage 1-4 models.
- `knitting/inference.py`: inference entry point for a color-code map.
- `knitting/evaluate.py`: patch-level evaluation.
- `knitting/evaluate_full_image.py`: full-image evaluation.
- `knitting/models.py`: neighbor-aware conditioning modules.
- `data/preprocess.py`: raw color-map/simulation pair preprocessing.
- `configs/`: stage-specific training configs.
- `assets/instructions.json`: 15 knitting instruction definitions and colors.
- `torchcfm/`: local Conditional Flow Matching implementation and UNet backbone.

## Inference

Run this module directly:

```bash
python knitting/inference.py --stage 4 --input dataset_raw/color_maps/Cable/Cable1_001_0_0.png
```

Or run from the repository root through the unified script:

```bash
python ../run_pipeline.py simulate --input outputs/runs/20260601_154724/color_map/pattern_sim_input.png --stage 4
```

## Stages

- Stage 1: center-instruction baseline.
- Stage 2: neighbor-aware conditioning.
- Stage 3: physics-aware feature conditioning.
- Stage 4: final structure-aware model with adaptive noise, boundary loss, and structure loss.

## Notes

This directory was adapted from a TorchCFM codebase. The retained `torchcfm/` package provides the flow-matching objective and UNet implementation, while the `knitting/`, `data/`, `configs/`, and `assets/` directories contain the knitting-specific method.
