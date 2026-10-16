"""按图1风格重绘原生可编辑图4（约束检查与保守修复循环），全英文 TNR，并执行交付审计。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
from io import BytesIO
from pathlib import Path
import sys
import time
from zipfile import ZipFile

sys.dont_write_bytecode = True
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches, Pt
import build_fig1_editable as f1

ROOT = f1.ROOT
TEMPLATE = f1.TEMPLATE
OUT = ROOT / 'outputs/fig4_pptx_en_20260922'
STEM = ROOT / 'docs/figures/Fig4_Constraint_Check_Conservative_Repair_EN'
PPTX, PNG, PDF = (STEM.with_suffix(ext) for ext in ('.pptx', '.png', '.pdf'))
INK, MUTED, BLUE = f1.INK, f1.MUTED, f1.BLUE
PLAN = ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_pattern_plan.json'
STATS = ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_stats.json'
ACTION_BMP = ROOT / 'outputs/runs/patternplan/pp_01/color_map/pp_01_output.bmp'
ACTION_NPY = ACTION_BMP.parent / 'intermediate/pp_01_action.npy'
RUNS = ROOT / 'outputs/runs'
COL_W, GAP, X0 = 4.05, .30, .16
COLS = [X0 + i * (COL_W + GAP) for i in range(4)]
PALETTES = [('EAF3FC', '4E86B5'), ('EAF4ED', '487F55'), ('FDF3E7', 'B07A3C'), ('F1EDF8', '8062AA')]
CANVAS = 3.50  # 作者意见：删冗回收的垂直空间用于放大数据网格（2.60→3.50），填满(a)栏、消除底部空白。
SUITE_EXPECT = {'runs': 263, 'craft_flagged': 33, 'loop_entered': 17, 'guard_pruned': 100}
# 图4 归档套件快照冻结在 263 条运行（与论文图注/正文一致）。以下 5 条 GUI 运行于 2026-09-22
# 晚间（原图4 定稿之后）才归档，对 craft_flagged/loop_entered/guard_pruned 三项计数均无贡献
# （经复算均为干净运行，排除后三项仍为 33/17/100）；仅为保持报告分母与全文一致而排除。
SUITE_EXCLUDE = {'20260922_215919', '20260922_220239', '20260922_220402',
                 '20260922_220713', '20260922_222102'}
TEXT_RECORDS = []
VISUAL_RECORDS = []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def guard_removals(stats):
    # 与管线各保守 guard 的统计键一一对应（pipeline.py step6.5/6.25/边距/配对 guard）。
    total = 0
    for key in ('compiler_guard', 'post_repair_compiler_guard'):
        total += (stats.get(key) or {}).get('removed_contextless_special_actions', 0)
    for key in ('layer_clip', 'post_repair_layer_clip', 'final_layer_clip'):
        total += (stats.get(key) or {}).get('clipped_actions', 0)
    region = stats.get('post_repair_event_region_guard') or {}
    total += region.get('removed_outside_event_region', 0) + region.get('pair_partner_removed', 0)
    pair = stats.get('wave_pair_guard') or {}
    total += pair.get('removed_unpaired_wave_cells', 0) + pair.get('removed_unpaired_honeycomb_cells', 0)
    total += (stats.get('canvas_margin') or {}).get('cleared_actions', 0)
    return total


def suite_stats():
    # 全量归档运行的修复触发统计：只读历史 stats.json，不重跑任何生成器。
    counts = {'runs': 0, 'craft_flagged': 0, 'loop_entered': 0, 'guard_pruned': 0}
    for path in sorted(RUNS.rglob('*_stats.json')):
        if set(path.parts) & SUITE_EXCLUDE:
            continue
        stats = json.loads(path.read_text(encoding='utf-8'))
        violations = stats.get('violations') or {}
        if 'hard_before' not in violations:
            continue
        counts['runs'] += 1
        counts['craft_flagged'] += violations.get('craft_before', 0) > 0
        counts['loop_entered'] += (stats.get('llm_repair') or {}).get('rounds', 0) > 0
        counts['guard_pruned'] += guard_removals(stats) > 0
    assert counts == SUITE_EXPECT, counts
    return counts


def instance():
    # 只读 Generation Case 01（pp_01）历史产物：该例首轮即通过全部检查，修复回路空闲。
    import numpy as np
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    stats = json.loads(STATS.read_text(encoding='utf-8'))
    motifs = {m['motif_id']: m for m in plan['motifs']}
    assert motifs['wave_1']['parent_id'] == 'circle_1'
    assert motifs['wave_1']['params']['period_x'] == 5 and motifs['wave_1']['params']['period_y'] == 4
    actions = np.load(ACTION_NPY, allow_pickle=False)
    assert actions.shape == (40, 40) and set(np.unique(actions).tolist()) == {0, 1, 7, 8}
    grid = Image.open(ACTION_BMP).convert('RGB')
    colors = {0: (255, 0, 16), 1: (43, 206, 72), 7: (0, 164, 255), 8: (255, 230, 6)}
    assert all(grid.getpixel((c, r)) == colors[int(actions[r, c])] for r in range(40) for c in range(40))
    assert all(stats['violations'][k] == 0 for k in ('hard_before', 'craft_before', 'hard_after', 'craft_after'))
    assert stats['violations']['hard'] == [] and stats['violations']['craft'] == []
    assert stats['llm_repair']['rounds'] == 0 and stats['llm_repair']['edits'] == 0
    assert guard_removals(stats) == 0, 'pp_01 的任何保守 guard 都不得有删除'
    assert stats['layer_clip_audit']['texture_actions_outside_child_layers'] == 0
    suite = suite_stats()
    evidence = {
        'sample': 'Generation Case 01 (pp_01), historical run outputs only',
        'plan_sha256': sha(PLAN), 'stats_sha256': sha(STATS),
        'action_npy_sha256': sha(ACTION_NPY), 'action_bmp_sha256': sha(ACTION_BMP),
        'first_pass_clean': True, 'violations': stats['violations'], 'llm_repair': stats['llm_repair'],
        'guard_removals_pp01': guard_removals(stats),
        'suite_counts': suite, 'suite_source': 'outputs/runs/**/*_stats.json (read-only scan; 5 post-snapshot '
                                               'GUI runs of 2026-09-22 excluded via SUITE_EXCLUDE to freeze the suite at 263)',
        'no_prerepair_grid_exported': '管线未导出修复前网格，故图面不展示前后网格对，'
                                      '修复路径以归档统计与算子契约呈现',
    }
    write_json('sample_evidence.json', evidence)
    return grid, suite


def text(sl, name, x, y, w, h, value, size=20, color=INK, bold=False, align='left'):
    s = f1.text(sl, name, x, y, w, h, value, size, color, bold, align)
    TEXT_RECORDS.append({'name': name, 'text': value, 'font_pt': size, 'box_inches': [x, y, w, h]})
    return s


def cand_runs(sl, image, x, y, size):
    # 与图1/图2/图3同款：同行同色连续格合并为原生矩形，颜色取自真实色码图。
    elements = []
    for r in range(40):
        c = 0
        while c < 40:
            rgb = image.getpixel((c, r))
            start = c
            while c < 40 and image.getpixel((c, r)) == rgb:
                c += 1
            hexrgb = ''.join(f'{k:02X}' for k in rgb)
            elements.append(f1.shape(sl, f'cand_run_{r}_{start}_{c}', x + start * size / 40,
                                     y + r * size / 40, (c - start) * size / 40, size / 40,
                                     hexrgb, hexrgb, lw=.18))
    f1.grouped(sl, 'cand_group', elements)
    VISUAL_RECORDS.append({'prefix': 'cand', 'layout': [x, y, size]})


def chip(sl, name, x, y, w, h, fill, accent, line1, line2=None, s1=24, s2=22, m=.06):
    f1.shape(sl, name, x, y, w, h, fill, accent, 'round')
    if line2 is None:
        text(sl, name + '_text', x + m, y + (h - .40) / 2, w - 2 * m, .40, line1, s1, accent, True, 'center')
    else:
        text(sl, name + '_title', x + m, y + .10, w - 2 * m, .40, line1, s1, bold=True, align='center')
        text(sl, name + '_sub', x + m, y + .52, w - 2 * m, .38, line2, s2, MUTED, align='center')


def dashed_line(sl, name, x1, y1, x2, y2, color, width, arrow=False):
    # f1.line 不支持虚线；按 CT_LineProperties 顺序在 solidFill 后插入 prstDash。
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn
    s = sl.shapes.add_connector(f1.MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    s.name = name
    style = s._element.find(qn('p:style'))
    if style is not None:
        s._element.remove(style)
    s.line.color.rgb = RGBColor.from_string(color)
    s.line.width = Pt(width)
    ln = s._element.spPr.find(qn('a:ln'))
    dash = f1.OxmlElement('a:prstDash')
    dash.set('val', 'dash')
    ln.append(dash)
    if arrow:
        tip = f1.OxmlElement('a:tailEnd')
        tip.set('type', 'triangle')
        tip.set('w', 'med')
        tip.set('len', 'med')
        ln.append(tip)
    return s


def build_deck():
    OUT.mkdir(parents=True, exist_ok=True)
    grid, suite = instance()
    prs = Presentation()
    if TEMPLATE.exists():
        tpl = Presentation(TEMPLATE)
        prs.slide_width, prs.slide_height = tpl.slide_width, tpl.slide_height
    else:
        # 模板随2026-09-29 docs整理删除；幻灯片尺寸改读图1证据清单（与图2/图3同款回退）。
        ev = ROOT / 'outputs/fig1_pptx_en_20260921/source_evidence.json'
        if ev.exists():
            w, h = json.loads(ev.read_text(encoding='utf-8'))['template_inches']
        else:
            w, h = 17.416666666666668, 9.802083333333334
        prs.slide_width, prs.slide_height = Inches(w), Inches(h)
    # 作者意见：删冗后回收的垂直空间不留下空白——内栏/栏面板/slide 高度同步压缩至8.30in，各栏内容贴紧面板。
    prs.slide_height = Inches(8.30)
    prs.core_properties.title = 'Constraint Checking and Conservative Repair Loop'
    prs.core_properties.subject = 'Figure 4: editable native shapes; Generation Case 01 and suite evidence'
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    TEXT_RECORDS.clear()
    VISUAL_RECORDS.clear()
    # 导师标准：数字盘①-④改 a-d（Elsevier 体例，图注同步引 (a)-(d)）；栏题双行居中升32pt，副题24pt（26pt经COM实测超栏宽）。
    headers = [('Candidate', 'ActionGrid', 'Generation Case 01 · A'),
               ('Deterministic', 'Checks', 'four checks, fixed order'),
               ('Conservative', 'Repair', 'remove or downgrade only'),
               ('Re-check and', 'Release', 'loop until V_hard = 0')]
    for i, (x, (bg, accent), (first, second, sub)) in enumerate(zip(COLS, PALETTES, headers)):
        tag = 'abcd'[i]
        f1.shape(sl, f'column_{i+1}', x, .40, COL_W, 7.24, bg, kind='round')
        f1.shape(sl, f'panel_disc_{tag}', x + .12, .58, .44, .44, accent, kind='oval')
        text(sl, f'panel_label_{tag}', x + .12, .58, .44, .44, tag, 26, 'FFFFFF', align='center')
        text(sl, f'heading_first_{i+1}', x + .10, 1.06, COL_W - .20, .50, first, 32, bold=True, align='center')
        text(sl, f'heading_second_{i+1}', x + .10, 1.62, COL_W - .20, .50, second, 32, bold=True, align='center')
        text(sl, f'subheading_{i+1}', x + .10, 2.18, COL_W - .20, .40, sub, 24, accent, align='center')
        f1.shape(sl, f'inner_panel_{i+1}', x + .10, 2.64, COL_W - .20, 4.82, 'FFFFFF', bg, 'round', 1)
    for i in range(3):
        f1.line(sl, f'stage_arrow_{i+1}', COLS[i] + COL_W + .04, 5.10, COLS[i + 1] - .04, 5.10, INK, 2.25, True)

    # (a) 候选网格：pp_01 真实色码图（首轮即通过，修复回路空闲）。
    # 作者意见：首轮零违例三行统计改由图注与正文文字阐述，图面仅保留真实色码图网格与其标识；标签升22pt。
    cx = COLS[0] + (COL_W - CANVAS) / 2
    cy = 2.86
    cand_runs(sl, grid, cx, cy, CANVAS)
    f1.shape(sl, 'cand_outline', cx - .005, cy - .005, CANVAS + .01, CANVAS + .01, None, '7C98AE', lw=1)
    text(sl, 'cand_label', COLS[0] + .20, 6.50, COL_W - .40, .36, 'Generation Case 01 · grid A', 22, align='center')
    text(sl, 'cand_sublabel', COLS[0] + .20, 6.90, COL_W - .40, .36, '4 action classes · 1600 cells', 22, MUTED, align='center')

    # (b) 四组确定性检查：写入 guard、硬约束 H1–H8、工艺 C1–C6、成组完整性。
    # 导师标准：三行“support(v)/fixed order”注复述图注(b)，删除（support(v) 仍由(c)修复芯片承载）；芯片升24/22pt。
    # 24pt标题容不下长串，H1 to H8 / C1 to C6 移入22pt副行；芯片加宽至 COL_W-.28。
    x2 = COLS[1] + .14
    cw = COL_W - .28
    chip(sl, 'check_chip_guard', x2, 2.86, cw, .98, 'EAF4ED', '487F55', 'Write-time guard', 'risk order · outline first', m=.02)
    chip(sl, 'check_chip_hard', x2, 4.00, cw, .98, 'EAF4ED', '487F55', 'Hard constraints', 'H1 to H8 · support · bed', m=.02)
    chip(sl, 'check_chip_craft', x2, 5.14, cw, .98, 'EAF4ED', '487F55', 'Craft heuristics', 'C1 to C6 · transition', m=.02)
    chip(sl, 'check_chip_group', x2, 6.28, cw, .98, 'EAF4ED', '487F55', 'Group integrity', 'split + tuck pairs complete', m=.02)

    # (c) 保守修复算子：只回退/取消/删除/降级，从不新造事件；修改限于支持域。
    # 作者意见：归档统计（263/33/17/100）改由图注与正文文字阐述，图面不再显示，
    # 使(c)栏与(b)(d)栏同为四枚芯片、垂直对齐；算子芯片升24/22pt。
    x3 = COLS[2] + .14
    chip(sl, 'repair_chip_base', x3, 2.86, cw, .98, 'FDF3E7', 'B07A3C', 'Revert to stable base', 'knit actions only', m=.02)
    chip(sl, 'repair_chip_cancel', x3, 4.00, cw, .98, 'FDF3E7', 'B07A3C', 'Cancel partial groups', 'whole group or nothing', m=.02)
    chip(sl, 'repair_chip_down', x3, 5.14, cw, .98, 'FDF3E7', 'B07A3C', 'Delete or downgrade', 'high-risk actions', m=.02)
    chip(sl, 'repair_chip_never', x3, 6.28, cw, .98, 'FDF3E7', 'B07A3C', 'Never create events', 'edits stay in support(v)', m=.02)

    # (d) 复核与放行：单调收敛、结构保持、输出色码图与机器导出。
    # 导师标准：三行“Case 01 passes first pass”注与(a)首轮统计及图注(d)重复，删除；芯片升24/22pt。
    x4 = COLS[3] + .14
    chip(sl, 'loop_chip_recheck', x4, 2.86, cw, .98, 'F1EDF8', '8062AA', 'Re-check loop', 'until V_hard = 0', m=.02)
    chip(sl, 'loop_chip_monotone', x4, 4.00, cw, .98, 'F1EDF8', '8062AA', 'Monotone convergence', 'count never increases', m=.02)
    chip(sl, 'loop_chip_release', x4, 5.14, cw, .98, 'F1EDF8', '8062AA', 'Output released', 'color map + machine export', m=.02)
    chip(sl, 'loop_chip_keep', x4, 6.28, cw, .98, 'F1EDF8', '8062AA', 'Structure preserved', 'outline and base untouched', m=.02)

    # 复核回路：自栏4底部虚线返回栏2（正交三段，箭头向上进入检查）。高度回收后回路下探至7.88in。
    x4c, x2c, y_loop = COLS[3] + COL_W / 2, COLS[1] + COL_W / 2, 7.88
    dashed_line(sl, 'loop_back_down', x4c, 7.70, x4c, y_loop, '8062AA', 1.6)
    dashed_line(sl, 'loop_back_across', x4c, y_loop, x2c, y_loop, '8062AA', 1.6)
    dashed_line(sl, 'loop_back_up', x2c, y_loop, x2c, 7.70, '8062AA', 1.6, True)

    # 导师标准：底部横带删除（主线句“check, repair, re-check…only removes or downgrades”与
    # “violation counts never increase…outlines…never reshaped”均由图注(d)逐字承载）。
    notes = (
        'Figure 4 is rebuilt as native editable PowerPoint objects in the Figure 1 visual language; all figure text is English Times New Roman.\n'
        'The candidate grid is the real Generation Case 01 (pp_01) color map drawn as merged native rectangles; this run passes every check on the '
        'first pass (0 hard and 0 craft violations, 0 LLM repair rounds and edits, 0 guard removals), so the repair loop is idle for it.\n'
        'Suite evidence is a read-only scan of all archived run statistics (263 runs): 33 runs flag craft violations at first detection, '
        '17 runs enter the repair loop, and conservative guards prune cells in 100 runs; no archived run flags a hard violation at detection.\n'
        'The pipeline does not export pre-repair grids, so the figure shows the operator contract and the caption reports the suite frequencies instead of a before/after grid pair.\n'
        'The figure carries no axes, ticks, monospace code blocks or bitmap overlays; the dashed loop back to the checks is a native connector.\n'
        '2026-09-29 advisor-style pass: the bottom summary band and the restatement notes (deterministic-program caption, support(v)/fixed-order, first-pass idle) were removed as verbatim duplicates of the caption; number discs relabeled a-d per Elsevier style and the caption cites (a)-(d); both the pp_01 first-pass zeros and the archived suite statistics (263/33/17/100) are stated only in the caption and body text, leaving column (a) as the real color-map grid plus its label and column (c) aligned with (b) and (d); the reclaimed vertical space was re-invested rather than left blank: the (a) grid grew to 3.50in, column headings rose to 32pt (subheadings held at the 24pt column-width ceiling after COM measured 26pt overflowing), and panel/slide heights were trimmed to 8.30in so no column carries a large empty tail (chip body type stays at the 24/22pt column-width ceiling).\n'
        '2026-09-29 reviewer pass: all body text raised one more step to a uniform 22pt floor (24pt chip titles, 24pt subheadings, 30pt column headings) so the printed figure matches Figs. 1-3; headings moved to their own centered two-line block because the narrow columns cannot fit 30pt beside the letter disc.\n'
        'Suite denominator frozen at 263 archived runs to match the caption: 5 clean GUI runs archived on the evening of 2026-09-22 (after this figure was first fixed) are excluded via SUITE_EXCLUDE; they contribute nothing to the 33/17/100 repair statistics, which are unchanged.')
    tf = sl.notes_slide.notes_text_frame
    tf.text = notes
    for para in tf.paragraphs:
        for run in para.runs:
            run.font.name, run.font.size = 'Times New Roman', Pt(18)
    prs.save(PPTX)
    normalize_package()
    write_json('text_manifest.json', TEXT_RECORDS)
    write_json('native_visual_manifest.json', VISUAL_RECORDS)
    return audit_deck()


def normalize_package():
    # 与图1/图2/图3同一规范化：包内所有typeface统一Times New Roman并补latin/ea/cs。
    from lxml import etree
    from pptx.oxml.ns import qn
    from pptx.oxml.xmlchemy import OxmlElement
    target = BytesIO()
    with ZipFile(PPTX) as src, ZipFile(target, 'w') as dest:
        for item in src.infolist():
            blob = src.read(item.filename)
            if item.filename.endswith('.xml'):
                root = etree.fromstring(blob)
                for node in root.iter():
                    if 'typeface' in node.attrib:
                        node.set('typeface', 'Times New Roman')
                    if node.tag in {qn('a:rPr'), qn('a:defRPr'), qn('a:endParaRPr')}:
                        node.set('lang', 'en-US')
                        if 'sz' in node.attrib:
                            node.set('sz', str(max(2200, int(node.get('sz')))))
                        for tag in ('a:latin', 'a:ea', 'a:cs'):
                            face = node.find(qn(tag))
                            if face is None:
                                face = OxmlElement(tag)
                                node.append(face)
                            face.set('typeface', 'Times New Roman')
                blob = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
            dest.writestr(item, blob)
    PPTX.write_bytes(target.getvalue())


def flatten(shapes):
    for s in shapes:
        yield s
        if s.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from flatten(s.shapes)


def reference_images():
    grid, _ = instance()
    return {'cand': grid}


def layout_of(prefix):
    return [COLS[0] + (COL_W - CANVAS) / 2, 2.86, CANVAS]


def audit_deck():
    assert PPTX.exists()
    p = Presentation(PPTX)
    assert len(p.slides) == 1
    shapes = list(flatten(p.slides[0].shapes))
    refs = reference_images()
    covered = {}
    for prefix, image in refs.items():
        runs = [s for s in shapes if s.name.startswith(prefix + '_run_')]
        seen = set()
        for s in runs:
            r, start, end = (int(v) for v in s.name.rsplit('_', 3)[1:])
            rgb = image.getpixel((start, r))
            assert tuple(s.fill.fore_color.rgb) == rgb, s.name
            assert all(image.getpixel((c, r)) == rgb for c in range(start, end)), s.name
            assert start == 0 or image.getpixel((start - 1, r)) != rgb, s.name
            assert end == 40 or image.getpixel((end, r)) != rgb, s.name
            x, y, size = layout_of(prefix)
            for actual, want in zip((s.left, s.top, s.width, s.height),
                                    (x + start * size / 40, y + r * size / 40, (end - start) * size / 40, size / 40)):
                assert abs(actual - Inches(want)) <= 3, s.name
            cells = {(r, c) for c in range(start, end)}
            assert not seen & cells
            seen |= cells
        assert seen == {(r, c) for r in range(40) for c in range(40)}, prefix
        covered[prefix] = len(seen)
    pictures = [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert not pictures, '图4不使用任何位图贴图'
    fonts, bounds = [], []
    for s in shapes:
        if s.left < -12700 or s.top < -12700 or s.left + s.width > p.slide_width + 12700 or s.top + s.height > p.slide_height + 12700:
            bounds.append(s.name)
        if s.has_text_frame and s.text.strip():
            for para in s.text_frame.paragraphs:
                for run in para.runs:
                    assert run.font.size is not None, s.name
                    fonts.append(run.font.size.pt)
    assert not bounds, bounds
    assert min(fonts) >= 22, min(fonts)
    ratio = 160 / (p.slide_width / 914400 * 25.4)
    assert min(fonts) * ratio >= 6
    with ZipFile(PPTX) as z:
        forbidden = [n for n in z.namelist() if n.lower().endswith('.svg')]
        assert not forbidden
        assert all(b'image/svg+xml' not in z.read(n) and b'<asvg:' not in z.read(n)
                   for n in z.namelist() if n.endswith(('.xml', '.rels')))
    from lxml import etree
    from pptx.oxml.ns import qn
    faces = set()
    with ZipFile(PPTX) as z:
        for name in z.namelist():
            if name.endswith('.xml'):
                for node in etree.fromstring(z.read(name)).iter():
                    if 'typeface' in node.attrib:
                        faces.add(node.get('typeface'))
                    if node.tag == qn('a:t'):
                        assert not re.search(r'[\u3400-\u9fff]', node.text or ''), name
    assert faces == {'Times New Roman'}, faces
    alltext = '\n'.join(s.text for s in shapes if s.has_text_frame)
    for phrase in ('H1 to H8', 'C1 to C6', 'support(v)', 'Never create events', 'Re-check loop',
                   'Monotone convergence', 'machine export',
                   'Generation Case 01 · grid A', 'outline and base untouched'):
        assert phrase in alltext, phrase
    result = {
        'passed': True, 'slide_count': 1, 'total_objects_recursive': len(shapes),
        'object_types': dict(Counter(str(s.shape_type) for s in shapes)),
        'scope_runs': sum(len([s for s in shapes if s.name.startswith(pfx + '_run_')]) for pfx in refs),
        'scope_cells_covered': covered, 'scope_pixel_exact': True, 'pictures': len(pictures),
        'text_objects': sum(s.has_text_frame and bool(s.text.strip()) for s in shapes),
        'min_font_pt': min(fonts), 'max_font_pt': max(fonts),
        'figure_width_mm': 160, 'min_reduced_font_pt': min(fonts) * ratio,
        'shape_out_of_slide': bounds, 'svg_files': forbidden,
        'package_typefaces': sorted(faces), 'pptx_sha256': sha(PPTX),
    }
    write_json('object_audit.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def render_deck(export=True):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app, pres = None, None
    try:
        if not export:
            prior = json.loads((OUT / 'export_audit.json').read_text(encoding='utf-8'))
            for path in (PPTX, PNG, PDF):
                assert sha(path) == prior['exports'][path.suffix]['sha256'], f'交付物与原导出记录不符: {path.name}'
        try:
            app = win32com.client.GetActiveObject('PowerPoint.Application')
        except Exception:
            app = win32com.client.Dispatch('PowerPoint.Application')
        for attempt in range(12):
            try:
                pres = app.Presentations.Open(str(PPTX), True, False, False)
                assert pres.Slides.Count == 1
                break
            except Exception:
                if attempt == 11:
                    raise
                time.sleep(1)
        slide = pres.Slides.Item(1)
        slide_w_pt, slide_h_pt = pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight
        records, overflow = [], []

        def inspect(shapes):
            for i in range(1, shapes.Count + 1):
                s = shapes.Item(i)
                if s.Type == 6:
                    inspect(s.GroupItems)
                if s.HasTextFrame and s.TextFrame2.HasText:
                    tf, tr = s.TextFrame2, s.TextFrame2.TextRange
                    w, h = s.Width - tf.MarginLeft - tf.MarginRight, s.Height - tf.MarginTop - tf.MarginBottom
                    row = {'name': s.Name, 'text': tr.Text, 'available_pt': [w, h],
                           'bound_pt': [tr.BoundWidth, tr.BoundHeight],
                           'glyph_rect_pt': [tr.BoundLeft, tr.BoundTop, tr.BoundWidth, tr.BoundHeight],
                           'com_font': tr.Font.Name, 'com_font_size': tr.Font.Size}
                    assert tr.Font.Name == 'Times New Roman' and tr.Font.Size >= 22, row
                    records.append(row)
                    if tr.BoundWidth > w + 1.2 or tr.BoundHeight > h + 1.2:
                        overflow.append(row)
        # 先在 COM 新鲜时测量文字（溢出/重叠），再导出：PowerPoint 导出后常进入长忙态
        # 拒绝后续呼叫（图1/2/3 同款僵尸 COM）；测量前置避开该窗口，真实字体违规立即上抛不掩盖。
        time.sleep(4)
        for walk in range(20):
            records.clear()
            overflow.clear()
            try:
                inspect(pres.Slides.Item(1).Shapes)
                break
            except AssertionError:
                raise
            except Exception:
                if walk == 19:
                    raise
                time.sleep(6)
        if export:
            slide.Export(str(PNG), 'PNG', 4000, round(4000 * slide_h_pt / slide_w_pt))
            pres.SaveAs(str(PDF), 32)
        overlaps = []
        for i, a in enumerate(records):
            ax, ay, aw, ah = a['glyph_rect_pt']
            for b in records[i + 1:]:
                bx, by, bw, bh = b['glyph_rect_pt']
                ix = min(ax + aw, bx + bw) - max(ax, bx)
                iy = min(ay + ah, by + bh) - max(ay, by)
                if ix > 2 and iy > 1.2:
                    overlaps.append({'names': [a['name'], b['name']], 'intersection_pt': [ix, iy]})
        report = {'png': str(PNG), 'png_size': Image.open(PNG).size if PNG.exists() else None,
                  'pdf': str(PDF), 'pptx_sha256': sha(PPTX), 'actual_powerpoint_com': True,
                  'text_objects_checked': len(records), 'text_overflow': overflow,
                  'text_overlap': overlaps, 'overlap_tolerance_pt': [2, 1.2],
                  'text_measurements': records, 'export_performed_this_call': export,
                  'ppt_version': app.Version}
        write_json('render_audit.json', report)
        if overflow or overlaps:
            write_json('render_failure_' + str(time.time_ns()) + '.json', report)
        im = Image.open(PNG).convert('RGB')
        im.resize((1600, round(im.height * 1600 / im.width)), Image.Resampling.LANCZOS).save(OUT / 'overview.png')
        im.resize((1890, round(im.height * 1890 / im.width)), Image.Resampling.LANCZOS).save(OUT / 'print_160mm_300dpi.png', dpi=(300, 300))
        k = im.width / (slide_w_pt / 72)
        for i, key in enumerate(('candidate', 'checks', 'repair', 'release')):
            im.crop((round(COLS[i] * k), round(.40 * k), round((COLS[i] + COL_W) * k), round(8.10 * k))).save(OUT / f'detail_{key}.png')
        print(json.dumps({'rendered': True, 'text_overflow_count': len(overflow), 'overflow': overflow,
                          'text_overlap_count': len(overlaps), 'overlaps': overlaps}, ensure_ascii=False, indent=2))
        assert not overflow, 'PowerPoint 实测存在文字溢出'
        assert not overlaps, 'PowerPoint 实测存在文字重叠'
        audit_exports()
    except Exception as exc:
        write_json('render_error_' + str(time.time_ns()) + '.json', {'error': repr(exc), 'pptx': str(PPTX)})
        raise
    finally:
        # 僵尸COM下Close也会拒绝呼叫，不能让它掩盖真实结果。
        try:
            if pres is not None:
                pres.Close()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def audit_exports():
    import pymupdf as fitz
    with fitz.open(PDF) as doc:
        assert len(doc) == 1
        page = doc[0]
        spans = [s for b in page.get_text('dict')['blocks'] if 'lines' in b
                 for line_ in b['lines'] for s in line_['spans'] if s['text'].strip()]
        # 删冗+升档+首轮/归档统计移出图面后文本对象恰42个（与 object_audit 一致），下限钉42防静默丢字。
        assert len(spans) >= 42, len(spans)
        assert not page.get_images(full=True), '图4 PDF不应含位图'
        # PDF导出字号有-0.04pt舍入（图1的19pt实测18.96同款），阈值取标称-0.05。
        assert min(s['size'] for s in spans) >= 21.95
        assert Image.open(PNG).width == 4000
        pdf_fonts = sorted({s['font'] for s in spans})
        assert all('TimesNewRoman' in f.replace('-', '') for f in pdf_fonts), pdf_fonts
        assert not re.search(r'[\u3400-\u9fff]', page.get_text())
        assert all(f[1] != 'n/a' for f in page.get_fonts(full=True)), 'PDF字体未嵌入'
        image = Image.open(PNG).convert('RGB')
        refs = reference_images()
        scale = image.width / (page.rect.width / 72)
        checks, bad_total = {}, 0
        for prefix, source in refs.items():
            x, y, width = layout_of(prefix)
            pitch = width / 40
            bad = [(r, c) for r in range(40) for c in range(40)
                   if image.getpixel((round((x + (c + .5) * pitch) * scale), round((y + (r + .5) * pitch) * scale))) != source.getpixel((c, r))]
            checks[prefix] = {'cell_centers_checked': 1600, 'rgb_mismatches': len(bad)}
            bad_total += len(bad)
        result = {'pdf_pages': 1, 'pdf_text_spans': len(spans),
                  'pdf_min_font_pt': min(s['size'] for s in spans), 'pdf_fonts': pdf_fonts,
                  'pdf_image_objects': len(page.get_images(full=True)),
                  'pdf_vector_drawings': len(page.get_drawings()),
                  'scope_pixel_checks': checks, 'scope_rgb_mismatches': bad_total,
                  'png_pixels': Image.open(PNG).size,
                  'exports': {p.suffix: {'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size}
                              for p in (PPTX, PNG, PDF)}}
        assert not bad_total, result
        write_json('export_audit.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args()
    f1.FONT = 'Times New Roman'
    if args.verify:
        audit_deck()
        render_deck(export=False)
    else:
        build_deck()
        render_deck()


if __name__ == '__main__':
    main()
