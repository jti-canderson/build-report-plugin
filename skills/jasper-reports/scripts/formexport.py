#!/usr/bin/env python3
"""
Read an eSeries config export (FORM / REPORT / RULE) and print what a report builder needs:
the root entity, the panels, and the authoritative field paths.

    python3 formexport.py EXPORT.zip              # outline: panels, columns, paths
    python3 formexport.py EXPORT.zip --paths      # unique paths only, one per line
    python3 formexport.py EXPORT.zip --velocity   # the static-text / widget templates
    python3 formexport.py EXPORT.zip --json       # the decoded srcContent, pretty-printed
    python3 formexport.py RULE-*.zip              # a RULE: registration, params, script size
    python3 formexport.py RULE-*.zip --script     # ... and the whole Groovy body

Format (verified on FORM=FV-AdultCaseSummary.xml, exported from okdac-qa 08/21/2026):

  A zip holding one file per exported record, named <ROOT>=<code>.xml. Each is a
  com.sustain.api.model.ConfigExportRsp with:
      srcRoot        FORM | REPORT | RULE - what kind of record this is
      srcCode        the record's Code
      srcId          its primary key IN THE SOURCE ENVIRONMENT ONLY
      srcActionUrl   the admin URL it came from - this names the environment, so quote it
      srcHash        change detection
      srcContent     the payload: JSON, HTML-entity-escaped inside the XML text node
      srcImportContent   the same payload as the importer consumes it

  A FORM's srcContent gives: rootEntity (the report root), code, formName, and a FLAT
  formItems list ordered by num. There is no nesting - a panel owns every item after it
  until the next panel.

      type 2  panel      label, grid, treeTable, columnHeaders, columnStyles, footerText
      type 0  data field path - the authoritative traversal from rootEntity
      type 7  widget     path ends in a Widget/Icon name, config in parameters
      type 1  static     staticFieldText, Velocity, no path of its own
      type 3  panel end  previewSummary

  newColumn / newRow drive layout: an item with newColumn starts a grid column, so the
  panel's columnHeaders map positionally onto those items - that is how you recover which
  header labels which path.

Why this matters for a report: the paths here are what the screen actually renders, so they
are worth more than the entity metadata - they are proven traversals, and cf_ marks a custom
field. A widget or static item has no path of its own and inherits $object from the item
before it, which is the scoping trap documented in the velocity-widgets skill.
"""
import sys, re, json, html, zipfile, os

TYPE = {0: 'field', 1: 'static', 2: 'PANEL', 3: 'end', 7: 'widget'}


def members(path):
    """Yield (name, xml_text) for an export zip, or the single xml if given one."""
    if path.lower().endswith('.zip'):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith('.xml'):
                    yield n, z.read(n).decode('utf8', 'replace')
    else:
        yield os.path.basename(path), open(path, encoding='utf8', errors='replace').read()


def meta(xml):
    out = {}
    for tag in ('srcRoot', 'srcCode', 'srcId', 'srcHash', 'srcActionUrl'):
        m = re.search(rf'<{tag}>(.*?)</{tag}>', xml, re.S)
        out[tag] = html.unescape(m.group(1)).strip() if m else ''
    return out


def import_content(xml):
    """srcImportContent - the structured payload the importer consumes. For a RULE this is a
    com.sustain.rule.model.RuleDef and is AUTHORITATIVE: srcContent's delimited text form
    cannot express lookupListName or REQUIRED/OPTIONAL, so it is lossy."""
    m = re.search(r'<srcImportContent>(.*?)</srcImportContent>', xml, re.S)
    return html.unescape(m.group(1)) if m else None


def ruledef(imp):
    """Pull the rule's registration out of a RuleDef payload."""
    g = lambda tag, src=imp: (re.search(rf'<{tag}>(.*?)</{tag}>', src, re.S).group(1)
                              if re.search(rf'<{tag}>(.*?)</{tag}>', src, re.S) else '')
    out = {t: g(t) for t in ('code', 'name', 'description', 'category', 'system', 'apiEnabled',
                             'caseEnabled', 'docEnabled', 'batchEnabled', 'engineClassName',
                             'transactional')}
    for kind, tag in (('inputs', 'RuleInputParam'), ('outputs', 'RuleOutputParam')):
        rows = []
        block = re.search(rf'<{kind}>(.*?)</{kind}>', imp, re.S)
        if block:
            for pm in re.finditer(rf'<com\.sustain\.rule\.model\.{tag}>(.*?)</com\.sustain\.rule\.model\.{tag}>',
                                  block.group(1), re.S):
                rows.append({k: g(k, pm.group(1)) for k in
                             ('name', 'className', 'presetValue', 'pos', 'type', 'lookupListName')})
        out[kind] = rows
    # <script> is not the Groovy - it is a nested doc: <code>, <category>, <language>,
    # <content>. The Groovy sits in <content>, escaped one level deeper than the tags
    # around it (so a CR reads &amp;#xd; at file level, &#xd; here).
    m = re.search(r'<script>(.*?)</script>', imp, re.S)
    inner = m.group(1) if m else ''
    c = re.search(r'<content>(.*?)</content>', inner, re.S)
    out['script'] = html.unescape(c.group(1)) if c else ''
    out['script_language'] = (re.search(r'<language>(.*?)</language>', inner).group(1)
                              if re.search(r'<language>(.*?)</language>', inner) else '')
    return out


def show_rule(imp, dump_script=False):
    r = ruledef(imp)
    print(f"  name       : {r['name']}")
    print(f"  category   : {r['category']}   transactional: {r['transactional']}")
    print(f"  engine     : {r['engineClassName'].rsplit('.', 1)[-1]}")
    flags = [k for k in ('system', 'apiEnabled', 'caseEnabled', 'docEnabled', 'batchEnabled')
             if r[k] == 'true']
    print(f"  flags      : {', '.join(flags) if flags else '(none set)'}")
    for kind in ('inputs', 'outputs'):
        print(f"\n  {kind.upper()}  (the rule reads each as _<name>)")
        if not r[kind]:
            print("    (none)")
        for p in r[kind]:
            lk = f"  lookup={p['lookupListName']}" if p['lookupListName'] else ''
            print(f"    {p['pos']}  {p['name']:22} {p['className']:44} {p['type']:9}{lk}")
    print(f"\n  script     : {len(r['script'])} chars of Groovy"
          f"{' - printed below' if dump_script else ' (--script to print)'}")
    if dump_script:
        print('-' * 72)
        print(r['script'])
    return r


def content(xml):
    m = re.search(r'<srcContent>(.*?)</srcContent>', xml, re.S)
    if not m:
        return None
    raw = html.unescape(m.group(1))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw            # REPORT/RULE payloads are not always JSON


def outline(cfg, show_velocity=False):
    print(f"  rootEntity : {cfg.get('rootEntity')}   <- the report root")
    print(f"  formName   : {cfg.get('formName')}  (code {cfg.get('code')})")
    items = cfg.get('formItems') or []
    print(f"  formItems  : {len(items)}\n")
    headers, hi = [], 0
    for it in items:
        t, path = it.get('type'), it.get('path') or ''
        if t == 2:
            headers = it.get('columnHeaders') or []
            hi = 0
            grid = ' [grid]' if it.get('grid') else ''
            grid += ' [tree]' if it.get('treeTable') else ''
            print(f"\nPANEL  {it.get('label')}{grid}")
            if headers:
                print(f"       columns: {' | '.join(h if h.strip('&#160; ') else '(blank)' for h in headers)}")
            continue
        if t == 3:
            continue
        col = ''
        if it.get('newColumn') or hi == 0:
            col = headers[hi] if hi < len(headers) else ''
            hi += 1
        tag = TYPE.get(t, f'type{t}')
        note = ''
        if t == 7 and it.get('parameters'):
            note = '  ' + json.dumps(it['parameters'])[:80]
        if t == 1:
            txt = it.get('staticFieldText')
            txt = ' '.join(txt) if isinstance(txt, list) else str(txt)
            note = '  ' + txt[:80].replace('\n', ' ')
        print(f"    {tag:7} {str(col)[:16]:18} {path:52}{note}")
        if show_velocity and t in (1, 7):
            body = it.get('staticFieldText') or (it.get('parameters') or {}).get('template')
            if body:
                for line in (body if isinstance(body, list) else [body]):
                    print(f"             | {line}")


def as_spec(cfg):
    """The folder view as data the report builder can prefill from.

    A panel becomes a SECTION; its column headers become COLUMNS. A header can be fed by
    several field items (First Name = namePrefix + firstName), so the first path wins and
    the rest ride along in `also` - the rule may want to join them, which is a decision for
    a person, not something to guess here.

    FIELD NAMES ARE MADE UNIQUE ACROSS THE WHOLE FORM, not per panel: the .jrxml declares
    one flat field list, so a `status` in two panels would collide into a single field and
    one of them would quietly show the other's value.
    """
    panels, used = [], set()

    def name_for(path, panel_key):
        base = re.sub(r'[^A-Za-z0-9]', '', (path or 'col').rsplit('.', 1)[-1]) or 'col'
        base = base[0].lower() + base[1:]
        if base not in used:
            used.add(base)
            return base
        pref = re.sub(r'[^A-Za-z0-9]', '', panel_key).lower()[:6] or 'x'
        cand = pref + base[0].upper() + base[1:]
        n = 2
        while cand in used:
            cand, n = f"{pref}{base[0].upper()}{base[1:]}{n}", n + 1
        used.add(cand)
        return cand

    headers, hi, cur = [], 0, None
    items = cfg.get('formItems') or []

    # A SEARCH form (S-*) has no panel items at all - just a flat list of fields - so the
    # panel-driven walk below would yield nothing and the caller would be told "no folder
    # view here" about a file that plainly is a form. Those fields are exactly the columns
    # a list report wants, so give them one section named after the form.
    if not any(i.get('type') == 2 for i in items) and any(i.get('path') for i in items):
        cols, seen_p = [], set()
        for it in items:
            path = it.get('path') or ''
            if not path or it.get('type') == 3 or path in seen_p:
                continue
            seen_p.add(path)
            cols.append({"header": it.get('label') or path.rsplit('.', 1)[-1],
                         "path": path, "also": []})
        key = re.sub(r'[^A-Za-z0-9]', '', cfg.get('code') or 'ROWS').upper()[:14] or 'ROWS'
        for c in cols:
            c["field"] = name_for(c["path"], key)
        return {"root": cfg.get('rootEntity'), "formName": cfg.get('formName'),
                "code": cfg.get('code'), "searchForm": True,
                "panels": [{"label": cfg.get('formName') or 'Rows', "grid": True,
                            "key": key, "columns": cols}] if cols else []}

    for it in items:
        t, path = it.get('type'), it.get('path') or ''
        if t == 2:
            cur = {"label": it.get('label') or 'Panel', "grid": bool(it.get('grid')),
                   "columns": []}
            panels.append(cur)
            headers, hi = it.get('columnHeaders') or [], 0
            continue
        if t == 3 or cur is None or not path:
            continue
        starts = bool(it.get('newColumn')) or hi == 0
        if starts:
            h = headers[hi] if hi < len(headers) else ''
            hi += 1
            h = '' if not h or not h.strip('&#160; ') else h
            cur["columns"].append({"header": h or path.rsplit('.', 1)[-1],
                                   "path": path, "also": []})
        elif cur["columns"]:
            cur["columns"][-1]["also"].append(path)

    for pnl in panels:
        key = re.sub(r'[^A-Za-z0-9]', '', pnl["label"]).upper()[:14] or 'PANEL'
        pnl["key"] = key
        for c in pnl["columns"]:
            c["field"] = name_for(c["path"], key)

    return {"root": cfg.get('rootEntity'), "formName": cfg.get('formName'),
            "code": cfg.get('code'),
            "panels": [p for p in panels if p["columns"]]}


def paths(cfg):
    seen, out = set(), []
    for it in cfg.get('formItems') or []:
        p = it.get('path')
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else ''
    # --spec: the builder-shaped view. An archive can hold several folder views, so this
    # emits a LIST and lets the caller choose - picking the first silently would hand
    # someone a report built from whichever form happened to sort first.
    specs = []
    # --spec emits JSON on stdout and NOTHING else. A stray banner line ahead of it is not
    # cosmetic: the caller does json.loads() on the whole stream and gets an exception.
    say = (lambda *a: None) if mode == '--spec' else print
    for name, xml in members(src):
        m = meta(xml)
        if mode != '--spec':
            say(f"=== {name} ===")
        say(f"  {m['srcRoot']} {m['srcCode']}  (id {m['srcId']} in the SOURCE environment only)")
        say(f"  from: {m['srcActionUrl']}")
        cfg = content(xml)
        if cfg is None:
            if '<jasperReport' in xml:
                say("  This is a .jrxml, not a config export - the template IS the contract.")
                say("  Read its <field>/<parameter> declarations and write the rule to them;")
                say("  see 'A .jrxml: the template is the contract' in SKILL.md.")
            else:
                say("  No srcContent - not an eSeries config export.")
            continue
        imp = import_content(xml)
        if m['srcRoot'] == 'RULE' and imp and mode not in ('--json', '--spec'):
            show_rule(imp, dump_script=(mode == '--script'))
            continue
        if mode == '--spec':
            if isinstance(cfg, dict) and cfg.get('formItems'):
                specs.append(as_spec(cfg))
        elif mode == '--json':
            print(json.dumps(cfg, indent=2) if isinstance(cfg, dict) else cfg)
        elif mode == '--paths':
            for p in paths(cfg):
                print(p)
        elif isinstance(cfg, dict):
            outline(cfg, show_velocity=(mode == '--velocity'))
        else:
            print(cfg[:4000])


    if mode == '--spec':
        print(json.dumps(specs, indent=2))


if __name__ == '__main__':
    main()
