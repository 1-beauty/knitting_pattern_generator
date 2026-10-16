import json, os, sys, traceback

try:
    base = r'e:\DeskTop\knitting_pattern_generator\outputs\runs\semantic'
    results = []
    missing = []

    for i in range(1, 101):
        sid = f'sem_{i:02d}'
        # Try both locations
        fpath = os.path.join(base, sid, f'{sid}_pattern_plan.json')
        if not os.path.exists(fpath):
            # Fallback: color_map subdirectory
            fpath2 = os.path.join(base, sid, 'color_map', f'{sid}_pattern_plan.json')
            if os.path.exists(fpath2):
                fpath = fpath2
            else:
                missing.append(sid)
                continue

        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        prompt = data['history'][0]['input']
        motifs = []
        for m in data['motifs']:
            motifs.append({
                'motif_id': m['motif_id'],
                'motif_type': m['motif_type'],
                'effect': m['effect'],
                'parent_id': m['parent_id'],
                'param_keys': sorted(list(m.get('params', {}).keys()))
            })
        
        results.append({
            'id': sid,
            'prompt': prompt,
            'motifs': motifs,
            'scoring': {
                'layout': None,
                'shape': None,
                'texture': None,
                'position': None,
                'parent': None,
                'params': None,
                'error_type': '',
                'note': ''
            }
        })

    if missing:
        print(f'MISSING {len(missing)} files: {missing}')

    out = os.path.join(base, 'scoring_sheet.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f'Done: {len(results)} records written. Missing: {len(missing)}. Output: {out}')

except Exception as e:
    traceback.print_exc()
    sys.exit(1)
