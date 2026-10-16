# -*- coding: utf-8 -*-
"""Fix Table 6 position: move correct 44-input table to after its caption,
remove old 8-input table, and fix column widths for all wide tables."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, Emu
from copy import deepcopy

DOCX = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
doc = Document(DOCX)
body = doc.element.body

# === Step 1: Identify the two tables ===
# tbl[5] at body-child-97: CORRECT 44-input table (orphaned in methods section)
# tbl[15] at body-child-191: OLD 8-input table (wrongly after Table 6 caption)

tbl_elements = []
for el in body.iterchildren():
    if el.tag == qn('w:tbl'):
        tbl_elements.append(el)

tbl5_el = tbl_elements[5]   # correct 44-input
tbl15_el = tbl_elements[15]  # old 8-input

# Verify
def get_first_row_text(tbl_el):
    texts = tbl_el.findall('.//' + qn('w:t'))
    return ''.join(t.text or '' for t in texts[:20])

print("tbl[5] content start:", get_first_row_text(tbl5_el)[:60])
print("tbl[15] content start:", get_first_row_text(tbl15_el)[:60])

# Verify tbl[5] has 44-input data
assert '44' in get_first_row_text(tbl5_el), "tbl[5] doesn't have 44-input data!"
assert '8 / 8' in get_first_row_text(tbl15_el), "tbl[15] doesn't have old 8-input data!"

# === Step 2: Find Table 6 caption position ===
# The caption "Table 6 Controlled comparison on 44 expanded..." is at body-child-190
caption_idx = None
for ki, el in enumerate(body.iterchildren()):
    if el.tag == qn('w:p'):
        texts = el.findall('.//' + qn('w:t'))
        txt = ''.join(t.text or '' for t in texts)
        if txt.startswith('Table 6 Controlled comparison'):
            caption_idx = ki
            print(f"Table 6 caption at body-child-{ki}")
            break

assert caption_idx is not None, "Table 6 caption not found!"

# === Step 3: Remove old table (tbl[15]) and insert correct table (tbl[5]) ===
# Save reference to the correct table element
correct_tbl = deepcopy(tbl5_el)

# Remove orphaned correct table from methods section
body.remove(tbl5_el)
print("Removed orphaned tbl[5] from body-child-97")

# Re-find positions after removal (indices shifted)
# Find old table again
old_tbl_found = False
for el in body.iterchildren():
    if el.tag == qn('w:tbl'):
        if el is tbl15_el:
            old_tbl_found = True
            break

# Remove old 8-input table
body.remove(tbl15_el)
print("Removed old tbl[15] (8-input)")

# Re-find caption position after removals
caption_el = None
for el in body.iterchildren():
    if el.tag == qn('w:p'):
        texts = el.findall('.//' + qn('w:t'))
        txt = ''.join(t.text or '' for t in texts)
        if txt.startswith('Table 6 Controlled comparison'):
            caption_el = el
            break

assert caption_el is not None
caption_pos = list(body).index(caption_el)
print(f"Caption now at body-child-{caption_pos}")

# Insert correct table right after caption
body.insert(caption_pos + 1, correct_tbl)
print("Inserted correct 44-input table after Table 6 caption")

# === Step 4: Fix column widths for Tables 5, 6, 7 ===
# Re-enumerate tables
doc2_tables = doc.tables

# Find Table 6 (44-input, 7 cols) - should now be after its caption
# Find Table 7 (preview, 9 cols)
# Find Table 5 (ablation, 9 cols)

def set_col_widths(tbl, widths_cm):
    """Set column widths in cm."""
    for i, w in enumerate(widths_cm):
        tbl.columns[i].width = Cm(w)
    # Also set cell widths for each row
    for row in tbl.rows:
        for i, cell in enumerate(row.cells):
            if i < len(widths_cm):
                cell.width = Cm(widths_cm[i])

# Identify tables by their header content
for ti, tbl in enumerate(doc2_tables):
    if len(tbl.columns) < 5:
        continue
    hdr0 = tbl.cell(0, 0).text.strip()
    hdr_last = tbl.cell(0, len(tbl.columns)-1).text.strip()
    
    # Table 6: 7 cols, starts with "Method", has "p (grouping)" or "Grouping"
    if len(tbl.columns) == 7 and hdr0 == 'Method' and '44' in tbl.cell(1, 2).text:
        print(f"\nFixing Table 6 (tbl[{ti}]) column widths")
        # Method needs most space (Plan-Grid+Repair), p needs least
        widths = [3.4, 1.8, 2.2, 2.3, 1.7, 2.8, 1.7]  # total 15.9
        set_col_widths(tbl, widths)
        print(f"  New widths: {widths} = {sum(widths):.1f}cm")
    
    # Table 7: 9 cols, starts with "Stage"
    elif len(tbl.columns) == 9 and hdr0 == 'Stage':
        print(f"\nFixing Table 7 (tbl[{ti}]) column widths")
        # SeamErr_diff and BoundaryF1 need more, KID needs less
        widths = [1.5, 1.5, 1.5, 1.6, 2.2, 2.1, 2.1, 1.4, 2.0]  # total 15.9
        set_col_widths(tbl, widths)
        print(f"  New widths: {widths} = {sum(widths):.1f}cm")
        # Also shorten "SeamErr_diff" to "SeamErr" to prevent mid-word break
        cell = tbl.cell(0, 4)
        for p in cell.paragraphs:
            for r in p.runs:
                if 'SeamErr_diff' in r.text:
                    r.text = r.text.replace('SeamErr_diff', 'SeamErr')
                    print("  Shortened header: SeamErr_diff -> SeamErr")
    
    # Table 5: 9 cols, starts with "Setting"
    elif len(tbl.columns) == 9 and hdr0 == 'Setting':
        print(f"\nFixing Table 5 (tbl[{ti}]) column widths")
        # Setting and Focus need more, Mean cols need less
        widths = [1.5, 2.4, 1.7, 1.7, 1.9, 1.5, 1.5, 1.4, 2.3]  # total 15.9
        set_col_widths(tbl, widths)
        print(f"  New widths: {widths} = {sum(widths):.1f}cm")

# === Step 5: Save ===
doc.save(DOCX)
print(f"\nSaved: {DOCX}")
