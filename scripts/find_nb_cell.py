import json
nb = json.load(open('notebooks/analysis.ipynb', encoding='utf-8'))
for i, cell in enumerate(nb['cells']):
    src = ''.join(cell.get('source', []))
    if 'os.makedirs' in src or 'plt.savefig' in src:
        ctype = cell['cell_type']
        first = src[:80].replace('\n', ' ')
        print(f"Cell {i}: type={ctype}, snippet={first!r}")
