#!/usr/bin/env python3
"""Temporary: layout of Utah's official results data."""
import json, gzip
from urllib.request import Request, urlopen
URL = 'https://electionresults.utah.gov/results/public/api/elections/Utah/general11032026/ballot-items'
req = Request(URL, headers={'User-Agent': 'election-2026 results reader (github.com/dwhitney2181/election-2026)', 'Accept-Encoding': 'gzip'})
with urlopen(req, timeout=60) as r:
    b = r.read()
    if r.headers.get('Content-Encoding') == 'gzip':
        b = gzip.decompress(b)
d = json.loads(b)
print('top keys:', {k: (v if not isinstance(v, list) else f'list[{len(v)}]') for k, v in d.items()})
names = [x['name'][0]['text'] for x in d['data']]
print('contests:', len(names))
print(json.dumps(names, separators=(',', ':'))[:6000])
for x in d['data']:
    n = x['name'][0]['text']
    if n in ('State House District 26', 'State Senate District 12', 'State House District 3'):
        x2 = dict(x)
        x2['summaryResults'] = {k: v for k, v in x['summaryResults'].items() if k != 'ballotOptions'}
        print('CONTEST', n, json.dumps(x2, separators=(',', ':'))[:1500])
        for o in x['summaryResults']['ballotOptions']:
            print('   ', o['name'][0]['text'], o['voteCount'], (o.get('party') or {}).get('name', [{}])[0].get('text') if o.get('party') else None,
                  o.get('isWriteIn'), o.get('isWinner'), {k: o[k] for k in o if k not in ('name', 'party', 'groupResults', 'id', 'nativeId')})
