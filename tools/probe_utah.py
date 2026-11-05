#!/usr/bin/env python3
"""Temporary: find where Utah's official results site gets its data."""
import re, sys, json
from urllib.request import Request, urlopen
sys.path.insert(0, 'tools')
from scrape_multistate import fetch

BASE = 'https://electionresults.utah.gov'
def get(url, n=600):
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0 (election-2026 results reader)', 'Accept': '*/*'})
        with urlopen(req, timeout=40) as r:
            b = r.read()
            enc = r.headers.get('Content-Encoding', '')
            if enc == 'gzip':
                import gzip; b = gzip.decompress(b)
            elif enc == 'br':
                import brotli; b = brotli.decompress(b)
            t = b.decode('utf-8', 'replace')
            print(f'== {url} -> {r.status} {r.headers.get("Content-Type")} {len(t)} chars')
            print(t[:n].replace('\n', ' ')); return t
    except Exception as e:
        print(f'== {url} -> ERROR {str(e)[:200]}'); return ''

get(BASE + '/robots.txt', 800)
home = get(BASE + '/results/public/Utah/elections/general11032026', 1500)
srcs = re.findall(r'(?:src|href)="([^"]+\.js[^"]*)"', home)
print('scripts:', srcs)
found = set()
for s in srcs[:8]:
    url = s if s.startswith('http') else BASE + ('' if s.startswith('/') else '/results/public/Utah/elections/') + s
    js = get(url, 0)
    for m in re.findall(r'["\'`]([^"\'`\s]{0,80}(?:api|/results/public)[^"\'`\s]{0,120})["\'`]', js):
        found.add(m)
print('API-like strings:', json.dumps(sorted(found)[:80], indent=0))
for path in ['/results/public/api/elections/Utah/general11032026',
             '/results/public/api/elections/Utah/general11032026/ballot-items',
             '/api/elections/Utah/general11032026',
             '/results/public/api/elections/Utah']:
    get(BASE + path, 1200)
