#!/usr/bin/env python3
"""Read an eSeries Data Dictionary export (.xlsx) with the standard library only.

No openpyxl required. Usage:

  dd.py summary  FILE
  dd.py entity   FILE Entity [--all]        # fields; --all includes widgets/transients
  dd.py find     FILE pattern               # search field/entity names (regex, case-insensitive)
  dd.py type     FILE Entity.field          # exact type of one field
  dd.py rels     FILE Entity                # relations only (many-to-one + collections)
  dd.py widgets  FILE Entity                # widgets valid at that entity
  dd.py lookups  FILE [pattern]             # lookup-list fields and their codes
  dd.py diff     FILE_A FILE_B [Entity]     # entity-level diff, or field-level for one entity
"""
import sys, re, html, zipfile

def load(path):
    z = zipfile.ZipFile(path)
    ss = z.read('xl/sharedStrings.xml').decode('utf8', 'replace')
    strings = [html.unescape(re.sub(r'<[^>]+>', '', m))
               for m in re.findall(r'<si>(.*?)</si>', ss, re.S)]
    sheet = [n for n in z.namelist() if re.match(r'xl/worksheets/sheet1\.xml$', n)][0]
    sh = z.read(sheet).decode('utf8', 'replace')
    out = []
    for rm in re.finditer(r'<row[^>]*>(.*?)</row>', sh, re.S):
        d = {}
        for cm in re.finditer(r'<c r="([A-Z]+)\d+"([^>]*)>(?:<v>(.*?)</v>)?', rm.group(1), re.S):
            col, attrs, v = cm.group(1), cm.group(2), cm.group(3)
            d[col] = '' if v is None else (strings[int(v)] if 't="s"' in attrs else v)
        out.append(d)
    return out

def parse(path):
    """-> {Entity: {'table':..., 'fields':[{name,type,desc,notnull,unique,indexed,examples}]}}"""
    ents, cur = {}, None
    for r in load(path):
        a = r.get('A', '').strip()
        if a:
            cur = a
            ents[cur] = {'table': r.get('B', '').strip(), 'fields': []}
        elif cur and r.get('B', '').strip():
            ents[cur]['fields'].append({
                'name': r['B'].strip(), 'type': r.get('C', '').strip(),
                'desc': r.get('D', '').strip(), 'notnull': r.get('E', '').strip(),
                'unique': r.get('F', '').strip(), 'indexed': r.get('G', '').strip(),
                'examples': r.get('H', '').strip(),
            })
    return ents

IS_WIDGET = lambda f: f['type'] == 'Widget'
IS_COLL   = lambda f: f['type'].startswith('Collection (')
SCALARS   = ('String', 'Lookup List', 'Date', 'Double', 'double', 'Long', 'long',
             'int', 'Integer', 'boolean', 'Boolean', 'Time', 'Blob', 'Clob')
IS_SCALAR = lambda f: any(f['type'].startswith(s) for s in SCALARS)
IS_REF    = lambda f: not IS_WIDGET(f) and not IS_COLL(f) and not IS_SCALAR(f) and f['type']

def flag(f):
    return ' '.join(x for x in (f['notnull'], f['unique'], f['indexed']) if x)

def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    cmd, path = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]

    if cmd == 'diff':
        A, B = parse(path), parse(rest[0])
        if len(rest) > 1:
            e = rest[1]
            fa = {f['name']: f['type'] for f in A.get(e, {}).get('fields', [])}
            fb = {f['name']: f['type'] for f in B.get(e, {}).get('fields', [])}
            print('%s: A=%d fields  B=%d fields' % (e, len(fa), len(fb)))
            for n in sorted(set(fa) - set(fb)): print('  only A: %-34s %s' % (n, fa[n]))
            for n in sorted(set(fb) - set(fa)): print('  only B: %-34s %s' % (n, fb[n]))
            for n in sorted(set(fa) & set(fb)):
                if fa[n] != fb[n]: print('  TYPE  : %-34s A=%s  B=%s' % (n, fa[n], fb[n]))
        else:
            print('A=%d entities  B=%d entities' % (len(A), len(B)))
            for n in sorted(set(A) - set(B)): print('  only A: ' + n)
            for n in sorted(set(B) - set(A)): print('  only B: ' + n)
        return 0

    ents = parse(path)

    if cmd == 'summary':
        tot = sum(len(v['fields']) for v in ents.values())
        kinds = {}
        for v in ents.values():
            for f in v['fields']:
                k = ('widget' if IS_WIDGET(f) else 'collection' if IS_COLL(f)
                     else 'reference' if IS_REF(f) else 'scalar')
                kinds[k] = kinds.get(k, 0) + 1
        print('entities %d   rows %d   %s' % (len(ents), tot,
              '  '.join('%s=%d' % kv for kv in sorted(kinds.items()))))
        cust = [e for e in ents if re.match(r'^(C_|Ce_|CE_|D_|g_|wc_|cf_)', e)]
        print('custom entities (%d): %s' % (len(cust), ', '.join(sorted(cust))))
    elif cmd == 'entity':
        e = rest[0]
        if e not in ents:
            near = [x for x in ents if e.lower() in x.lower()]
            print('no entity %r. close: %s' % (e, ', '.join(near[:10]))); return 1
        show_all = '--all' in rest
        print('%s  (table %s)' % (e, ents[e]['table']))
        for f in ents[e]['fields']:
            if not show_all and IS_WIDGET(f): continue
            print('  %-34s %-30s %s%s' % (f['name'], f['type'], flag(f),
                  ('  // ' + f['desc'][:60]) if f['desc'] else ''))
    elif cmd == 'rels':
        e = rest[0]
        for f in ents.get(e, {}).get('fields', []):
            if IS_COLL(f): print('  one-to-many  %-30s -> %s' % (f['name'], f['type'][12:-1]))
            elif IS_REF(f): print('  many-to-one  %-30s -> %s  %s' % (f['name'], f['type'], flag(f)))
    elif cmd == 'widgets':
        e = rest[0]
        ws = [f for f in ents.get(e, {}).get('fields', []) if IS_WIDGET(f)]
        print('%s: %d widgets' % (e, len(ws)))
        for f in ws: print('  %-38s %s' % (f['name'], f['desc'][:70]))
    elif cmd == 'type':
        e, fld = rest[0].split('.', 1)
        for f in ents.get(e, {}).get('fields', []):
            if f['name'] == fld:
                print('%s.%s -> %s %s' % (e, fld, f['type'], flag(f)))
                if f['desc']: print('  desc: ' + f['desc'])
                if f['examples']: print('  ' + f['examples'][:300])
                return 0
        print('not found: %s.%s' % (e, fld)); return 1
    elif cmd == 'find':
        pat = re.compile(rest[0], re.I)
        for e, v in sorted(ents.items()):
            if pat.search(e): print('ENTITY %s (table %s)' % (e, v['table']))
            for f in v['fields']:
                if pat.search(f['name']): print('  %-28s %-30s %s' % (e, f['name'], f['type']))
    elif cmd == 'lookups':
        pat = re.compile(rest[0], re.I) if rest else None
        seen = {}
        for e, v in ents.items():
            for f in v['fields']:
                if f['type'].startswith('Lookup List ('):
                    code = f['type'][13:-1]
                    if pat and not (pat.search(code) or pat.search(f['name'])): continue
                    seen.setdefault(code, []).append('%s.%s' % (e, f['name']))
        for code in sorted(seen):
            print('%-34s used by %d field(s)  e.g. %s' % (code, len(seen[code]), seen[code][0]))
    else:
        print(__doc__); return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
