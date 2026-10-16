from docx import Document
from docx.oxml.ns import qn

PATH = r"e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx"
d = Document(PATH)
M_OMATH = qn('m:oMath')
M_T = qn('m:t')
W_T = qn('w:t')

# ---- 1) fix p057: drop the stray Omega' oMath sitting inside the equation reference ----
p057 = None
for p in d.paragraphs:
    if "structural prerequisite for the subsequent scope clipping" in p.text:
        p057 = p
        break
oms = p057._p.findall('.//' + M_OMATH)
removed = 0
for om in oms:
    mt = "".join(t.text or "" for t in om.findall('.//' + M_T))
    if mt.strip() in ("\u03a9'", "\u03a9\u2019", "Ω'"):
        om.getparent().remove(om)
        removed += 1
print("p057 oMath removed:", removed)

# ---- 2) scan whole doc for other '(Eq.' immediately followed by an oMath (symbol-as-number misuse) ----
print("\n=== scan: equation-reference nodes across document ===")
suspect = 0
for pi, p in enumerate(d.paragraphs):
    # build document-order token list
    toks = []
    for node in p._p.iter():
        if node.tag == M_T:
            toks.append(("M", node.text or ""))
        elif node.tag == W_T:
            toks.append(("T", node.text or ""))
    joined = "".join(t[1] for t in toks)
    if "(Eq." in joined or "(eq." in joined:
        # find each '(Eq.' and report the next ~12 chars (with MATH markers)
        idx = 0
        while True:
            k = joined.find("(Eq.", idx)
            if k < 0:
                break
            snippet = joined[k:k+14]
            # detect if an oMath sits right after '(Eq. '
            has_math_after = any(
                kind == "M" for kind, _ in toks
            ) and "(Eq. " in joined and snippet.replace(" ", "").startswith("(Eq.")
            flag = ""
            # a clean numeric ref looks like '(Eq. (5))' -> after '(Eq. ' comes '('
            after = joined[k+5:k+7]
            if not after.startswith("("):
                flag = "  <-- SUSPECT (no numeric '(n)' after 'Eq.')"
                suspect += 1
            print(f"  p{pi:03d}: {snippet!r}{flag}")
            idx = k + 4

print("\nsuspect equation refs:", suspect)

# ---- save ----
try:
    d.save(PATH)
    saved = PATH
except PermissionError:
    saved = r"e:\DeskTop\knitting_pattern_generator\docs\论文to_cii_fix9a.docx"
    d.save(saved)
    print("WARNING: locked, saved bypass:", saved)

# ---- verify ----
d2 = Document(saved)
j2 = "\n".join(p.text for p in d2.paragraphs)
print("\n=== VERIFY p057 ===")
print("'scope clipping (Eq. (5)) and local editing' present:",
      "scope clipping (Eq. (5)) and local editing" in j2)
print("no stray \"(Eq. (5)Ω')\":", "(Eq. (5)\u03a9" not in j2 and "(5)Ω" not in j2)
for p in d2.paragraphs:
    if "structural prerequisite for the subsequent scope clipping" in p.text:
        seg = p.text[p.text.find("scope clipping"):][:40]
        print("p057 tail now:", repr(seg))
        print("p057 oMath count now:", len(p._p.findall('.//' + qn('m:oMath'))))
        break
