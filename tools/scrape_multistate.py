#!/usr/bin/env python3
"""Read MultiState's 2026 results pages and write leg_live.json.

Runs on a schedule in GitHub Actions (.github/workflows/update-legislatures.yml).
The output has the same shape as window.LEG in leg_all.js, so
tools/build_atlas_feed.py can turn it into atlas-live.json for the atlas.

Safety rules:
  * A state whose page can't be read, or which suddenly parses to far fewer rows
    than before, keeps its previous entry (so a site change never wipes data).
  * A state's "asof" time only changes when its results change, so the files
    only change (and only get committed) when there is real news.
Only the Python standard library is used.
"""
from __future__ import annotations
import gzip, json, re, sys, time, zlib
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'leg_live.json'
BASE = 'https://www.multistate.us/elections/results/{}-2026.html'
STATES = {
    'AL': 'alabama', 'AK': 'alaska', 'AZ': 'arizona', 'AR': 'arkansas', 'CA': 'california', 'CO': 'colorado',
    'CT': 'connecticut', 'DE': 'delaware', 'FL': 'florida', 'GA': 'georgia', 'HI': 'hawaii', 'ID': 'idaho',
    'IL': 'illinois', 'IN': 'indiana', 'IA': 'iowa', 'KS': 'kansas', 'KY': 'kentucky', 'ME': 'maine',
    'MD': 'maryland', 'MA': 'massachusetts', 'MI': 'michigan', 'MN': 'minnesota', 'MO': 'missouri',
    'MT': 'montana', 'NE': 'nebraska', 'NV': 'nevada', 'NH': 'new-hampshire', 'NM': 'new-mexico',
    'NY': 'new-york', 'NC': 'north-carolina', 'ND': 'north-dakota', 'OH': 'ohio', 'OK': 'oklahoma',
    'OR': 'oregon', 'PA': 'pennsylvania', 'RI': 'rhode-island', 'SC': 'south-carolina', 'SD': 'south-dakota',
    'TN': 'tennessee', 'TX': 'texas', 'VT': 'vermont', 'WA': 'washington', 'WV': 'west-virginia',
    'WI': 'wisconsin', 'WY': 'wyoming'}
VOID = {'br', 'img', 'hr', 'meta', 'link', 'input', 'source', 'wbr', 'col', 'area', 'base', 'embed', 'param', 'track'}
PARTY_WORDS = {'democrat': 'D', 'democratic': 'D', 'republican': 'R', 'independent': 'I', 'unaffiliated': 'I',
               'nonpartisan': 'NP', 'non-partisan': 'NP', 'libertarian': 'L', 'green': 'G', 'forward': 'F',
               'constitution': 'C'}
DEBUG_LEFT = [2]
MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.']


class Node:
    __slots__ = ('tag', 'attrs', 'children', 'parent')

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs), [], parent

    def elements(self):
        return [c for c in self.children if isinstance(c, Node)]

    def text(self):
        out = []
        for c in self.children:
            out.append(c.text() if isinstance(c, Node) else c)
        return ''.join(out)


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root', [], None)
        self.cur = self.root
        self.links = []

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag == 'a' and 'district.html' in (n.attrs.get('href') or ''):
            self.links.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if data:
            self.cur.children.append(data)


def clean(s):
    return re.sub(r'\s+', ' ', (s or '').replace('\xa0', ' ')).strip()


def party_code(p):
    p = clean(p)
    if re.fullmatch(r'[A-Z]{1,3}', p):
        return p
    low = p.lower()
    for word, code in PARTY_WORDS.items():
        if word in low:
            return code
    return 'O'


def winners(cell):
    cell = clean(cell)
    if not cell or 'no winner' in cell.lower():
        return []
    out = []
    for m in re.finditer(r'\s*,?\s*([^()]+?)\s*\(([^()]+)\)', cell):
        name = clean(m.group(1)).lstrip(',').strip()
        if name:
            out.append((name, party_code(m.group(2))))
    return out


def chamber_and_district(race, st):
    race = clean(race)
    m = re.match(r'^(House of Delegates|General Assembly|Assembly|House|Senate|Legislature)\b\s*(.*)$', race, re.I)
    if not m:
        return None, None
    word, rest = m.group(1).lower(), m.group(2)
    name = {'senate': 'State Senate', 'assembly': 'Assembly', 'general assembly': 'Assembly',
            'house of delegates': 'House of Delegates', 'legislature': 'Legislature'}.get(word, 'State House')
    if st == 'NE':
        name = 'Legislature'
    d = re.sub(r'^(?:HD|SD|AD|LD|District|Dist\.?)\s*[-#:]?\s*', '', rest.strip(), flags=re.I).strip()
    return name, d


def row_cells(link):
    """Cells of the row holding this district link (works for <tr> and for div grids)."""
    node, child = link.parent, link
    while node is not None and node.tag != 'root':
        els = node.elements()
        if 3 <= len(els) <= 8 and els[0] is child:
            # the first cell must be just the race label, so summary lists and captions are ignored
            if clean(els[0].text()) != clean(link.text()):
                return None
            return [clean(e.text()) for e in els]
        child, node = node, node.parent
    return None


def parse(html, st):
    t = Tree()
    t.feed(html)
    chambers, seen = {}, set()
    for a in t.links:
        cells = row_cells(a)
        if not cells:
            continue
        name, d = chamber_and_district(cells[0], st)
        if not name or not d:
            continue
        w = winners(cells[1] if len(cells) > 1 else '')
        others = cells[2] if len(cells) > 2 else ''
        notes = cells[3] if len(cells) > 3 else ''
        key = (name, d, cells[1], others)
        if key in seen:
            continue
        seen.add(key)
        parties = {p for _, p in w}
        chambers.setdefault(name, []).append({
            'd': d, 'w': ', '.join(n for n, _ in w),
            'wp': (parties.pop() if len(parties) == 1 else 'mixed') if w else '',
            'others': others, 'notes': notes, 'called': bool(w)})
    return [{'name': n, 'races': r} for n, r in chambers.items()]


def fetch(url):
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; election-2026-results/1.0; +https://github.com/dwhitney2181/election-2026)',
                                'Accept': 'text/html', 'Accept-Encoding': 'gzip, deflate'})
    with urlopen(req, timeout=30) as r:
        raw = r.read(20_000_000)
        enc = (r.headers.get('Content-Encoding') or '').lower()
    if enc == 'gzip' or raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    elif enc == 'deflate':
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    elif enc == 'br':
        try:
            import brotli  # only if installed; otherwise treat the page as unreadable
            raw = brotli.decompress(raw)
        except ImportError:
            raise RuntimeError('page sent brotli-compressed and the brotli module is not installed')
    text = raw.decode('utf-8', 'replace')
    if '<' not in text[:2000]:
        raise RuntimeError(f'response is not HTML (Content-Encoding: {enc or "none"})')
    return text


def mt_now():
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo('America/Denver'))
        tz = 'MT'
    except Exception:
        now, tz = datetime.now(timezone(timedelta(hours=-7))), 'MT'
    h = now.hour % 12 or 12
    return f"{h}:{now.minute:02d} {'a.m.' if now.hour < 12 else 'p.m.'} {tz}, {MONTHS[now.month - 1]} {now.day}, {now.year}"


def load_baseline():
    for p in (OUT, ROOT / 'leg_all.js'):
        if p.exists():
            s = p.read_text(encoding='utf-8')
            try:
                return json.loads(s[s.index('{'):s.rindex('}') + 1])
            except ValueError:
                continue
    return {'states': {}}


def count(entry):
    return sum(len(c['races']) for c in (entry or {}).get('chambers', []))


def main():
    base = load_baseline()
    old = base.get('states', {})
    states, errors, changed = {}, {}, False
    asof = mt_now()
    only = set(sys.argv[1:])
    for st, slug in STATES.items():
        if only and st not in only:
            if st in old:
                states[st] = old[st]
            continue
        url = BASE.format(slug)
        try:
            html = fetch(url)
            chambers = parse(html, st)
        except Exception as e:
            errors[st] = f'fetch failed: {str(e)[:120]}'
            if st in old:
                states[st] = old[st]
            continue
        n, prev = sum(len(c['races']) for c in chambers), count(old.get(st))
        if n == 0 and DEBUG_LEFT[0] > 0:  # print a sample of the page so the parser can be fixed
            DEBUG_LEFT[0] -= 1
            i = html.find('district.html')
            print(f'--- {st} debug: {len(html)} bytes, district.html x{html.count("district.html")}, <table x{html.count("<table")}, <tr x{html.count("<tr")}')
            print(html[max(0, i - 1200):i + 1200] if i >= 0 else html[:2400])
            print(f'--- end {st} debug')
        if n == 0 or (prev > 10 and n < 0.6 * prev):
            errors[st] = f'parsed {n} rows (previously {prev}); kept previous data'
            if st in old:
                states[st] = old[st]
            continue
        if st in old and old[st].get('chambers') == chambers:
            states[st] = old[st]  # unchanged: keep its old time so the file doesn't churn
        else:
            states[st] = {'asof': asof, 'src': 'MultiState Elections', 'url': url, 'chambers': chambers}
            changed = True
        time.sleep(1)
    data = {'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds') if changed or not OUT.exists()
            else base.get('updated_utc'),
            'states': states}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    filled = sum(1 for s in states.values() for c in s['chambers'] for r in c['races'] if r['w'])
    print(f'{len(states)} states, {filled} races with winners, {len(errors)} problems, changed={changed}')
    for st, e in errors.items():
        print(f'  {st}: {e}')


if __name__ == '__main__':
    main()
