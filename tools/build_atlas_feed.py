#!/usr/bin/env python3
"""Build atlas-feed.json for the Legislative Atlas (dwhitney2181/legislative-atlas).

Reads leg_all.js (MultiState winners, all states) and results_all.js (Utah vote
counts) from the repository root and writes atlas-feed.json in the row format the
atlas server and page accept:

  state, chamber (upper/lower), district, seat, candidate, party, status,
  previous_party, votes, pct, reporting, updated, source, source_kind,
  source_url, multimember, note

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

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent

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


def build():
    L = load_js(ROOT / 'leg_all.js')
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
                                      'multimember': True,
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
                     'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                     'data_as_of_utc': fallback,
                     'states': sorted({r['state'] for r in races}),
                     'rows': len(races),
                     'skipped_mixed_party_multi_winner': skipped,
                     'notes': 'Unofficial. Only races with a reported winner are listed. previous_party is set only where a source says the seat flipped (or, in Utah, the documented prior party).'},
            'races': races}
    out = ROOT / 'atlas-feed.json'
    out.write_text(json.dumps(feed, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    return feed


if __name__ == '__main__':
    f = build()
    print(f"wrote atlas-feed.json: {f['meta']['rows']} rows, {len(f['meta']['states'])} states, "
          f"{len(f['meta']['skipped_mixed_party_multi_winner'])} mixed multi-winner rows skipped")
