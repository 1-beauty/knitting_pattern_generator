from generation.visual_types import VisualRegion, VisualSpec
from generation.visual_to_realization import VisualToRealizationConverter
from generation.event_planner import EventPlanner
from generation.action_builder import ActionBuilder
from generation.aesthetic_pass import AestheticPass
from generation.mask_utils import point_in_mask
from core import actions


def _build_grid_for_region(vr: VisualRegion):
    conv = VisualToRealizationConverter()
    plan = conv.convert(VisualSpec(regions=[vr]))
    planner = EventPlanner(grid_size=40)
    events = planner.plan(plan)
    builder = ActionBuilder(grid_size=40)
    grid = builder.build(plan, events)
    return grid, plan


def _count_special(grid):
    special = actions.split_ids() | actions.tuck_ids() | actions.miss_ids() | actions.transfer_ids()
    cnt = 0
    rows, cols = grid.shape
    for i in range(rows):
        for j in range(cols):
            if int(grid[i, j]) in special:
                cnt += 1
    return cnt


def test_aesthetic_reduces_isolated_specials_for_various_shapes():
    shapes = [
        ("circle", "wave_tuck"),
        ("rectangle", "wave_tuck"),
        ("diamond", "cable"),
        ("hexagon", "wave_tuck"),
        ("triangle", "wave_tuck"),
        ("stripe", "wave_tuck"),
        ("column", "wave_tuck"),
        ("oval", "wave_tuck"),
    ]

    aesthetic = AestheticPass()

    for shape_name, effect in shapes:
        vr = VisualRegion(
            region_id=f"test_{shape_name}",
            visual_shape=shape_name,
            visual_effect=effect,
            layout_role="center",
            placement={"center": [20, 20], "size": 10, "mask_shape": shape_name},
            params={},
        )

        grid_before, plan = _build_grid_for_region(vr)
        special_before = _count_special(grid_before)

        grid_after = aesthetic.apply(grid_before, realization_plan=plan)
        special_after = _count_special(grid_after)

        # 美化应不增加特殊动作数量，并且在多数情况下减少或相同
        assert special_after <= special_before, f"{shape_name}: special actions increased ({special_before} -> {special_after})"

