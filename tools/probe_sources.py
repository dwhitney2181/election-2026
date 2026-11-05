#!/usr/bin/env python3
"""Temporary: report how candidate results pages are built, so a reader can be written."""
import json, re, sys
sys.path.insert(0, 'tools')
from scrape_multistate import fetch
from html.parser import HTMLParser


def robots(host):
    try:
        t = fetch(f'https://{host}/robots.txt') if False else None
    except Exception:
        pass
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(f'https://{host}/robots.txt', headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as r:
            txt = r.read().decode('utf-8', 'replace')
    except Exception as e:
        print(host, 'robots failed', e); return
    groups, cur = [], None
    for line in txt.splitlines():
        line = line.split('#')[0].strip()
        if not line: continue
        k, _, v = line.partition(':'); k = k.strip().lower(); v = v.strip()
        if k == 'user-agent':
            if cur is None or cur['rules']: cur = {'agents': [], 'rules': []}; groups.append(cur)
            cur['agents'].append(v)
        elif cur is not None and k in ('allow', 'disallow'):
            cur['rules'].append((k, v))
    for g in groups:
        if '*' in g['agents']:
            rel = [r for r in g['rules'] if any(x in r[1].lower() for x in ('elect', 'politic', '/api', 'result')) or r[1] in ('/', '')]
            print(f'{host} robots for *: {len(g["rules"])} rules; relevant: {rel[:15]}')


def walk(o, path='', hits=None, depth=0):
    if hits is None: hits = []
    if depth > 9 or len(hits) > 12: return hits
    if isinstance(o, dict):
        ks = set(o.keys())
        if ks & {'candidates', 'cands', 'candidateResults'} and len(json.dumps(o)) < 6000:
            hits.append((path, json.dumps(o)[:900]))
            return hits
        for k, v in o.items():
            if isinstance(v, (dict, list)): walk(v, f'{path}.{k}', hits, depth + 1)
    elif isinstance(o, list):
        for i, v in enumerate(o[:3]):
            walk(v, f'{path}[{i}]', hits, depth + 1)
    return hits


def sizes(o, path, depth=0, limit=3):
    if depth > limit or not isinstance(o, dict): return
    for k, v in o.items():
        s = len(json.dumps(v))
        if s > 20000:
            print(f'   {path}.{k}: {s//1000}KB {type(v).__name__}{"[" + str(len(v)) + "]" if isinstance(v, list) else ""}')
            sizes(v if isinstance(v, dict) else (v[0] if isinstance(v, list) and v and isinstance(v[0], dict) else None), f'{path}.{k}', depth + 1, limit)


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables = []; self.cell = None; self.row = None
    def handle_starttag(self, tag, a):
        if tag == 'table': self.tables.append([])
        elif tag == 'tr' and self.tables: self.row = []; self.tables[-1].append(self.row)
        elif tag in ('td', 'th') and self.row is not None: self.cell = []
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell = None
    def handle_data(self, d):
        if self.cell is not None: self.cell.append(d)


robots('abcnews.com'); robots('www.nbcnews.com')
for u in ['https://abcnews.com/Elections/2026-us-house-election-results-live-map/',
          'https://abcnews.com/Elections/2026-us-senate-election-results-live-map/',
          'https://abcnews.com/Elections/2026-us-governor-election-results-live-map/']:
    print('=' * 90); print(u)
    t = fetch(u)
    p = Tables(); p.feed(t)
    for tb in p.tables:
        print(f'  table rows={len(tb)} | first rows: {tb[:3]}')
    i = t.find("window['__CONFIG__']=")
    if i >= 0:
        o, _ = json.JSONDecoder().raw_decode(t, i + len("window['__CONFIG__']="))
        sizes(o, 'CONFIG', 0, 5)
        for path, s in walk(o)[:4]:
            print('  HIT', path); print('     ', s)
for u in ['https://www.nbcnews.com/politics/2026-elections/senate-results']:
    print('=' * 90); print(u)
    t = fetch(u)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    o = json.loads(m.group(1))
    sizes(o['props']['pageProps'], 'pageProps', 0, 4)
    for path, s in walk(o['props']['pageProps'])[:3]:
        print('  HIT', path); print('     ', s)
