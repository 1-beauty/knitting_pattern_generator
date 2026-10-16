# -*- coding: utf-8 -*-
"""Replace Fig3 image blob AND fix display extent (aspect changed 2700->2400)."""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from docx import Document
from docx.oxml.ns import qn

DOCX_PATH = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'
NEW_PNG = r'e:\DeskTop\knitting_pattern_generator\docs\figures\Fig3_Event_Level_Constraint_Compilation_EN.png'

doc = Document(DOCX_PATH)

# Identify Fig3 image rel (rId38)
target_rid = None
for rid, rel in doc.part.rels.items():
    if 'image' in rel.reltype and 'rId38' in rid:
        target_rid = rid
        print(f"Fig3 image: {rid} -> {rel.target_ref} ({len(rel.target_part.blob)//1024} KB)")
        break
assert target_rid, "rId38 not found"

# Replace blob
new_blob = open(NEW_PNG, 'rb').read()
doc.part.rels[target_rid].target_part._blob = new_blob
print(f"Blob replaced: {len(new_blob)//1024} KB")

# New aspect: 5225 x 2400
NEW_W, NEW_H = 5225, 2400
ASPECT = NEW_H / NEW_W  # 0.4593

# Find the inline drawing referencing rId38 and update extent
body = doc.element.body
updated = 0
for blip in body.iter(qn('a:blip')):
    embed = blip.get(qn('r:embed'))
    if embed == target_rid:
        # walk up to inline
        node = blip
        while node is not None and node.tag != qn('wp:inline'):
            node = node.getparent()
        if node is None:
            continue
        # wp:extent
        ext = node.find(qn('wp:extent'))
        old_cx = int(ext.get('cx')); old_cy = int(ext.get('cy'))
        new_cy = int(old_cx * ASPECT)
        ext.set('cx', str(old_cx)); ext.set('cy', str(new_cy))
        # a:ext inside spPr/xfrm
        for aext in node.iter(qn('a:ext')):
            aext.set('cx', str(old_cx)); aext.set('cy', str(new_cy))
        print(f"Extent: cx={old_cx} cy {old_cy} -> {new_cy} (EMU), "
              f"display {old_cx/360000:.2f}x{old_cy/360000:.2f}cm -> {old_cx/360000:.2f}x{new_cy/360000:.2f}cm")
        updated += 1
print(f"Updated {updated} drawing extent(s)")

doc.save(DOCX_PATH)
print(f"Saved: {DOCX_PATH}")
