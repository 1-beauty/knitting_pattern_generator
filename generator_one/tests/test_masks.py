from generation.visual_types import VisualSpec, VisualRegion
from generation.visual_to_realization import VisualToRealizationConverter
from generation.event_planner import EventPlanner
from generation.action_builder import ActionBuilder
from generation.mask_utils import point_in_mask


def test_circle_wave_mask():
    vr = VisualRegion(region_id='main', visual_shape='circle', visual_effect='wave_tuck', layout_role='center', placement={'center':[20,20],'size':8})
    vs = VisualSpec(regions=[vr])

    conv = VisualToRealizationConverter()
    plan = conv.convert(vs)
    assert plan.regions[0].placement.get('mask_shape') == 'circle'
    assert plan.regions[0].border_style == 'back_loop_outline'

    planner = EventPlanner(grid_size=40)
    events = planner.plan(plan)

    builder = ActionBuilder(grid_size=40)
    grid = builder.build(plan, events)

    # 所有事件应位于掩码内
    for e in events:
        assert point_in_mask(e.row, e.col, plan.regions[0].placement, 40), f"event outside mask: {e.row},{e.col}"

    # 所有非 base (f_knit) 操作应位于掩码内
    base_idx = builder._f_knit
    rows, cols = grid.shape
    for r in range(rows):
        for c in range(cols):
            if grid[r,c] != base_idx:
                assert point_in_mask(r, c, plan.regions[0].placement, 40), f"action outside mask at {r},{c}"


def test_rectangle_inner_wave_mask():
    outer = VisualRegion(
        region_id='outer',
        visual_shape='frame',
        visual_effect='plain',
        layout_role='border',
        placement={'center': [20, 20], 'size': 18},
    )
    inner = VisualRegion(
        region_id='inner',
        visual_shape='panel',
        visual_effect='wave_tuck',
        layout_role='center',
        placement={},
    )
    vs = VisualSpec(regions=[outer, inner])

    conv = VisualToRealizationConverter()
    plan = conv.convert(vs)

    outer_region = plan.regions[0]
    inner_region = plan.regions[1]
    assert outer_region.border_style == 'back_loop_outline'
    assert inner_region.placement.get('shape') == 'rectangle'
    assert inner_region.placement.get('mask_shape') == 'rectangle'
    assert inner_region.event_params.get('edge_fade', 0) == 0
    assert inner_region.placement.get('size') == 16

    builder = ActionBuilder(grid_size=40)
    assert builder._get_shape(outer_region) == 'rectangle'
    assert builder._get_shape(inner_region) == 'rectangle'

    planner = EventPlanner(grid_size=40)
    events = planner.plan(plan)

    grid = builder.build(plan, events)

    for e in events:
        if e.region_id == 'inner':
            assert point_in_mask(e.row, e.col, inner_region.placement, 40), f"event outside rectangle mask: {e.row},{e.col}"

    base_idx = builder._f_knit
    rows, cols = grid.shape
    for r in range(rows):
        for c in range(cols):
            if grid[r, c] != base_idx:
                assert point_in_mask(r, c, inner_region.placement, 40) or point_in_mask(r, c, outer_region.placement, 40), f"action outside masks at {r},{c}"


def test_rectangle_mask_axis_aligned_not_diamond():
    placement = {'mask_shape': 'rectangle', 'center': [20, 20], 'size': 6}

    # 轴向点应在矩形内
    assert point_in_mask(20, 26, placement, 40)
    assert point_in_mask(26, 20, placement, 40)

    # 对角远点在矩形内（矩形判定），若是菱形则会被排除
    assert point_in_mask(25, 25, placement, 40)

    # 明显外部点
    assert not point_in_mask(20, 27, placement, 40)


def test_circle_center_dense_wave_distribution():
    vr = VisualRegion(
        region_id='main',
        visual_shape='circle',
        visual_effect='wave_tuck',
        layout_role='center',
        placement={'center': [20, 20], 'size': 10},
        params={'density_profile': 'center_dense'},
    )
    conv = VisualToRealizationConverter()
    plan = conv.convert(VisualSpec(regions=[vr]))

    planner = EventPlanner(grid_size=40)
    events = planner.plan(plan)

    # 边缘环事件应显著少于中心区域
    center_count = 0
    edge_count = 0
    for e in events:
        dr = e.row - 20
        dc = e.col - 20
        rr = (dr * dr + dc * dc) / float(10 * 10)
        if rr <= 0.50:
            center_count += 1
        elif rr >= 0.80:
            edge_count += 1
    assert center_count >= edge_count


def test_rectangle_border_thickness_and_wave_direction_param():
    outer = VisualRegion(
        region_id='outer',
        visual_shape='frame',
        visual_effect='plain',
        layout_role='border',
        placement={'center': [20, 20], 'size': 16},
        params={'border_thickness': 3},
    )
    inner = VisualRegion(
        region_id='inner',
        visual_shape='panel',
        visual_effect='wave_tuck',
        layout_role='center',
        placement={},
        params={'wave_direction': 'vertical'},
    )
    plan = VisualToRealizationConverter().convert(VisualSpec(regions=[outer, inner]))

    assert plan.regions[0].border_thickness == 3
    assert plan.regions[1].event_params.get('wave_direction') == 'vertical'


def test_clipped_diamond_wave_adds_edge_anchor_events():
    outer = VisualRegion(
        region_id='outer',
        visual_shape='diamond',
        visual_effect='plain',
        layout_role='center',
        placement={'center': [20, 20], 'size': 18},
    )
    inner = VisualRegion(
        region_id='inner',
        visual_shape='wave',
        visual_effect='wave_tuck',
        layout_role='center',
        placement={'center': [20, 20], 'size': 12, 'shape': 'diamond', 'parent_id': 'outer', 'clip_to_parent': True},
        params={'period_x': 4, 'period_y': 3, 'split_col_offset': 2, 'tuck_col_offset': 3},
    )
    plan = VisualToRealizationConverter().convert(VisualSpec(regions=[outer, inner]))
    inner_region = plan.get_region('inner')
    assert inner_region.event_params.get('edge_anchor') is True

    events = EventPlanner(grid_size=40).plan(plan)
    anchor_events = [e for e in events if e.reason in {'diagonal_wave edge_anchor', 'diagonal_wave edge_anchor_pair', 'diagonal_wave edge_anchor_endpoint', 'diagonal_wave edge_anchor_seam'}]
    assert anchor_events
    rows_with_two_sides = {}
    for event in anchor_events:
        rows_with_two_sides.setdefault(event.row, []).append(event.col)
    assert any(max(cols) - min(cols) >= 4 for cols in rows_with_two_sides.values() if len(cols) >= 2)


def test_clipped_diamond_wave_edge_anchors_are_paired():
    outer = VisualRegion(
        region_id='outer',
        visual_shape='diamond',
        visual_effect='plain',
        layout_role='center',
        placement={'center': [20, 20], 'size': 18},
    )
    inner = VisualRegion(
        region_id='inner',
        visual_shape='wave',
        visual_effect='wave_tuck',
        layout_role='center',
        placement={'center': [20, 20], 'size': 12, 'shape': 'diamond', 'parent_id': 'outer', 'clip_to_parent': True},
        params={'period_x': 4, 'period_y': 3, 'split_col_offset': 2, 'tuck_col_offset': 3},
    )
    plan = VisualToRealizationConverter().convert(VisualSpec(regions=[outer, inner]))
    events = EventPlanner(grid_size=40).plan(plan)
    paired = [e for e in events if e.reason in {'diagonal_wave edge_anchor_pair', 'diagonal_wave edge_anchor_endpoint', 'diagonal_wave edge_anchor_seam'}]
    assert paired

    by_row = {}
    for event in paired:
        by_row.setdefault(event.row, []).append(event)
    assert any(
        any(abs(a.col - b.col) >= 4 and {a.action_abbr, b.action_abbr} == {'f_split', 'f_tuck'}
            for a in row_events for b in row_events if a is not b)
        for row_events in by_row.values()
    )


def test_hexagon_honeycomb_keeps_hexagon_shape_and_background_excludes_it():
    center = VisualRegion(
        region_id='center_honeycomb',
        visual_shape='hexagon',
        visual_effect='honeycomb',
        layout_role='center',
        placement={'center': [20, 20], 'size': 12, 'shape': 'hexagon'},
        params={'period_x': 3, 'period_y': 3, 'stagger': True},
    )
    background = VisualRegion(
        region_id='background_wave',
        visual_shape='allover',
        visual_effect='wave_tuck',
        layout_role='allover',
        placement={'type': 'full'},
        params={'period_x': 6, 'period_y': 5, 'split_col_offset': 2, 'tuck_col_offset': 3},
    )
    plan = VisualToRealizationConverter().convert(VisualSpec(regions=[center, background]))
    center_region = plan.get_region('center_honeycomb')
    bg_region = plan.get_region('background_wave')

    assert center_region.placement.get('mask_shape') == 'hexagon'
    assert center_region.border_style == 'back_loop_outline'
    assert center_region.event_pattern == 'honeycomb_tuck'
    assert bg_region.placement.get('exclude_masks')

    events = EventPlanner(grid_size=40).plan(plan)
    center_events = [e for e in events if e.region_id == 'center_honeycomb']
    bg_events = [e for e in events if e.region_id == 'background_wave']
    assert center_events
    assert bg_events
    assert all(point_in_mask(e.row, e.col, center_region.placement, 40) for e in center_events)
    assert all(not point_in_mask(e.row, e.col, center_region.placement, 40) for e in bg_events)


def test_narrow_side_band_vertical_wave_uses_local_phase():
    left = VisualRegion(
        region_id='left_rib',
        visual_shape='column',
        visual_effect='rib',
        layout_role='side_band',
        placement={'side': 'left', 'width': 4, 'center': [6, 20], 'size': 4},
        params={'period_y': 2, 'width': 4},
    )
    right = VisualRegion(
        region_id='right_rib',
        visual_shape='column',
        visual_effect='rib',
        layout_role='side_band',
        placement={'side': 'right', 'width': 4, 'center': [34, 20], 'size': 4},
        params={'period_y': 2, 'width': 4},
    )
    plan = VisualToRealizationConverter().convert(VisualSpec(regions=[left, right]))
    events = EventPlanner(grid_size=40).plan(plan)

    left_events = [e for e in events if e.region_id == 'left_rib']
    right_events = [e for e in events if e.region_id == 'right_rib']
    assert left_events
    assert right_events
    assert all(e.col < 4 for e in left_events)
    assert all(e.col >= 36 for e in right_events)


def test_frame_does_not_overwrite_child_circle_masks():
    frame = VisualRegion(
        region_id='frame',
        visual_shape='frame',
        visual_effect='plain',
        layout_role='border',
        placement={'center': [20, 20], 'size': 18},
    )
    circle = VisualRegion(
        region_id='circle_lace',
        visual_shape='circle',
        visual_effect='lace',
        layout_role='center',
        placement={'center': [20, 20], 'size': 14},
        params={'period_x': 4, 'period_y': 4, 'stagger': True},
    )
    inner = VisualRegion(
        region_id='inner_wave',
        visual_shape='wave',
        visual_effect='wave_tuck',
        layout_role='center',
        placement={'center': [20, 20], 'size': 10, 'shape': 'circle', 'parent_id': 'circle_lace'},
        params={'period_x': 3, 'period_y': 3, 'split_col_offset': 2, 'tuck_col_offset': 3},
    )
    plan = VisualToRealizationConverter().convert(VisualSpec(regions=[frame, circle, inner]))
    circle_region = plan.get_region('circle_lace')
    inner_region = plan.get_region('inner_wave')

    assert circle_region.placement.get('mask_shape') == 'circle'
    assert inner_region.placement.get('mask_shape') == 'circle'
    assert circle_region.event_pattern == 'lattice_miss'
    assert inner_region.event_pattern == 'diagonal_wave'


def test_common_geometry_effect_pairs_preserve_requested_shape():
    shapes = ['diamond', 'triangle', 'hexagon', 'circle', 'heart', 'star']
    effects = ['plain', 'wave_tuck', 'lace', 'relief', 'honeycomb', 'seed', 'cable']

    for shape in shapes:
        for effect in effects:
            region = VisualRegion(
                region_id=f'{shape}_{effect}',
                visual_shape=shape,
                visual_effect=effect,
                layout_role='center',
                placement={'center': [20, 20], 'size': 10, 'shape': shape},
            )
            plan = VisualToRealizationConverter().convert(VisualSpec(regions=[region]))
            realized = plan.regions[0]
            assert realized.placement.get('mask_shape') == shape
            assert realized.placement.get('shape') == shape
            assert realized.border_style == 'back_loop_outline'


def test_triangle_outline_has_all_three_sides_after_raster_repair():
    triangle = VisualRegion(
        region_id='triangle',
        visual_shape='triangle',
        visual_effect='honeycomb',
        layout_role='center',
        placement={'center': [20, 20], 'size': 16, 'shape': 'triangle'},
        params={'period_x': 4, 'period_y': 4, 'stagger': True},
    )
    plan = VisualToRealizationConverter().convert(VisualSpec(regions=[triangle]))
    events = EventPlanner(grid_size=40).plan(plan)
    grid = ActionBuilder(grid_size=40).build(plan, events)
    b_knit = ActionBuilder(grid_size=40)._b_knit
    coords = [(r, c) for r in range(40) for c in range(40) if int(grid[r, c]) == b_knit]

    top = [(r, c) for r, c in coords if r <= 8 and 17 <= c <= 23]
    left = [(r, c) for r, c in coords if 8 <= r <= 28 and c < 20]
    right = [(r, c) for r, c in coords if 8 <= r <= 28 and c > 20]
    assert len(top) >= 2
    assert len(left) >= 8
    assert len(right) >= 8
