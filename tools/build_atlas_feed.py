#!/usr/bin/env python3
"""Build atlas-feed.json and atlas-federal.json for the Legislative Atlas (dwhitney2181/legislative-atlas).

Reads leg_all.js (MultiState winners, all states) and results_all.js (Utah vote
counts) from the repository root and writes atlas-feed.json in the row format the
atlas server and page accept:

  state, chamber (upper/lower), district, seat, candidate, party, status,
  previous_party, votes, pct, reporting, updated, source, source_kind,
  source_url, multimember, members (seats in a multi-seat district), note

Rules (match the atlas's own conservative policy):
  * Only races with a reported winner are included; uncalled races are skipped.
  * previous_party is set only from an explicit "Flipped X to Y" note (or, for
    Utah, from the documented prior party of the seat).
  * Districts that elect several members on one ballot are split into one row
    per winner, marked multimember=true, with no per-seat flip claim.
  * Rows that list several winners from different parties are skipped, since
    the source does not say which winner belongs to which party.

Usage:  python3 tools/build_atlas_feed.py [repo_root]
"""
from __future__ import annotations
import json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else Path(__file__).resolve().parent.parent

PARTY = {'R': 'R', 'D': 'D', 'I': 'I', 'NP': 'N', 'N': 'N', 'F': 'F', 'O': 'O', 'NONPARTISAN': 'N',
         'C': 'O', 'L': 'O', 'G': 'O', 'IAP': 'O', 'U': 'I'}
SUFFIX = re.compile(r'^(jr\.?|sr\.?|ii|iii|iv)$', re.I)
TZ = {'ET': -5, 'CT': -6, 'MT': -7, 'PT': -8, 'AKT': -9, 'HT': -10}


def load_js(path: Path):
    s = path.read_text(encoding='utf-8')
    return json.loads(s[s.index('{'):s.rindex('}') + 1])


def iso_from_asof(asof: str, fallback: str) -> str:
    """'11:50 a.m. MT, Nov. 4, 2026' -> '2026-11-04T18:50:00+00:00'."""
    m = re.match(r'\s*(\d{1,2}):(\d{2})\s*([ap])\.?m\.?\s*([A-Z]{2,3}),\s*([A-Za-z]{3})[a-z]*\.?\s*(\d{1,2}),\s*(\d{4})', asof or '')
    if not m:
        return fallback
    hh, mm, ap, tz, mon, day, yr = m.groups()
    h = int(hh) % 12 + (12 if ap.lower() == 'p' else 0)
    month = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'].index(mon.lower()) + 1
    local = datetime(int(yr), month, int(day), h, int(mm), tzinfo=timezone(timedelta(hours=TZ.get(tz, -5))))
    return local.astimezone(timezone.utc).isoformat(timespec='seconds')


def split_names(w: str):
    parts = [p.strip() for p in w.split(',') if p.strip()]
    out = []
    for p in parts:
        if out and SUFFIX.match(p):
            out[-1] += ', ' + p
        else:
            out.append(p)
    return out


def clean_district(d: str) -> str:
    d = str(d).strip().replace(',', '')
    d = re.sub(r'\s+', ' ', d)
    m = re.fullmatch(r'0*(\d+)([A-Za-z]?)', d)
    return (m.group(1) + m.group(2).upper()) if m else d


def flip_from(notes: str, party: str):
    m = re.search(r'flipped\s+([A-Za-z]+)\s+to\s+([A-Za-z]+)', notes or '', re.I)
    if not m:
        return None
    old, new = PARTY.get(m.group(1).upper()), PARTY.get(m.group(2).upper())
    return old if old and new == party and old != party else None


def build(leg='leg_all.js', out_name='atlas-feed.json', stable=False):
    L = load_js(ROOT / leg)
    A = load_js(ROOT / 'results_all.js')
    fallback = L.get('updated_utc') or datetime.now(timezone.utc).isoformat(timespec='seconds')
    races, skipped = [], []
    for st, o in sorted(L['states'].items()):
        if st == 'UT':
            continue  # Utah comes from the vote-count table below
        updated = iso_from_asof(o.get('asof', ''), fallback)
        url = o.get('url') or 'https://www.multistate.us/elections/'
        for c in o['chambers']:
            ch = 'upper' if ('senate' in c['name'].lower() or st == 'NE') else 'lower'
            seen = {}
            for r in c['races']:
                d = clean_district(r['d'])
                seen[d] = seen.get(d, 0) + 1
                w = (r.get('w') or '').strip()
                wp = str(r.get('wp') or '').strip()
                if not w:
                    # A lone candidate with no opponent is elected even before the source fills its winner column.
                    m = re.fullmatch(r'Unopposed:\s*([^,()]+?)\s*\(([^)]+)\)', (r.get('others') or '').strip())
                    if not m:
                        continue
                    w, wp = m.group(1).strip(), m.group(2).strip()
                    r = {**r, 'notes': r.get('notes') or 'Unopposed'}
                elif not r.get('called', True):
                    continue
                party = PARTY.get(wp.upper())
                names = split_names(w)
                if wp == 'mixed' or not party:
                    skipped.append(f'{st} {c["name"]} {d}: {w} ({wp or "no party"})')
                    continue
                base = {'state': st, 'chamber': ch, 'district': d, 'party': party,
                        'status': 'reported', 'votes': None, 'reporting': None, 'updated': updated,
                        'source_kind': 'multistate',
                        'source': 'MultiState reported winner (publisher-reported; not certified)',
                        'source_url': url}
                note = (r.get('notes') or '').strip()
                if len(names) > 1:
                    for i, n in enumerate(names, 1):
                        races.append({**base, 'candidate': n, 'seat': f'member-{i}', 'previous_party': None,
                                      'multimember': True, 'members': len(names),
                                      'note': (note + '; ' if note else '') + f'{len(names)} members elected together in this district'})
                else:
                    row = {**base, 'candidate': names[0], 'seat': '', 'previous_party': flip_from(note, party),
                           'multimember': False}
                    if note:
                        row['note'] = note
                    races.append(row)
            # Several separately listed contests in one district (e.g. WA/ID positions): give each its own seat
            dup = {d for d, n in seen.items() if n > 1}
            if dup:
                counter = {}
                for row in races:
                    if row['state'] == st and row['chamber'] == ch and row['district'] in dup and not row['multimember']:
                        counter[row['district']] = counter.get(row['district'], 0) + 1
                        row['seat'] = f'position-{counter[row["district"]]}'
                        row['members'] = seen[row['district']]
                        row['note'] = ((row.get('note') or '') + '; ' if row.get('note') else '') + \
                            'position number follows the order MultiState lists the contests'
    # Utah: vote counts from the Utah table in results_all.js
    meta = A.get('meta', {})
    ut_updated = L['states'].get('UT', {}).get('asof') or fallback
    for r in A.get('leg_ut', []):
        cands = sorted(r.get('c') or [], key=lambda x: -(x.get('votes') or 0))
        if not cands or not cands[0].get('votes'):
            continue
        top = cands[0]
        party = PARTY.get(str(top.get('party', '')).upper())
        if not party:
            continue
        ch = 'upper' if 'senate' in r['office'].lower() else 'lower'
        margin = round((top.get('pct') or 0) - (cands[1].get('pct') or 0), 2) if len(cands) > 1 else 100.0
        prior = PARTY.get(str(r.get('prior') or '').upper())
        races.append({'state': 'UT', 'chamber': ch, 'district': clean_district(r['d']), 'seat': '',
                      'candidate': top['name'], 'party': party,
                      'status': 'called' if r.get('called') else 'leading',
                      'previous_party': prior, 'votes': top.get('votes'), 'pct': top.get('pct'),
                      'margin': margin, 'reporting': None,
                      'updated': iso_from_asof(ut_updated, fallback) if isinstance(ut_updated, str) else fallback,
                      'source_kind': 'news',
                      'source': 'Utah News Dispatch election-night vote tables (unofficial); race calls from MultiState',
                      'source_url': 'https://www.yahoo.com/news/politics/articles/utah-legislature-2026-election-night-045111772.html',
                      'multimember': False})
    feed = {'meta': {'source': 'Compiled for the Legislative Atlas from MultiState reported winners and Utah unofficial returns',
                     'generated_utc': fallback if stable else datetime.now(timezone.utc).isoformat(timespec='seconds'),
                     'data_as_of_utc': fallback,
                     'states': sorted({r['state'] for r in races}),
                     'rows': len(races),
                     'skipped_mixed_party_multi_winner': skipped,
                     'notes': 'Unofficial. Only races with a reported winner are listed. previous_party is set only where a source says the seat flipped (or, in Utah, the documented prior party).'},
            'races': races}
    out = ROOT / out_name
    out.write_text(json.dumps(feed, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    return feed


def build_federal():
    """atlas-federal.json: U.S. House, U.S. Senate, governors and delegates for the atlas."""
    A = load_js(ROOT / 'results_all.js')
    F = load_js(ROOT / 'flips.js')
    meta = dict(A.get('meta', {}))
    fm = F.get('meta', {})
    flips = {}
    for i in F.get('items', []):
        if i.get('kind') in ('house', 'gov'):
            flips[(i['kind'], i['st'], str(i.get('dist') or ''))] = {
                k: i.get(k) for k in ('winner', 'wp', 'loser', 'fr', 'to', 'status', 'src', 'url', 'note', 'incdef')}
    house = []
    for r in A.get('house', []):
        dem, rep = r.get('dem'), r.get('rep')
        lead = None
        if isinstance(dem, (int, float)) and isinstance(rep, (int, float)) and dem != rep:
            lead = 'D' if dem > rep else 'R'
        note = (r.get('note') or '').lower()
        fl = flips.get(('house', r['st'], str(r['d'])))
        status = 'called' if 'gain' in note or (fl and fl.get('status') == 'called') else (
            'leading' if 'lead' in note else '')
        row = {'st': r['st'], 'd': r['d'], 'dem': dem, 'rep': rep, 'oth': r.get('oth'), 'inn': r.get('inn'),
               'lead': lead, 'status': status, 'note': r.get('note') or '', 'rating': r.get('rating') or '',
               'who': r.get('who') or ''}
        if r.get('fox'):
            row['fox'] = r['fox']
        if fl:
            row['flip'] = fl
            if fl.get('winner'):
                row['who'] = fl['winner']
        house.append(row)

    def statewide(rows, kind):
        out = []
        for r in rows:
            row = dict(r)
            row['flip'] = bool(r.get('win') and r.get('prior') and r['win'] != r['prior'] and r.get('status') in ('called', 'leading'))
            fl = flips.get((kind, r['st'], '')) if kind else None
            if fl:
                row['flip_src'] = fl.get('src')
                row['flip_url'] = fl.get('url')
            out.append(row)
        return out

    fed = {'meta': {'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'asof': fm.get('asof', ''),
                    'house_src': meta.get('house_src'), 'house_url': meta.get('house_url'), 'house_asof': meta.get('house_asof'),
                    'fox_url': meta.get('fox_url'),
                    'gov_src': meta.get('gov_src'), 'gov_url': meta.get('gov_url'),
                    'sen_src': meta.get('sen_src'), 'sen_url': meta.get('sen_url'),
                    'house_context': fm.get('house_context', ''), 'house_context_urls': fm.get('house_context_urls', []),
                    'notes': 'Unofficial. House percentages from the named results table; a district is called only when a source called it.'},
           'house': house,
           'senate': statewide(A.get('sen', []), None),
           'governors': statewide(A.get('gov', []), 'gov'),
           'delegates': statewide(A.get('house_del', []), None),
           'pending_gov': F.get('pending_gov', [])}
    (ROOT / 'atlas-federal.json').write_text(json.dumps(fed, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    return fed


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('root', nargs='?', default=None)
    ap.add_argument('--leg', default='leg_all.js', help='legislative tables to read (leg_all.js or leg_live.json)')
    ap.add_argument('--out', default='atlas-feed.json', help='legislative feed file to write')
    ap.add_argument('--no-federal', action='store_true', help='skip atlas-federal.json')
    args = ap.parse_args()
    if args.no_federal:
        f = build(args.leg, args.out, stable=True)
        print(f"wrote {args.out}: {f['meta']['rows']} rows, {len(f['meta']['states'])} states")
        raise SystemExit(0)
    fd = build_federal()
    print(f"wrote atlas-federal.json: {len(fd['house'])} House districts, {len(fd['senate'])} Senate races, "
          f"{len(fd['governors'])} governor races, {len(fd['delegates'])} delegates")
    f = build()
    print(f"wrote atlas-feed.json: {f['meta']['rows']} rows, {len(f['meta']['states'])} states, "
          f"{len(f['meta']['skipped_mixed_party_multi_winner'])} mixed multi-winner rows skipped")
