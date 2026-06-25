import json
import math

from generation.pattern_plan import PatternPlanEngine
from generation.event_planner import EventPlanner
from generation.mask_utils import point_in_mask
from generation.visual_to_realization import VisualToRealizationConverter


def test_wave_edit_changes_existing_motif_size():
    engine = PatternPlanEngine()
    plan = engine.from_prompt("中心波浪")
    before_size = plan.get_motif("main").region["size"]

    edited = engine.from_prompt("波浪更大一点", current_plan=plan)
    after = edited.get_motif("main")

    assert after.motif_type == "wave"
    assert after.region["size"] > before_size


def test_add_eyelet_keeps_previous_motif_and_adds_lace():
    engine = PatternPlanEngine()
    plan = engine.from_prompt("中心波浪")

    edited = engine.from_prompt("中间加一点镂空", current_plan=plan)

    assert any(m.motif_id == "main" for m in edited.motifs)
    assert any(m.effect == "lace" for m in edited.motifs)


def test_random_plan_renders_to_visual_spec():
    engine = PatternPlanEngine()
    plan = engine.from_prompt("随机生成一个镂空波浪")
    spec = engine.render_visual_spec(plan)

    assert spec.regions[0].layout_role == "ground"
    assert len(spec.regions) >= 2


def test_nested_diamond_wave_is_clipped_to_parent_shape():
    engine = PatternPlanEngine()
    plan = engine.from_prompt("菱形内部波浪条纹")
    spec = engine.render_visual_spec(plan)
    realization = VisualToRealizationConverter().convert(spec)
    inner = realization.get_region("inner")

    assert inner is not None
    assert inner.placement.get("parent_id") == "outer"
    assert inner.placement.get("mask_shape") == "diamond"

    events = EventPlanner(grid_size=40).plan(realization)
    inner_events = [e for e in events if e.region_id == "inner"]
    assert inner_events
    for event in inner_events:
        assert point_in_mask(event.row, event.col, inner.placement, 40)


def test_nested_star_wave_keeps_star_mask():
    engine = PatternPlanEngine()
    data = {
        "layout_type": "centered",
        "motifs": [
            {
                "motif_id": "star_frame",
                "motif_type": "frame",
                "effect": "plain",
                "region": {"center": [20, 20], "size": 18, "shape": "star"},
                "role": "border",
            },
            {
                "motif_id": "inner_wave",
                "motif_type": "wave",
                "effect": "wave_tuck",
                "region": {"center": [20, 20], "size": 14, "shape": "star"},
                "role": "center",
                "parent_id": "star_frame",
            },
        ],
    }
    plan = engine.validate(engine._data_to_plan(data, current_plan=None))
    realization = VisualToRealizationConverter().convert(engine.render_visual_spec(plan))
    inner = realization.get_region("inner_wave")

    assert inner.placement.get("mask_shape") == "star"
    assert inner.placement.get("parent_id") == "star_frame"
    events = EventPlanner(grid_size=40).plan(realization)
    assert [e for e in events if e.region_id == "inner_wave"]


def test_allover_diamond_mesh_uses_repeated_mask_not_full_canvas():
    engine = PatternPlanEngine()
    data = {
        "layout_type": "allover_repeat",
        "motifs": [
            {
                "motif_id": "diamond_repeat",
                "motif_type": "diamond",
                "effect": "plain",
                "region": {"type": "full"},
                "params": {"period_x": 10, "period_y": 10, "size": 5},
                "role": "allover",
            },
            {
                "motif_id": "mesh_inside",
                "motif_type": "mesh",
                "effect": "lace",
                "region": {"type": "full", "shape": "diamond"},
                "params": {"period_x": 10, "period_y": 10},
                "role": "allover",
                "parent_id": "diamond_repeat",
            },
        ],
    }
    plan = engine.validate(engine._data_to_plan(data, current_plan=None))
    realization = VisualToRealizationConverter().convert(engine.render_visual_spec(plan))
    mesh = realization.get_region("mesh_inside")

    assert mesh.placement.get("repeat") is True
    assert mesh.placement.get("mask_shape") == "diamond"
    events = EventPlanner(grid_size=40).plan(realization)
    mesh_events = [e for e in events if e.region_id == "mesh_inside"]
    assert mesh_events
    assert len(mesh_events) < 1600
    for event in mesh_events:
        assert point_in_mask(event.row, event.col, mesh.placement, 40)


def test_complex_framed_diamond_reparents_inner_texture_to_diamond():
    engine = PatternPlanEngine()
    text = "带矩形边框的中心菱形，菱形内部是波浪条纹，两侧为罗纹边带"
    data = {
        "layout_type": "framed",
        "motifs": [
            {"motif_id": "frame", "motif_type": "frame", "effect": "plain", "region": {"center": [20, 20], "size": 16}, "role": "border"},
            {"motif_id": "diamond_center", "motif_type": "diamond", "effect": "plain", "region": {"center": [20, 20], "size": 16}, "role": "center"},
            {"motif_id": "wave_inside", "motif_type": "wave", "effect": "wave_tuck", "region": {"center": [20, 20], "size": 12, "shape": "frame"}, "role": "center", "parent_id": "frame"},
            {"motif_id": "left_rib", "motif_type": "stripe", "effect": "rib", "region": {"x_range": [0, 4], "y_range": [0, 40]}, "role": "border"},
            {"motif_id": "right_rib", "motif_type": "stripe", "effect": "rib", "region": {"x_range": [36, 40], "y_range": [0, 40]}, "role": "border"},
        ],
    }
    plan = engine._data_to_plan(data, current_plan=None)
    engine._repair_plan_from_text(plan, text)
    plan = engine.validate(plan)

    wave = plan.get_motif("wave_inside")
    assert wave.parent_id == "diamond_center"
    assert wave.region.get("shape") == "diamond"
    assert plan.get_motif("left_rib").role == "side_band"
    assert plan.get_motif("left_rib").region.get("side") == "left"
    assert plan.get_motif("right_rib").role == "side_band"
    assert plan.get_motif("right_rib").region.get("side") == "right"


def test_background_role_and_hexagon_center_are_repaired():
    engine = PatternPlanEngine()
    text = "中心六边形蜂巢纹理，周围搭配波浪吊目背景"
    data = {
        "layout_type": "centered",
        "motifs": [
            {"motif_id": "honeycomb_center", "motif_type": "panel", "effect": "honeycomb", "region": {"center": [20, 20], "size": 16}, "role": "center"},
            {"motif_id": "wave_background", "motif_type": "allover", "effect": "wave_tuck", "region": {"type": "full"}, "role": "background"},
        ],
    }
    plan = engine._data_to_plan(data, current_plan=None)
    engine._repair_plan_from_text(plan, text)
    plan = engine.validate(plan)

    assert plan.get_motif("honeycomb_center").motif_type == "hexagon"
    assert plan.get_motif("honeycomb_center").region.get("shape") == "hexagon"
    assert plan.get_motif("wave_background").role == "allover"


def test_inner_mesh_parented_to_side_band_is_repaired_to_diamond():
    engine = PatternPlanEngine()
    text = "中心大菱形，菱形边缘是麻花轮廓，内部为稀疏镂空网眼，左右两侧有罗纹边带"
    data = {
        "layout_type": "framed",
        "motifs": [
            {"motif_id": "diamond_outline", "motif_type": "diamond", "effect": "cable", "region": {"center": [20, 20], "size": 18}, "role": "center"},
            {"motif_id": "inner_mesh", "motif_type": "mesh", "effect": "lace", "region": {"center": [20, 20], "size": 12, "shape": "stripe"}, "role": "center", "parent_id": "left_rib"},
            {"motif_id": "left_rib", "motif_type": "stripe", "effect": "rib", "region": {"x_start": 0, "x_end": 5}, "role": "border"},
            {"motif_id": "right_rib", "motif_type": "stripe", "effect": "rib", "region": {"x_start": 35, "x_end": 40}, "role": "border"},
        ],
    }
    plan = engine._data_to_plan(data, current_plan=None)
    engine._repair_plan_from_text(plan, text)
    plan = engine.validate(plan)

    mesh = plan.get_motif("inner_mesh")
    assert mesh.parent_id == "diamond_outline"
    assert mesh.region.get("shape") == "diamond"
    assert plan.get_motif("left_rib").role == "side_band"
    assert plan.get_motif("left_rib").parent_id is None


def test_x1_x2_side_band_width_is_respected():
    engine = PatternPlanEngine()
    data = {
        "motifs": [
            {"motif_id": "rib_left", "motif_type": "stripe", "effect": "rib", "region": {"x1": 0, "x2": 4, "y1": 0, "y2": 39}, "role": "side_band"},
            {"motif_id": "rib_right", "motif_type": "stripe", "effect": "rib", "region": {"x1": 36, "x2": 39, "y1": 0, "y2": 39}, "role": "side_band"},
        ],
    }
    plan = engine.validate(engine._data_to_plan(data, current_plan=None))

    assert plan.get_motif("rib_left").region.get("width") == 4
    assert plan.get_motif("rib_left").region.get("side") == "left"
    assert plan.get_motif("rib_right").region.get("width") == 3
    assert plan.get_motif("rib_right").region.get("side") == "right"


def test_triangle_accent_shape_is_repaired_from_prompt_and_id():
    engine = PatternPlanEngine()
    text = "中心大菱形内部波浪，下方加入小三角镂空装饰"
    data = {
        "motifs": [
            {"motif_id": "diamond_main", "motif_type": "diamond", "effect": "plain", "region": {"center": [20, 20], "size": 20}, "role": "center"},
            {"motif_id": "triangle_lace_bottom", "motif_type": "mesh", "effect": "lace", "region": {"center": [20, 32], "size": 8, "shape": "diamond"}, "role": "accent", "parent_id": "diamond_main"},
        ],
    }
    plan = engine._data_to_plan(data, current_plan=None)
    engine._repair_plan_from_text(plan, text)
    plan = engine.validate(plan)

    accent = plan.get_motif("triangle_lace_bottom")
    assert accent.role == "center"
    assert accent.region.get("shape") == "triangle"


def test_bottom_accent_uses_row_axis_not_right_column():
    engine = PatternPlanEngine()
    text = "中心大菱形内部波浪，下方加入小三角镂空装饰"
    data = {
        "motifs": [
            {"motif_id": "diamond_main", "motif_type": "diamond", "effect": "plain", "region": {"center": [20, 20], "size": 18}, "role": "center"},
            {"motif_id": "wave_inside", "motif_type": "wave", "effect": "wave_tuck", "region": {"center": [20, 20], "size": 12, "shape": "diamond"}, "role": "center", "parent_id": "diamond_main"},
            {"motif_id": "triangle_eyelet", "motif_type": "triangle", "effect": "lace", "region": {"center": [20, 30], "size": 8, "shape": "triangle"}, "role": "center"},
        ],
    }
    plan = engine._data_to_plan(data, current_plan=None)
    engine._repair_plan_from_text(plan, text)
    plan = engine.validate(plan)

    accent = plan.get_motif("triangle_eyelet")
    assert accent.region["center"][0] > 20
    assert accent.region["center"][1] == 20


def test_panel_with_triangle_shape_renders_as_triangle():
    engine = PatternPlanEngine()
    data = {
        "motifs": [
            {
                "motif_id": "main",
                "motif_type": "panel",
                "effect": "honeycomb",
                "region": {"shape": "triangle", "center": [20, 20], "size": 16},
                "role": "center",
            }
        ],
    }
    plan = engine._data_to_plan(data, current_plan=None)
    engine._repair_plan_from_text(plan, "三角形内部蜂巢纹理")
    spec = engine.render_visual_spec(engine.validate(plan))

    main = next(r for r in spec.regions if r.region_id == "main")
    assert main.visual_shape == "triangle"
    assert main.placement.get("mask_shape", main.placement.get("shape")) == "triangle"


def test_start_end_side_band_width_is_not_expanded_to_default_size():
    engine = PatternPlanEngine()
    data = {
        "motifs": [
            {"motif_id": "left_rib", "motif_type": "column", "effect": "rib", "region": {"start": [0, 0], "end": [3, 39]}, "role": "side_band"},
            {"motif_id": "right_rib", "motif_type": "column", "effect": "rib", "region": {"start": [37, 0], "end": [39, 39]}, "role": "side_band"},
        ],
    }
    plan = engine.validate(engine._data_to_plan(data, current_plan=None))

    assert plan.get_motif("left_rib").region.get("width") == 4
    assert plan.get_motif("right_rib").region.get("width") == 3


def test_region_shape_overrides_panel_motif_type_for_common_geometry():
    engine = PatternPlanEngine()
    for shape in ["diamond", "triangle", "hexagon", "circle", "heart", "star"]:
        data = {
            "motifs": [
                {
                    "motif_id": f"{shape}_texture",
                    "motif_type": "panel",
                    "effect": "honeycomb",
                    "region": {"shape": shape, "center": [20, 20], "size": 12},
                    "role": "center",
                }
            ],
        }
        spec = engine.render_visual_spec(engine.validate(engine._data_to_plan(data, current_plan=None)))
        realized = next(r for r in spec.regions if r.region_id == f"{shape}_texture")
        assert realized.visual_shape == shape
        assert realized.placement.get("shape") == shape


def test_background_mesh_is_not_parented_to_inner_wave():
    engine = PatternPlanEngine()
    text = "圆形结构，内部波浪吊目，外部矩形边框，背景稀疏网眼"
    data = {
        "layout_type": "framed",
        "motifs": [
            {
                "motif_id": "bg_mesh",
                "motif_type": "circle",
                "effect": "lace",
                "region": {"type": "full", "shape": "circle"},
                "role": "allover",
                "parent_id": "inner_wave",
            },
            {
                "motif_id": "inner_wave",
                "motif_type": "circle",
                "effect": "wave_tuck",
                "region": {"center": [20, 20], "size": 12, "shape": "circle"},
                "role": "center",
            },
        ],
    }
    plan = engine._data_to_plan(data, current_plan=None)
    engine._repair_plan_from_text(plan, text)
    plan = engine.validate(plan)
    bg = plan.get_motif("bg_mesh")

    assert bg.role == "allover"
    assert bg.parent_id is None
    assert bg.motif_type == "panel"
    assert bg.region == {"type": "full"}


def test_prompt_background_creates_independent_sparse_mesh_layer():
    engine = PatternPlanEngine()
    plan = engine.from_prompt("矩形外框，圆形内部细密波浪吊目，背景稀疏网眼")
    bg = plan.get_motif("bg_texture")

    assert bg is not None
    assert bg.role == "allover"
    assert bg.parent_id is None
    assert bg.effect == "lace"
    assert bg.params["period_x"] >= 7
    assert bg.params["period_y"] >= 7


def test_allover_background_excludes_inner_texture_not_plain_frame():
    engine = PatternPlanEngine()
    plan = engine.from_prompt("圆形结构，内部波浪吊目，外部矩形边框，背景稀疏网眼")
    realization = VisualToRealizationConverter().convert(engine.render_visual_spec(plan))
    bg = realization.get_region("bg_texture")
    excluded = {item["region_id"] for item in bg.placement.get("exclude_masks", [])}

    assert "inner" in excluded
    assert "border" not in excluded


def test_child_texture_does_not_draw_second_container_outline():
    engine = PatternPlanEngine()
    text = "中心菱形，内部蜂巢吊目，背景稀疏网眼"
    data = {
        "layout_type": "centered",
        "motifs": [
            {
                "motif_id": "diamond_center",
                "motif_type": "diamond",
                "effect": "plain",
                "region": {"center": [20, 20], "size": 16},
                "role": "center",
            },
            {
                "motif_id": "honeycomb_inner",
                "motif_type": "panel",
                "effect": "honeycomb",
                "region": {"center": [20, 20], "size": 10, "shape": "diamond"},
                "role": "center",
                "parent_id": "diamond_center",
            },
        ],
    }
    plan = engine.parse_or_fallback(json.dumps(data), user_input=text)
    realization = VisualToRealizationConverter().convert(engine.render_visual_spec(plan))
    outer = realization.get_region("diamond_center")
    inner = realization.get_region("honeycomb_inner")

    assert outer.border_style != "none"
    assert inner.event_pattern == "honeycomb_tuck"
    assert inner.border_style == "none"


def test_frame_contains_near_edge_circles_as_children():
    engine = PatternPlanEngine()
    text = "矩形边框内包含两个靠近边界的小圆形区域，小圆形内部填充密集波浪吊目，背景为平针"
    data = {
        "layout_type": "framed",
        "motifs": [
            {
                "motif_id": "frame_rect",
                "motif_type": "frame",
                "effect": "plain",
                "region": {"center": [20, 20], "size": 16},
                "role": "border",
            },
            {
                "motif_id": "circle_left",
                "motif_type": "circle",
                "effect": "wave_tuck",
                "region": {"center": [10, 20], "size": 8, "shape": "circle"},
                "params": {"period_x": 3, "period_y": 3, "split_col_offset": 2, "tuck_col_offset": 3},
                "role": "center",
            },
            {
                "motif_id": "circle_right",
                "motif_type": "circle",
                "effect": "wave_tuck",
                "region": {"center": [30, 20], "size": 8, "shape": "circle"},
                "params": {"period_x": 3, "period_y": 3, "split_col_offset": 2, "tuck_col_offset": 3},
                "role": "center",
            },
        ],
    }
    plan = engine.parse_or_fallback(json.dumps(data), user_input=text)
    left = plan.get_motif("circle_left")
    right = plan.get_motif("circle_right")

    assert left.parent_id == "frame_rect"
    assert right.parent_id == "frame_rect"

    realization = VisualToRealizationConverter().convert(engine.render_visual_spec(plan))
    left_region = realization.get_region("circle_left")
    right_region = realization.get_region("circle_right")

    for region in [left_region, right_region]:
        assert region.placement.get("parent_id") == "frame_rect"
        assert region.placement.get("clip_to_parent") is True
        center = region.placement["center"]
        size = region.placement["size"]
        assert center[0] - size > 3
        assert center[0] + size < 37

    left_center = left_region.placement["center"]
    right_center = right_region.placement["center"]
    assert math.dist(left_center, right_center) >= left_region.placement["size"] + right_region.placement["size"]

    events = EventPlanner(grid_size=40).plan(realization)
    counts = {}
    for event in events:
        counts[event.region_id] = counts.get(event.region_id, 0) + 1
    assert counts.get("circle_left", 0) >= 20
    assert counts.get("circle_right", 0) >= 20
