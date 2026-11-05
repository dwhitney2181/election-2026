#!/usr/bin/env python3
"""Read U.S. House, Senate and governor results and write federal_live.json.

Sources (both allow automated reading of these pages in robots.txt):
  * NBC News results pages: every race's candidates, votes, vote shares, share of the
    vote counted, and NBC's calls (the data embedded in each page as __NEXT_DATA__).
  * ABC News results tables: which House/Senate/governor seats ABC marks as a party
    "gain" (a called seat changing party), used to cross-check flips.
A source that can't be read leaves its section out; update_site.py then keeps the
previous numbers for it. Standard library only (plus brotli via scrape_multistate.fetch).
"""
from __future__ import annotations
import json, re, sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_multistate import fetch  # handles gzip/brotli

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'federal_live.json'
NBC = 'https://www.nbcnews.com/politics/2026-elections/{}-results'
ABC = 'https://abcnews.com/Elections/2026-us-{}-election-results-live-map/'
FIPS = {'01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA', '08': 'CO', '09': 'CT', '10': 'DE', '11': 'DC', '12': 'FL',
        '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN', '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
        '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS', '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
        '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND', '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI',
        '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT', '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
        '56': 'WY', '60': 'AS', '66': 'GU', '69': 'MP', '72': 'PR', '78': 'VI'}
STATE_NAMES = {'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA', 'Colorado': 'CO',
               'Connecticut': 'CT', 'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID',
               'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA',
               'Maine': 'ME', 'Maryland': 'MD', 'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN',
               'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV',
               'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC',
               'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA',
               'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX',
               'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV',
               'Wisconsin': 'WI', 'Wyoming': 'WY'}
# AP-style abbreviations used in ABC's tables
AP = {'Ala.': 'AL', 'Alaska': 'AK', 'Ariz.': 'AZ', 'Ark.': 'AR', 'Calif.': 'CA', 'Colo.': 'CO', 'Conn.': 'CT', 'Del.': 'DE',
      'Fla.': 'FL', 'Ga.': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID', 'Ill.': 'IL', 'Ind.': 'IN', 'Iowa': 'IA', 'Kan.': 'KS',
      'Ky.': 'KY', 'La.': 'LA', 'Maine': 'ME', 'Md.': 'MD', 'Mass.': 'MA', 'Mich.': 'MI', 'Minn.': 'MN', 'Miss.': 'MS',
      'Mo.': 'MO', 'Mont.': 'MT', 'Neb.': 'NE', 'Nev.': 'NV', 'N.H.': 'NH', 'N.J.': 'NJ', 'N.M.': 'NM', 'N.Y.': 'NY',
      'N.C.': 'NC', 'N.D.': 'ND', 'Ohio': 'OH', 'Okla.': 'OK', 'Ore.': 'OR', 'Pa.': 'PA', 'R.I.': 'RI', 'S.C.': 'SC',
      'S.D.': 'SD', 'Tenn.': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vt.': 'VT', 'Va.': 'VA', 'Wash.': 'WA', 'W.Va.': 'WV',
      'W. Va.': 'WV', 'Wis.': 'WI', 'Wyo.': 'WY'}
PARTY = {'dem': 'D', 'democrat': 'D', 'democratic': 'D', 'rep': 'R', 'gop': 'R', 'republican': 'R', 'ind': 'I',
         'independent': 'I', 'lib': 'L', 'libertarian': 'L', 'grn': 'G', 'green': 'G'}


def party(p):
    p = (p or '').strip().lower()
    return PARTY.get(p, PARTY.get(p[:3], 'O') if p else 'O')


def nbc_page(office):
    t = fetch(NBC.format(office))
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    if not m:
        raise RuntimeError('no __NEXT_DATA__ on NBC page')
    return json.loads(m.group(1))['props']['pageProps']


def race_from(entry, flips):
    tip = entry.get('tooltip') or {}
    cands = []
    for c in tip.get('candidates') or []:
        cands.append({'name': c.get('name') or ' '.join(x for x in (c.get('firstName'), c.get('lastName')) if x),
                      'party': party(c.get('party')), 'pct': c.get('percentVote'), 'votes': c.get('votes', c.get('vote')),
                      'win': bool(c.get('isWinner')), 'inc': bool(c.get('isIncumbent'))})
    called = any(c['win'] for c in cands)
    return {'inn': tip.get('percentIn'), 'called': called, 'call_code': tip.get('callStatusCode'),
            'race': tip.get('raceName'), 'cands': cands, 'flip': flips}


def style_flip(entry):
    """NBC colors a seat that changed party with a 'flipToBlue' / 'flipToRed' fill."""
    m = re.search(r'flipTo(\w+)', str((entry.get('style') or {}).get('fill') or ''))
    return {'blue': 'D', 'red': 'R'}.get(m.group(1).lower(), 'I') if m else None


def table_flips(pp):
    """{stateAbbr or district key: party that flipped the seat} from NBC's table, when it marks flips."""
    out = {}
    for row in ((pp.get('tableData') or {}).get('states') or []):
        key = row.get('stateAbbr') or row.get('key') or ''
        if row.get('houseNumber') or row.get('district'):
            key = f"{key}-{int(str(row.get('houseNumber') or row.get('district')).lstrip('0') or 1)}"
        for side, p in (('dem', 'D'), ('rep', 'R'), ('ind', 'I')):
            v = row.get(side) or {}
            if v.get('isFlip') and v.get('isWinner'):
                out[key] = p
    return out


def nbc():
    res, meta = {}, {}
    for office, key in (('house', 'house'), ('senate', 'senate'), ('governor', 'governor')):
        try:
            pp = nbc_page(office)
        except Exception as e:
            print(f'NBC {office}: FAILED {str(e)[:150]}')
            continue
        flips = table_flips(pp)
        races = {}
        for k, entry in (pp.get('mapData') or {}).items():
            if not isinstance(entry, dict) or not entry.get('tooltip'):
                continue
            if office == 'house':
                if not re.fullmatch(r'\d{4}', str(k)):
                    continue
                st = FIPS.get(k[:2])
                if not st:
                    continue
                d = int(k[2:]) or 1
                rid = f'{st}-{d}'
            else:
                st = str(entry.get('stateCode') or k)[:2].upper()
                if not re.fullmatch(r'[A-Z]{2}', st):
                    continue
                rid = st if str(k).upper() == st else str(k).upper()
            r = race_from(entry, style_flip(entry) or flips.get(rid) or flips.get(st))
            if r['cands']:
                races[rid] = r
        res[key] = races
        meta[f'{key}_asof'] = pp.get('lastModifiedFormatted') or pp.get('lastModified') or pp.get('currentTime')
        meta[f'{key}_url'] = NBC.format(office)
        print(f'NBC {office}: {len(races)} races, {sum(r["called"] for r in races.values())} called, '
              f'{sum(1 for r in races.values() if r["flip"] and r["called"])} called seats marked as changing party')
    return res, meta


class Cells(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, a):
        if tag == 'table':
            self.tables.append([])
        elif tag == 'tr' and self.tables:
            self.row = []
            self.tables[-1].append(self.row)
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []
        elif self.cell is not None:
            self.cell.append(' ')

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif self.cell is not None:
            self.cell.append(' ')

    def handle_data(self, d):
        if self.cell is not None:
            self.cell.append(d)


MISSED = []


def num(s):
    m = re.match(r'\s*(\d+(?:\.\d+)?)%', s or '')
    return float(m.group(1)) if m else None


def abc(office):
    t = fetch(ABC.format(office))
    p = Cells()
    p.feed(t)
    out = {}
    for tb in p.tables:
        for row in tb[1:]:
            if len(row) < 3:
                continue
            m = re.match(r'^(.*?)(?:\s+(\d+))?\s+(\d+(?:\.\d+)?)% in$', row[0].strip())
            if not m:
                if office == 'house' and len(MISSED) < 12 and '% in' in ' '.join(row):
                    MISSED.append(row[:2])
                continue
            name = m.group(1).strip()
            bare = name.rstrip('.')
            st = AP.get(name) or AP.get(bare) or AP.get(bare + '.') or STATE_NAMES.get(name) or STATE_NAMES.get(bare)
            if not st:
                if office == 'house' and len(MISSED) < 12:
                    MISSED.append(row[:2])
                continue
            rid = f'{st}-{int(m.group(2))}' if (office == 'house' and m.group(2)) else (f'{st}-1' if office == 'house' else st)
            text = ' '.join(row[1:]).lower()
            note = ''
            for who, p_ in (('democrats', 'dem'), ('republicans', 'rep'), ('independents', 'ind')):
                for verb in ('gain', 'lead', 'win', 'hold'):
                    if f'{who} {verb}' in text:
                        note = f'{p_} {verb}'
            out[rid] = {'inn': float(m.group(3)), 'dem': num(row[1]), 'rep': num(row[2]),
                        'oth': num(row[3]) if len(row) > 3 else None, 'note': note}
    if len(out) < (300 if office == 'house' else 20):
        raise RuntimeError(f'only {len(out)} rows parsed')
    return out


def main():
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    races, meta = nbc()
    abcd = {}
    for office in ('house', 'senate', 'governor'):
        try:
            abcd[office] = abc(office)
            if MISSED and office == 'house':
                print('  ABC rows not parsed (sample):', MISSED[:4])
            print(f'ABC {office}: {len(abcd[office])} rows, {sum("gain" in r["note"] for r in abcd[office].values())} gains')
        except Exception as e:
            print(f'ABC {office}: FAILED {str(e)[:150]}')
    data = {'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'meta': meta,
            'nbc': races, 'abc': abcd, 'abc_url': ABC.format('{office}')}
    # keep the previous section for any source that failed this time
    for sec in ('house', 'senate', 'governor'):
        if sec not in data['nbc'] and sec in prev.get('nbc', {}):
            data['nbc'][sec] = prev['nbc'][sec]
            print(f'  kept previous NBC {sec}')
        if sec not in data['abc'] and sec in prev.get('abc', {}):
            data['abc'][sec] = prev['abc'][sec]
            print(f'  kept previous ABC {sec}')
    if not data['nbc'] and not data['abc']:
        sys.exit('no federal source could be read; leaving federal_live.json unchanged')
    same = lambda a, b: all(a.get(k) == b.get(k) for k in ('nbc', 'abc'))
    if prev and same(data, prev):
        print('no new federal numbers since the last read')
        return
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    main()
