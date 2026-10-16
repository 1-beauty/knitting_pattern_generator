import json, sys
data = json.load(open(r"e:\DeskTop\knitting_pattern_generator\scripts\pptx_design.json", encoding="utf-8"))
targets = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else [2,3,5,7,10,12]
for sl in data["slides"]:
    if sl["idx"] not in targets:
        continue
    print("="*90)
    print("SLIDE", sl["idx"])
    for sh in sl["shapes"]:
        g = sh["geom"]
        # skip tiny decorative color squares (no text, < 0.2in)
        if not sh.get("paras") and g[2] and g[3] and g[2] < 0.2 and g[3] < 0.2:
            continue
        gs = f"L{g[0]} T{g[1]} W{g[2]} H{g[3]}"
        print(f"  #{sh['id']:>3} {sh['name'][:14]:<14} auto={sh.get('auto')} fill={sh.get('fill')} line={sh.get('line')} anchor={sh.get('anchor')}")
        print(f"       {gs}")
        for pi, p in enumerate(sh.get("paras", [])):
            runs = p.get("runs", [])
            rtxt = " || ".join(f"[{r['t']}|sz{r['sz']}|b{r['b']}|{r['color']}|{r['name']}]" for r in runs)
            if rtxt:
                print(f"       p{pi} align={p['align']} lvl={p['lvl']}: {rtxt}")
