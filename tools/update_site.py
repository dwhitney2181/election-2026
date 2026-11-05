#!/usr/bin/env python3
"""Fold the latest automatic reads into the files the election-2026 page loads.

Reads   leg_live.json      (tools/scrape_multistate.py: every legislative race MultiState lists)
        federal_live.json  (tools/scrape_federal.py: NBC News results and calls, ABC News gain markers)
Updates leg_all.js, results_all.js and flips.js in place.

Whatever a source didn't return this time keeps its previous value, and rows the
automatic sources don't cover (territory governors, delegates, hand-written context)
are left alone. Standard library only.
"""
from __future__ import annotations
import copy, json, re, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_multistate import mt_now  # e.g. "7:23 a.m. MT, Nov. 5, 2026"

ROOT = Path(__file__).resolve().parent.parent
NBC_URL = 'https://www.nbcnews.com/politics/2026-elections/{}-results'
ABC_HOUSE = 'https://abcnews.com/Elections/2026-us-house-election-results-live-map/'
MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.']
PNAME = {'D': 'Democrats', 'R': 'Republicans', 'I': 'independents'}
SUFFIX = re.compile(r',\s+(?=(?:Sr|Jr|II|III|IV|V)\b\.?)')


def load_js(p):
    t = p.read_text(encoding='utf-8')
    return json.loads(t[t.index('{'):t.rindex('}') + 1])


def write_js(p, var, obj, indent=None, seps=None):
    body = json.dumps(obj, ensure_ascii=False, indent=indent, separators=seps)
    new = f'window.{var} = {body};\n'
    if p.read_text(encoding='utf-8') != new:
        p.write_text(new, encoding='utf-8')
        return True
    return False


def num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r'\d+(?:\.\d+)?', str(v))
    return float(m.group()) if m else None


def r1(v):
    v = num(v)
    if v is None:
        return None
    v = round(v, 1)
    return int(v) if v == int(v) else v


def clock(dt, tz='America/New_York', abbr='ET'):
    d = dt.astimezone(ZoneInfo(tz))
    h = d.hour % 12 or 12
    return f"{h}:{d.minute:02d} {'a.m.' if d.hour < 12 else 'p.m.'} {abbr}, {MONTHS[d.month - 1]} {d.day}"


def parse_time(v):
    if v in (None, ''):
        return None
    m = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*([AP])\.?M\.?\s*E[SD]?T\s*', str(v), re.I)
    if m:                                              # "9:34 AM ET": today's date, Eastern time
        et = datetime.now(ZoneInfo('America/New_York'))
        h = int(m.group(1)) % 12 + (12 if m.group(3).upper() == 'P' else 0)
        t = et.replace(hour=h, minute=int(m.group(2)), second=0, microsecond=0)
        return t if t <= et else t.replace(day=t.day - 1) if t.day > 1 else t
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except ValueError:
        return None


def ordered(race, minor=False):
    """Candidates, winner first, then by vote share. Write-ins and candidates under 0.5% are left out
    (unless nobody has votes yet) so they don't show up as 'the other candidate'."""
    cs = [dict(c, name=' '.join(str(c['name']).split()), pct=num(c.get('pct')))
          for c in race.get('cands') or [] if str(c.get('name') or '').strip()]
    cs = sorted(cs, key=lambda c: (not c.get('win'), -(c['pct'] or -1), -(num(c.get('votes')) or 0)))
    if minor:
        return cs
    counted = any((c['pct'] or 0) > 0 for c in cs)
    keep = [c for c in cs if c.get('win') or (counted and (c['pct'] or 0) >= 0.5 and 'write-in' not in c['name'].lower())
            or (not counted and 'write-in' not in c['name'].lower())]
    return keep or cs


def top(cs, p):
    return next((c for c in cs if c['party'] == p), None)


def label(c):
    return f"{c['name']} ({'other' if c['party'] == 'O' else c['party']})" if c else ''


def lead_txt(w, cs):
    """'+4.6 pts, ' or, for a near tie, '+312 votes, '."""
    nx = cs[1] if len(cs) > 1 else None
    if not nx or w['pct'] is None or nx['pct'] is None:
        return ''
    m = r1(w['pct'] - nx['pct'])
    v1, v2 = num(w.get('votes')), num(nx.get('votes'))
    if m < 1 and v1 is not None and v2 is not None:
        return f"+{int(v1 - v2):,} votes, "
    return f"+{m} pts, "


def has_votes(race, cs):
    return bool(race.get('called') or any((c['pct'] or 0) > 0 for c in cs))


# ---------------------------------------------------------------- legislatures
def short_ch(name):
    return name.replace('State ', '')


def leg_flip_items(LEG, old_items):
    """Seats changing party, from MultiState's 'Flipped X to Y' notes, plus Utah election-night leads."""
    items, covered = [], set(LEG['states'])
    for st, S in sorted(LEG['states'].items()):
        for ch in S['chambers']:
            for r in ch['races']:
                notes = r.get('notes') or ''
                m = re.search(r'Flipped\s+(\w+)\s+to\s+(\w+)', notes)
                if not m or not (r.get('w') or '').strip():
                    continue
                fr, to = m.group(1), m.group(2)
                if fr == to:
                    continue
                multi = len(SUFFIX.sub(' ', r['w']).split(', ')) > 1
                items.append({'kind': 'leg', 'st': st, 'office': ch['name'], 'dist': str(r['d']), 'winner': r['w'],
                              'wp': r.get('wp') or to, 'loser': r.get('others') or '', 'fr': fr, 'to': to,
                              'status': 'called', 'src': 'MultiState Elections',
                              'url': S.get('url') or 'https://www.multistate.us/elections/general-2026',
                              'incdef': 'Incumbent defeated' in notes,
                              'note': 'Multi-member district' if multi else ''})
    have = {(i['st'], i['office'], i['dist']) for i in items}
    races = {(st, ch['name'], str(r['d'])): r for st, S in LEG['states'].items() for ch in S['chambers'] for r in ch['races']}
    kept = 0
    for i in old_items:
        if i['kind'] != 'leg':
            continue
        key = (i['st'], i['office'], str(i['dist']))
        if i['st'] not in covered:                       # state not read at all: keep what we had
            items.append(i); kept += 1
        elif i['status'] == 'leading' and key not in have:
            r = races.get(key)
            if r is None or not (r.get('w') or '').strip():  # still no winner recorded: keep the lead
                items.append(i); kept += 1
    return items, kept


def uncalled(LEG, old):
    out = dict(old)
    for st, S in LEG['states'].items():
        rows = []
        for ch in S['chambers']:
            n = sum(1 for r in ch['races'] if not (r.get('called') and (r.get('w') or '').strip())
                    and not re.match(r'\s*Unopposed', r.get('others') or ''))
            rows.append([short_ch(ch['name']), str(n)])
        out[st] = rows
    return out


def update_leg_ut(A, LEG):
    S = LEG['states'].get('UT')
    if not S:
        return 0
    races = {(ch['name'], str(r['d'])): r for ch in S['chambers'] for r in ch['races']}
    n = 0
    for row in A.get('leg_ut', []):
        r = races.get((row['office'], str(row['d'])))
        if r and r.get('called') and (r.get('w') or '').strip() and not row.get('called'):
            row['called'] = True
            n += 1
            lead = (row.get('c') or [{}])[0].get('name', '')
            if lead and lead.split()[-1].lower() not in r['w'].lower():
                print(f"  note: UT {row['office']} {row['d']}: MultiState winner {r['w']!r}, election-night leader {lead!r}")
    return n


SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv'}


def last_name(n):
    toks = [x for x in re.split(r'[\s,]+', n.lower()) if x and x not in SUFFIXES]
    return re.sub(r'[^a-z]', '', toks[-1]) if toks else ''


def nice_name(o, old):
    """The state lists names in capitals; reuse the name already on file for the same candidate."""
    same = [c['name'] for c in old if c.get('party') == o['party'] and last_name(c['name']) == last_name(o['name'])]
    if len(same) == 1:
        return same[0]
    if o['party'] == 'W' and re.fullmatch(r'write[- ]?ins?', o['name'].strip(), re.I):
        return 'Write-In'
    fix = lambda w: w.upper() if w.lower() in ('ii', 'iii', 'iv') else re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), w)
    return ' '.join(fix(w) for w in o['name'].split())


def update_utah(A, UT):
    """Utah legislative vote counts from the state's own results feed, race by race.
    A race keeps its old counts if the feed's total is lower (counts only go up)."""
    races, n = UT.get('races', {}), 0
    for row in A.get('leg_ut', []):
        r = races.get(f"{row['office']}|{row['d']}")
        if not r:
            continue
        opts = [o for o in r['c'] if o['votes'] > 0 or not o['write_in']]
        total = sum(o['votes'] for o in opts)
        if not total or total < sum(c.get('votes') or 0 for c in row['c']):
            continue
        cs = [{'name': nice_name(o, row['c']), 'party': o['party'] or 'O', 'votes': o['votes'],
               'pct': round(100 * o['votes'] / total, 2)} for o in sorted(opts, key=lambda o: -o['votes'])]
        if UT.get('official') and not row.get('called'):
            row['called'] = True
        if cs != row['c']:
            row['c'] = cs
            n += 1
    return n


def utah_leading(A, leg, url):
    """Utah seats where the leader's party differs from the seat's previous party and no call is recorded yet."""
    have = {(i['st'], i['office'], str(i['dist'])) for i in leg}
    out = []
    for row in A.get('leg_ut', []):
        c = row.get('c') or []
        if row.get('called') or len(c) < 2 or ('UT', row['office'], str(row['d'])) in have:
            continue
        lead = c[0]
        if lead['party'] in ('W', row.get('prior')):
            continue
        out.append({'kind': 'leg', 'st': 'UT', 'office': row['office'], 'dist': str(row['d']), 'winner': lead['name'],
                    'wp': lead['party'], 'loser': ', '.join(f"{x['name']} ({x['party']})" for x in c[1:] if x['party'] != 'W'),
                    'fr': row.get('prior'), 'to': lead['party'], 'status': 'leading',
                    'margin': round(lead['pct'] - c[1]['pct'], 1),
                    'src': "Utah's official results site (unofficial count)", 'url': url, 'incdef': False, 'note': ''})
    return out


# ---------------------------------------------------------------- federal
def update_house(A, races, abc):
    n = 0
    for h in A['house']:
        rid = f"{h['st']}-{h['d']}"
        r = races.get(rid)
        if r:
            cs = ordered(r)
            if cs:
                d, rp = top(cs, 'D'), top(cs, 'R')
                rest = sum(c['pct'] or 0 for c in ordered(r, minor=True)) - (d['pct'] or 0 if d else 0) - (rp['pct'] or 0 if rp else 0)
                h['inn'] = r1(r.get('inn'))
                h['dem'] = r1(d['pct']) if d else None
                h['rep'] = r1(rp['pct']) if rp else None
                h['oth'] = r1(rest) if rest > 0 else None
                h['c'] = [[c['name'], c['party'], r1(c['pct']), bool(c.get('inc'))] for c in cs[:4]]
                h['called'] = bool(r.get('called'))
                h['win'] = cs[0]['party'] if h['called'] else None
                h.pop('fox', None)
                h.pop('who', None)
                n += 1
        a = abc.get(rid) or (abc.get(f"{h['st']}-1") if h['d'] in (0, 1) else None)
        if a and a.get('note'):
            h['note'] = a['note']
    return n


def update_statewide(rows, races, office, url):
    n = 0
    for row in rows:
        st = row['st']
        r = races.get(st) or next((v for k, v in races.items() if k.startswith(st)), None)
        if not r:
            continue
        cs = ordered(r)
        if not cs:
            continue
        d, rp = top(cs, 'D'), top(cs, 'R')
        others = [c for c in cs if c['party'] not in ('D', 'R')]
        o = others[0] if others else None
        row['dn'] = d['name'] if d else ''
        row['rn'] = rp['name'] if rp else ''
        row['other'] = label(o) if o else ''
        row['dp'] = r1(d['pct']) if d else None
        row['rp'] = r1(rp['pct']) if rp else None
        row['op'] = r1(o['pct']) if o else None
        row['inn'] = r1(r.get('inn'))
        if r.get('called'):
            row['status'], row['win'] = 'called', cs[0]['party']
            auto = 'Called by NBC News'
        elif has_votes(r, cs):
            row['status'], row['win'] = 'leading', cs[0]['party']
            auto = 'Not called yet (NBC News count)'
        else:
            row['status'], row['win'] = 'uncalled', None
            auto = 'No votes reported yet (NBC News)'
        # keep hand-written context ("Open seat", "Special election"); drop old counts, calls and our own notes
        auto_notes = ('Called by NBC News', 'Not called yet (NBC News count)', 'No votes reported yet (NBC News)')
        keep = [x for x in (row.get('note') or '').split('; ') if x and x not in auto_notes
                and not re.search(r'%|\bled\b|\blead|counted|[Cc]all|count', x)]
        row['note'] = '; '.join(keep + [auto])
        row['src'], row['url'] = 'NBC News', url
        n += 1
    return n


def house_items(A, races, abc, old_items, url):
    old = {(i['st'], str(i['dist'])): i for i in old_items if i['kind'] == 'house'}
    nbc_marks = any(r.get('flip') and r.get('called') for r in races.values())
    out, dropped = [], []
    seen = set()
    for h in A['house']:
        key = (h['st'], str(h['d']))
        r = races.get(f"{h['st']}-{h['d']}")
        prev = old.get(key)
        if not r:
            if prev:
                out.append(prev); seen.add(key)
            continue
        cs = ordered(r)
        if not cs or not has_votes(r, cs):
            if prev:
                out.append(prev); seen.add(key)
            continue
        w = cs[0]
        loser = next((c for c in cs[1:] if c['party'] != w['party']), None)
        incs = [c for c in cs if c.get('inc')]
        # only a major-party incumbent losing to the other major party counts as a seat changing hands
        lost_inc = [c for c in incs if c['party'] in ('D', 'R') and w['party'] in ('D', 'R') and c['party'] != w['party']]
        same_inc = any(c['party'] == w['party'] for c in incs)
        abc_note = (abc.get(f"{h['st']}-{h['d']}") or {}).get('note', '')
        abc_gain = abc_note == {'D': 'dem gain', 'R': 'rep gain', 'I': 'ind gain'}.get(w['party'])
        margin = r1((w['pct'] or 0) - (cs[1]['pct'] or 0)) if len(cs) > 1 and w['pct'] is not None else None
        if r.get('called'):
            if nbc_marks:      # NBC marks changed seats itself (it accounts for redrawn districts); ABC as a second opinion
                flip = bool(r.get('flip') == w['party'] or abc_gain)
            else:
                flip = bool(r.get('flip') == w['party'] or abc_gain or (lost_inc and not same_inc)
                            or (prev and prev['to'] == w['party']))
            if not flip:
                if prev:
                    dropped.append(f"{key[0]}-{key[1]} ({prev['to']} called for {w['party']} instead)")
                continue
            fr = (lost_inc[0]['party'] if lost_inc and not same_inc else prev['fr'] if prev
                  else ('R' if w['party'] == 'D' else 'D'))
            src = ('NBC News call' + ('; NBC and ABC mark it as a party gain' if r.get('flip') == w['party'] and abc_gain
                                     else '; NBC marks it as a party gain' if r.get('flip') == w['party']
                                     else '; ABC News marks it as a party gain' if abc_gain else ''))
            note = (prev or {}).get('note') or ('Incumbent defeated' if lost_inc and not same_inc else '')
            if prev and prev.get('status') == 'leading' and 'trailing' in note.lower():
                note = 'Incumbent defeated' if lost_inc else ''
            out.append({'kind': 'house', 'st': h['st'], 'office': 'U.S. House', 'dist': str(h['d']),
                        'winner': w['name'], 'wp': w['party'], 'loser': label(loser), 'fr': fr, 'to': w['party'],
                        'status': 'called', 'src': src, 'url': url, 'incdef': bool(lost_inc and not same_inc),
                        'note': note})
        else:
            trailing_inc = lost_inc and not same_inc
            if prev and prev.get('status') == 'called':
                out.append(prev)                      # another network already called it; keep their call
            elif (prev and prev['to'] == w['party']) or trailing_inc or r.get('flip') == w['party']:
                fr = lost_inc[0]['party'] if trailing_inc else prev['fr'] if prev else ('R' if w['party'] == 'D' else 'D')
                note = 'Incumbent trailing' if trailing_inc else ((prev or {}).get('note') or '')
                out.append({'kind': 'house', 'st': h['st'], 'office': 'U.S. House', 'dist': str(h['d']),
                            'winner': w['name'], 'wp': w['party'], 'loser': label(loser), 'fr': fr, 'to': w['party'],
                            'status': 'leading',
                            'src': f"NBC News count ({lead_txt(w, cs)}{r1(r.get('inn')) or 0}% in)",
                            'url': url, 'incdef': False, 'note': note})
            elif prev:
                dropped.append(f"{key[0]}-{key[1]} ({prev['to']} no longer leads)")
                continue
            else:
                continue
        seen.add(key)
    for k, i in old.items():                          # delegates and anything outside the 435
        if k not in seen and not any((h['st'], str(h['d'])) == k for h in A['house']):
            out.append(i)
    return out, dropped


def gov_items(A, races, old_items, url):
    old = {i['st']: i for i in old_items if i['kind'] == 'gov'}
    out = []
    for row in A['gov']:
        prev = old.get(row['st'])
        r = races.get(row['st'])
        if not r:
            if prev:
                out.append(prev)
            continue
        if not row.get('win') or row['win'] == row.get('prior') or row['status'] not in ('called', 'leading'):
            continue
        cs = ordered(r)
        w = cs[0]
        loser = next((c for c in cs[1:] if c['party'] != w['party']), None)
        lost_inc = any(c.get('inc') and c['party'] != w['party'] for c in cs)
        same = prev and prev['to'] == row['win'] and prev['status'] == row['status']
        out.append({'kind': 'gov', 'st': row['st'], 'office': 'Governor', 'dist': '', 'winner': w['name'],
                    'wp': w['party'], 'loser': label(loser), 'fr': row.get('prior'), 'to': row['win'],
                    'status': row['status'],
                    'src': prev['src'] if same and row['status'] == 'called' else
                    ('NBC News call' if row['status'] == 'called' else
                     f"NBC News count ({row.get('dp')}% to {row.get('rp')}%, {row.get('inn') or 0}% counted)"
                     if row.get('dp') is not None and row.get('rp') is not None else 'NBC News count'),
                    'url': prev['url'] if same and row['status'] == 'called' else url,
                    'incdef': lost_inc, 'note': (prev or {}).get('note', '') if same else ''})
    return out


def pending_gov(A, races, old):
    out = [p for p in old if p[0] not in races]
    for row in A['gov']:
        r = races.get(row['st'])
        if not r or row['status'] == 'called':
            continue
        cs = ordered(r)
        if row['status'] == 'leading' and len(cs) > 1:
            out.append([row['st'], f"{label(cs[0])} led {label(cs[1])} {r1(cs[0]['pct'])}% to {r1(cs[1]['pct'])}% "
                                   f"with {row.get('inn') or 0}% counted (NBC News); not called"])
        else:
            out.append([row['st'], 'No votes reported yet (NBC News)'])
    return sorted(out)


def house_context(A, races, abc, items, asof):
    called = sum(1 for r in races.values() if r.get('called'))
    fl = [i for i in items if i['kind'] == 'house' and i['status'] == 'called' and i['dist'] != 'Delegate']
    by = {p: sum(1 for i in fl if i['to'] == p) for p in ('D', 'R', 'I')}
    parts = ', '.join(f"{n} to {PNAME[p]}" for p, n in by.items() if n)
    gains = sum(1 for a in abc.values() if 'gain' in (a.get('note') or ''))
    marks = any(r.get('flip') and r.get('called') for r in races.values())
    how = ('as marked by NBC News or ABC News' if marks else
           'counting ABC flip markers and incumbents who lost to the other party')
    t = (f"NBC News had called {called} of 435 House races as of {asof}. Among called races, {len(fl)} seats "
         f"changed party{f' ({parts})' if parts else ''}, {how}.")
    if gains:
        t += f" ABC News marked {gains} seats as party gains."
    return t


# ---------------------------------------------------------------- main
def main():
    now = datetime.now(timezone.utc)
    A = load_js(ROOT / 'results_all.js')
    F = load_js(ROOT / 'flips.js')
    A0, F0 = copy.deepcopy(A), copy.deepcopy(F)
    changed = []

    LEG = None
    lp = ROOT / 'leg_live.json'
    if lp.exists():
        LEG = json.loads(lp.read_text(encoding='utf-8'))
        if len(LEG.get('states', {})) >= 30:
            if write_js(ROOT / 'leg_all.js', 'LEG', LEG):
                changed.append('leg_all.js')
        else:
            print('leg_live.json has too few states; legislative files left alone')
            LEG = None

    fed = {}
    fp = ROOT / 'federal_live.json'
    if fp.exists():
        fed = json.loads(fp.read_text(encoding='utf-8'))
    nbc, abc = fed.get('nbc', {}), fed.get('abc', {})
    fmeta = fed.get('meta', {})

    items = F['items']
    if LEG:
        leg, kept = leg_flip_items(LEG, items)
        F['uncalled'] = uncalled(LEG, F.get('uncalled', {}))
        n_ut = update_leg_ut(A, LEG)
        print(f"legislatures: {len(leg)} seats changing party ({kept} kept from before); Utah calls added: {n_ut}")
    else:
        leg = [i for i in items if i['kind'] == 'leg']

    up = ROOT / 'utah_live.json'
    UT = json.loads(up.read_text(encoding='utf-8')) if up.exists() else {}
    if UT.get('races'):
        nu = update_utah(A, UT)
        t_ut = parse_time(UT.get('asof_utc'))
        A['meta'].update({'ut_src': "Utah Lieutenant Governor's Office results site", 'ut_url': UT.get('url'),
                          'ut_asof': clock(t_ut, 'America/Denver', 'MT') if t_ut else '', 'ut_asof_utc': UT.get('asof_utc'),
                          'ut_official': bool(UT.get('official'))})
        leg = [i for i in leg if not (i['st'] == 'UT' and i['status'] == 'leading')]
        leg += utah_leading(A, leg, UT.get('url'))
        print(f"Utah: {nu} legislative races got newer counts from the state; "
              f"{sum(1 for i in leg if i['st'] == 'UT' and i['status'] == 'leading')} seats show the challenging party ahead")

    house_races, sen_races, gov_races = nbc.get('house', {}), nbc.get('senate', {}), nbc.get('governor', {})
    abc_house = abc.get('house', {})
    house_asof = None
    if house_races:
        t = parse_time(fmeta.get('house_asof'))
        house_asof = clock(t) if t else clock(now)
        nh = update_house(A, house_races, abc_house)
        A['meta'].update({'house_src': 'NBC News House results', 'house_url': NBC_URL.format('house'),
                          'house_short': 'NBC', 'house_asof': house_asof, 'abc_url': ABC_HOUSE})
        print(f"House: {nh} of {len(A['house'])} districts updated from NBC")
    if sen_races:
        ns = update_statewide(A['sen'], sen_races, 'senate', NBC_URL.format('senate'))
        A['meta'].update({'sen_src': 'NBC News Senate results and calls', 'sen_url': NBC_URL.format('senate')})
        print(f"Senate: {ns} races updated")
    if gov_races:
        ng = update_statewide(A['gov'], gov_races, 'governor', NBC_URL.format('governor'))
        A['meta'].update({'gov_src': 'NBC News governor results and calls', 'gov_url': NBC_URL.format('governor')})
        print(f"Governors: {ng} races updated")
    if house_races or sen_races or gov_races:
        A['meta']['auto'] = True
        A['meta']['updated'] = mt_now()

    if house_races:
        house, dropped = house_items(A, house_races, abc_house, items, NBC_URL.format('house'))
        if dropped:
            print('  House items dropped: ' + '; '.join(dropped))
        F['meta']['house_context'] = house_context(A, house_races, abc_house, house, house_asof)
        F['meta']['house_context_urls'] = [['NBC News', NBC_URL.format('house')], ['ABC News', ABC_HOUSE]]
    else:
        house = [i for i in items if i['kind'] == 'house']
    if gov_races:
        gov = gov_items(A, gov_races, items, NBC_URL.format('governor'))
        F['pending_gov'] = pending_gov(A, gov_races, F.get('pending_gov', []))
    else:
        gov = [i for i in items if i['kind'] == 'gov']
    other = [i for i in items if i['kind'] not in ('leg', 'house', 'gov')]
    F['items'] = gov + house + leg + other
    c = Counter((i['kind'], i['status']) for i in F['items'])
    print('flip list: ' + ', '.join(f'{k} {s}: {n}' for (k, s), n in sorted(c.items())))

    # Stamp the time only when some result actually changed, so unchanged runs commit nothing.
    strip = lambda o, ks: {**o, 'meta': {m: v for m, v in o['meta'].items() if m not in ks}}
    a_keys, f_keys = ('updated', 'house_asof'), ('asof', 'house_context')
    ctx_same = re.sub(r' as of [^.]+\.', '.', F['meta'].get('house_context', '')) == \
        re.sub(r' as of [^.]+\.', '.', F0['meta'].get('house_context', ''))
    if strip(A, a_keys) != strip(A0, a_keys) or strip(F, f_keys) != strip(F0, f_keys) or not ctx_same or changed:
        d = datetime.now(ZoneInfo('America/Denver'))
        F['meta']['asof'] = (f"{MONTHS[d.month - 1]} {d.day}, {d.year}, {d.hour % 12 or 12}:{d.minute:02d} "
                             f"{'a.m.' if d.hour < 12 else 'p.m.'} MT")
    else:                                              # nothing new: keep the old timestamps too
        for k in a_keys:
            if k in A0['meta']:
                A['meta'][k] = A0['meta'][k]
            else:
                A['meta'].pop(k, None)
        F['meta']['house_context'] = F0['meta'].get('house_context', F['meta'].get('house_context'))
    if write_js(ROOT / 'results_all.js', 'ALL', A):
        changed.append('results_all.js')
    if write_js(ROOT / 'flips.js', 'FLIPS', F, indent=0):
        changed.append('flips.js')
    print('changed: ' + (', '.join(changed) if changed else 'nothing'))

if __name__ == '__main__':
    main()
