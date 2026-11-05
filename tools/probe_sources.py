#!/usr/bin/env python3
"""Temporary: show the structure of NBC's full race lists."""
import json, re, sys
sys.path.insert(0, 'tools')
from scrape_multistate import fetch

def show(o, path, depth=0):
    if depth > 3: return
    if isinstance(o, dict):
        print('  ' * depth + f'{path}: dict keys={list(o.keys())[:30]}')
        for k, v in list(o.items())[:30]:
            if isinstance(v, (dict, list)) and len(json.dumps(v)) > 400:
                show(v, f'{path}.{k}', depth + 1)
    elif isinstance(o, list):
        print('  ' * depth + f'{path}: list[{len(o)}] first={json.dumps(o[0])[:700] if o else None}')

for office in ('senate', 'governor', 'house'):
    u = f'https://www.nbcnews.com/politics/2026-elections/{office}-results'
    print('=' * 90); print(u)
    t = fetch(u)
    o = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S).group(1))
    pp = o['props']['pageProps']
    print(' pageProps keys:', list(pp.keys()))
    show(pp.get('mapData'), 'mapData')
    for k in ('racesToWatchData', 'balanceOfPower', 'bopData', 'raceResults', 'results', 'tableData', 'stateResults'):
        if k in pp: show(pp[k], k)
    # find any list with >= 30 dicts having stateAbbr
    def find(o, path=''):
        if isinstance(o, list) and len(o) >= 30 and isinstance(o[0], dict) and ('stateAbbr' in o[0] or 'state' in o[0] or 'stateCode' in o[0]):
            print(f' BIG LIST {path}: {len(o)} items; first={json.dumps(o[0])[:900]}')
            return
        if isinstance(o, dict):
            for k, v in o.items(): find(v, f'{path}.{k}')
        elif isinstance(o, list):
            for i, v in enumerate(o[:2]): find(v, f'{path}[{i}]')
    find(pp, 'pageProps')
