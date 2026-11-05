#!/usr/bin/env python3
"""Read Utah's official results (Lieutenant Governor's election results site) and write utah_live.json.

The public results site at electionresults.utah.gov loads its numbers from a JSON feed
(/results/public/api/elections/Utah/<election>/ballot-items). This keeps every state House
and state Senate race (plus the four U.S. House races, for reference) with each candidate's
vote count. If the feed can't be read, or comes back incomplete, the previous file is kept.
Standard library only.
"""
from __future__ import annotations
import gzip, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'utah_live.json'
ELECTION = 'general11032026'
SITE = f'https://electionresults.utah.gov/results/public/Utah/elections/{ELECTION}'
API = f'https://electionresults.utah.gov/results/public/api/elections/Utah/{ELECTION}'
PARTY = {'democratic': 'D', 'republican': 'R', 'unaffiliated': 'U', 'forward': 'F', 'constitution': 'C',
         'libertarian': 'L', 'green': 'G', 'independent american': 'IA', 'united utah': 'UU'}


def get(url):
    req = Request(url, headers={'User-Agent': 'election-2026 results reader (github.com/dwhitney2181/election-2026)',
                                'Accept': 'application/json', 'Accept-Encoding': 'gzip'})
    with urlopen(req, timeout=60) as r:
        b = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            b = gzip.decompress(b)
    return json.loads(b.decode('utf-8'))


def text(v):
    if isinstance(v, list):
        return next((x.get('text') for x in v if x.get('languageId') == 'en'), v[0].get('text') if v else '') or ''
    return v or ''


def main():
    prev = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    try:
        meta = get(API)
        items = get(API + '/ballot-items')['data']
    except Exception as e:
        sys.exit(f'Utah results feed could not be read ({str(e)[:150]}); keeping utah_live.json as it was')
    races = {}
    for it in items:
        m = re.match(r'(State House|State Senate|U\.S\. House) District (\d+)', text(it.get('name')))
        if not m or it.get('contestType') != 'Candidate':
            continue
        opts = []
        for o in (it.get('summaryResults') or {}).get('ballotOptions') or []:
            pname = text((o.get('party') or {}).get('name')).strip().lower()
            write_in = bool(o.get('isWriteIn') or o.get('isQualifiedWriteIn'))
            opts.append({'name': ' '.join(text(o.get('name')).split()),
                         'party': 'W' if write_in and not pname else PARTY.get(pname, 'O' if pname else ''),
                         'votes': int(o.get('voteCount') or 0), 'write_in': write_in,
                         'winner': o.get('isWinner')})
        rs = it.get('reportingStatus') or {}
        races[f'{m.group(1)}|{m.group(2)}'] = {'total': it.get('voteTotal'), 'reporting': [rs.get('reportingUnits'), rs.get('totalUnits')],
                                               'asof': rs.get('asOf'), 'c': opts}
    leg = sum(1 for k in races if not k.startswith('U.S.'))
    if leg < 85:
        sys.exit(f'only {leg} legislative races in the Utah feed; keeping utah_live.json as it was')
    data = {'source': "Utah Lieutenant Governor's Office, election results site", 'url': SITE,
            'official': bool(meta.get('isOfficialResults')), 'asof_utc': meta.get('asOf') or meta.get('lastUpdated'),
            'races': races}
    if prev.get('races') == data['races'] and prev.get('official') == data['official']:
        print(f"Utah: no new counts since {prev.get('asof_utc')}")
        return
    data['read_utc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"Utah: {leg} legislative races, as of {data['asof_utc']}{' (official)' if data['official'] else ''}")


if __name__ == '__main__':
    main()
