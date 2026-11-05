#!/usr/bin/env python3
"""Write utah/results.js (the Utah legislature map's data) from results_all.js.

results_all.js "leg_ut" holds every Utah House and Senate race with the state's latest
vote counts (tools/update_site.py) and MultiState's calls. This turns it into the map's
window.RES format, keeping each seat's previous party and the Senate seats not on the
ballot from the existing file. The file is rewritten only when something changed.
"""
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'utah' / 'results.js'
MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.']


def load_js(p):
    t = p.read_text(encoding='utf-8')
    return json.loads(t[t.index('{'):t.rindex('}') + 1])


def mt(iso):
    m = re.match(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)', str(iso or ''))
    if not m:
        return ''
    d = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    d = d.astimezone(ZoneInfo('America/Denver'))
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'a.m.' if d.hour < 12 else 'p.m.'} MT, {MONTHS[d.month - 1]} {d.day}, {d.year}"


def render(res):
    out = ['window.RES = {', f'"meta": {json.dumps(res["meta"], ensure_ascii=False)},']
    for ch in ('house', 'senate'):
        out.append(f'"{ch}": {{')
        keys = sorted(res[ch], key=int)
        for i, k in enumerate(keys):
            out.append(f'  "{k}": {json.dumps(res[ch][k], ensure_ascii=False)}' + (',' if i < len(keys) - 1 else ''))
        out.append('},')
    out.append(f'"senate_hold": {json.dumps(res["senate_hold"], ensure_ascii=False)}')
    out.append('};')
    return '\n'.join(out) + '\n'


def main():
    A = load_js(ROOT / 'results_all.js')
    L = load_js(ROOT / 'leg_all.js')
    old = load_js(OUT)
    m = A.get('meta', {})
    new = {'house': {}, 'senate': {}, 'senate_hold': old.get('senate_hold', {})}
    for r in A.get('leg_ut', []):
        ch = 'house' if r['office'] == 'State House' else 'senate'
        prev = old.get(ch, {}).get(str(r['d']), {})
        new[ch][str(r['d'])] = {'c': r['c'], 'prior': prev.get('prior', r.get('prior')),
                                'called': bool(r.get('called') or prev.get('called'))}
    if len(new['house']) != 75 or len(new['senate']) != len(old.get('senate', {})):
        raise SystemExit(f"unexpected race counts ({len(new['house'])} House, {len(new['senate'])} Senate); utah/results.js left alone")
    calls = (L.get('states', {}).get('UT') or {}).get('asof') or old['meta'].get('calls_checked', '')
    if m.get('ut_url'):
        meta = {'counts_asof': mt(m.get('ut_asof_utc')) or old['meta'].get('counts_asof', ''),
                'counts_source': "Utah Lieutenant Governor's Office results site", 'counts_url': m['ut_url'],
                'counts_note': 'Official canvassed results' if m.get('ut_official') else '',
                'official': bool(m.get('ut_official'))}
    else:
        meta = {k: old['meta'].get(k) for k in ('counts_asof', 'counts_source', 'counts_url', 'counts_note')}
    meta.update({'calls_checked': calls, 'calls_source': "MultiState Elections' Utah results page",
                 'calls_url': 'https://www.multistate.us/elections/results/utah-2026'})
    new['meta'] = meta
    same = {k: v for k, v in old['meta'].items() if k != 'updated_utc'} == meta and \
        all(new[k] == old.get(k) for k in ('house', 'senate', 'senate_hold'))
    if same:
        print('utah/results.js: no change')
        return
    meta['updated_utc'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    OUT.write_text(render(new), encoding='utf-8')
    print(f"utah/results.js: counts as of {meta['counts_asof']}; calls as of {calls}")


if __name__ == '__main__':
    main()
