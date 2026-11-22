"""Symmetric decomposition from exhaustive disjoint observed counts."""
from collections import defaultdict
from math import fsum


def aggregate(rows, keys):
    groups = defaultdict(lambda: [0, 0])
    for row in rows:
        key = (row['period'], *(row[k] for k in keys))
        groups[key][0] += row['attempts']
        groups[key][1] += row['successes']
    return [dict(zip(['period', *keys], key), attempts=n, successes=s, rate=s/n if n else None)
            for key, (n, s) in sorted(groups.items())]


def decompose(rows, keys):
    cells = [{tuple(r[k] for k in keys): r for r in rows if r['period'] == i} for i in (0, 1)]
    totals = [sum(r['attempts'] for r in group.values()) for group in cells]
    if not all(totals) or cells[0].keys() != cells[1].keys() or any(r['attempts'] <= 0 for group in cells for r in group.values()):
        return {'available': False, 'reason': 'Empty population or appearing/disappearing segment; missing rates are undefined'}
    if any(len(group) != sum(r['period'] == i for r in rows) for i, group in enumerate(cells)):
        raise ValueError('Partition contains duplicate segment keys')
    parts = []
    for key in sorted(cells[0]):
        a, b = cells[0][key], cells[1][key]
        w0, w1 = a['attempts']/totals[0], b['attempts']/totals[1]
        r0, r1 = a['successes']/a['attempts'], b['successes']/b['attempts']
        parts.append(dict(zip(keys, key), mix=(w1-w0)*(r0+r1)/2,
                          within=(r1-r0)*(w0+w1)/2, rate_change=r1-r0))
    mix, within = fsum(p['mix'] for p in parts), fsum(p['within'] for p in parts)
    change = sum(r['successes'] for r in cells[1].values())/totals[1] - sum(r['successes'] for r in cells[0].values())/totals[0]
    if abs(mix + within - change) > 1e-10:
        raise ValueError('Decomposition failed to reconcile')
    return {'available': True, 'version': 'symmetric-1.0.0', 'mix': mix, 'within': within, 'change': change, 'parts': parts}
