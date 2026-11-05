#!/usr/bin/env python3
"""Temporary: report how candidate results pages are built, so a reader can be written."""
import json, re, sys
sys.path.insert(0, 'tools')
from scrape_multistate import fetch

URLS = [
    'https://abcnews.com/Elections/2026-us-house-election-results-live-map/',
    'https://abcnews.com/Elections/2026-us-senate-election-results-live-map/',
    'https://abcnews.com/Elections/2026-us-governor-election-results-live-map/',
    'https://www.nbcnews.com/politics/2026-elections/senate-results',
    'https://www.nbcnews.com/politics/2026-elections/governor-results',
    'https://www.nbcnews.com/politics/2026-elections/house-results',
    'https://politics.api.cnn.io/results/national-races/2026-SG.json',
    'https://www.multistate.us/elections/results/wisconsin-2026.html',
]


def keys(o, depth=0, path=''):
    out = []
    if depth > 4:
        return out
    if isinstance(o, dict):
        for k, v in list(o.items())[:25]:
            sz = len(json.dumps(v)) if not isinstance(v, (str, int, float, type(None))) else 0
            if sz > 3000:
                out.append(f'{path}.{k} ({sz//1000}KB, {type(v).__name__}{"[" + str(len(v)) + "]" if isinstance(v, list) else ""})')
                out += keys(v, depth + 1, f'{path}.{k}')
    elif isinstance(o, list) and o:
        out += keys(o[0], depth + 1, f'{path}[0]')
    return out


for u in URLS:
    print('=' * 100)
    print(u)
    try:
        t = fetch(u)
    except Exception as e:
        print('  FAILED:', str(e)[:200])
        continue
    title = re.search(r'<title[^>]*>(.*?)</title>', t, re.S)
    print(f'  {len(t)} chars | title: {title.group(1).strip()[:90] if title else "-"} | <table x{t.count("<table")} | __NEXT_DATA__ {"__NEXT_DATA__" in t} | application/json scripts x{len(re.findall(r"application/(?:ld\+)?json", t))}')
    blobs = re.findall(r'<script[^>]*>(.*?)</script>', t, re.S)
    big = sorted(blobs, key=len, reverse=True)[:3]
    for b in big:
        b = b.strip()
        m = re.match(r'^(?:window\.[\w$\[\]\'".]+\s*=\s*|self\.__next_f\.push\()?', b)
        body = b[m.end():] if m else b
        print(f'  script {len(b)} chars, starts: {b[:120]!r}')
        try:
            o = json.loads(body.rstrip(';').rstrip(')'))
            for line in keys(o)[:25]:
                print('     ', line)
        except Exception:
            pass
    for word in ('Wisconsin', 'Baldwin', 'Crowley', 'Tiffany', 'Ossoff', 'WI-03', 'Van Orden'):
        i = t.find(word)
        if i >= 0:
            print(f'  "{word}" at {i}: {t[max(0, i-200):i+250]!r}')
            break
    if u.endswith('.json'):
        print('  json head:', t[:600])
