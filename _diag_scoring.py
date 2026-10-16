import json, os, sys

base = r'e:\DeskTop\knitting_pattern_generator\outputs\runs\semantic'

# First, list all sem_XX directories
dirs = sorted([d for d in os.listdir(base) if d.startswith('sem_') and os.path.isdir(os.path.join(base, d))])
print(f'Total sem_XX directories: {len(dirs)}')

# For each, check both possible locations
found = []
missing = []
for d in dirs:
    # Path A: sem_XX/color_map/sem_XX_pattern_plan.json
    pathA = os.path.join(base, d, 'color_map', f'{d}_pattern_plan.json')
    # Path B: sem_XX/sem_XX_pattern_plan.json
    pathB = os.path.join(base, d, f'{d}_pattern_plan.json')
    
    if os.path.exists(pathA):
        found.append((d, pathA))
    elif os.path.exists(pathB):
        found.append((d, pathB))
    else:
        missing.append(d)

print(f'Found pattern_plan.json: {len(found)}')
print(f'Missing: {len(missing)}')
if missing:
    print('Missing dirs:')
    for m in missing:
        # List what's actually in that dir
        dirpath = os.path.join(base, m)
        contents = os.listdir(dirpath)
        print(f'  {m}: {contents}')
