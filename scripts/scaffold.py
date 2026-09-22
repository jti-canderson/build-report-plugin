#!/usr/bin/env python3
"""
Write a report folder's BOILERPLATE from a short spec, so the only thing authored by hand is
the part that carries a decision.

    python3 scaffold.py spec.json [--out DIR] [--force]

WHAT THIS IS NOT: it is not a kitchen-sink report that gets pruned. Deleting from a finished
layout is unsafe here - the templates compute column geometry from relative widths, so a
removed column leaves a hole rather than a narrower table, and a stranded <field> empties a
cell in silence. This generates FROM the spec, the same way parse_cols() computes widths
instead of anyone doing the arithmetic by hand.

WHAT IT WRITES  (three files, ~170 lines, none of it a decision)
    gen_jrxml.py                 the template call
    verification/fixture.py      the KEYS list, the row plumbing, the TSV writer
    verification/Fixture.groovy  the object graph rulecheck.groovy RUNS the rule against
    verification/run.sh          regenerate -> render each variant -> collect output

WHAT IT DELIBERATELY DOES NOT WRITE
    the .groovy rule        every line of it is a decision
    the fixture ROWS        seeded with placeholders and marked TODO. A fixture of tidy
                            rows proves nothing: the value is in the long label, the
                            missing sub-type, the hyphenated number - judgment, not shape.
    the NOTES blocks        see contract_docs.py

SPEC (see --example for a complete one)
    name       Case_Search            file stem; also the jrxml name
    title      "Case Search"          human name, masthead
    template   record_summary         module in templates/ - A record_summary, B tabular_list,
                                      C grouped_summary, D statement, E wide_table
    sections   [{key,title,cols}]     cols are [header, relative width, align, fieldName]
    meta/tiles [str]                  metadata strip labels, stat tile labels
    params     [[name, className]]    launch inputs. NO defaults - a defaultValueExpression
                                      marks a parameter the report supplies ITSELF (the logo),
                                      and eSeries binds the two differently.
    variants   ["full","none"]        fixture modes to render

Existing files are never overwritten without --force: the fixture rows and any hand-edit to
the generator are exactly what a re-scaffold would destroy.
"""
import importlib.util
import inspect
import json
import re
import subprocess
import os
import sys


TPL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")


def build_kwargs(module):
    """Which keyword arguments this template's build() actually accepts.

    The templates do NOT share one signature - found by forward-testing 2026-09-08.
    record_summary and eseries_summary take `sections`; tabular_list takes `columns`;
    grouped_summary, statement and wide_table take NOTHING and read module-level
    constants, so a report cannot parameterise them without editing the shared template
    and corrupting it for every other report. Emitting a call this template cannot
    accept produces a gen_jrxml.py that dies with a TypeError on first run, so this is
    checked at scaffold time and refused with a reason.
    """
    path = os.path.join(TPL_DIR, "templates", module + ".py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location(module, path)
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.join(TPL_DIR))
    sys.path.insert(0, os.path.join(TPL_DIR, "templates"))
    try:
        spec.loader.exec_module(m)
    except Exception:
        return None
    return set(inspect.signature(m.build).parameters)


EXAMPLE = {
    "name": "Case_Search", "title": "Case Search", "template": "record_summary",
    "letter": "A", "why": "the search itself is the record - masthead names it, tiles count it",
    "sections": [
        {"key": "RESULTS", "title": "Matching Cases",
         "cols": [["Case Number", 24, "Left", "caseNumber"],
                  ["Case Type", 22, "Left", "caseTypeLabel"],
                  ["Date", 18, "Left", "caseDate"]]},
        {"key": "BYTYPE", "title": "Count By Case Type",
         "cols": [["Case Type", 70, "Left", "caseTypeLabel"],
                  ["Cases", 30, "Right", "typeCount"]]}],
    "meta": ["Case Type", "From", "To", "Printed"],
    "tiles": ["Cases Found", "Case Types", "Jurisdictions"],
    "params": [["CaseType", "java.lang.String"], ["StartDate", "java.util.Date"]],
    "variants": ["full", "none"],
}

MAST = ["recTitle", "recKicker", "recSlug"]


def gen_jrxml(s):
    L = ['#!/usr/bin/env python3', '"""',
         f'{s["title"]} - laid out on the JTI `{s["template"]}` template'
         + (f' ({s["letter"]}).' if s.get("letter") else '.'), '']
    if s.get("why"):
        L += [f'WHY THIS TEMPLATE: {s["why"]}', '']
    L += ['    python3 gen_jrxml.py', '"""', 'import pathlib', 'import sys', '',
          'TPL = pathlib.Path.home() / "JaspersoftWorkspace/MyReports/jti-reports-plugin/templates"',
          'sys.path.insert(0, str(TPL))', 'sys.path.insert(0, str(TPL / "templates"))',
          f'import {s["template"]} as T   # noqa: E402', '',
          f'NAME = "{s["name"]}"', '',
          '# Named fields throughout - never the positional c1..c6. With cN, reordering a',
          '# column silently changes what every later column in that section means, and',
          '# nothing on the page shows it.', 'SECTIONS = [']
    for sec in s["sections"]:
        L.append(f'    ("{sec["key"]}", "{sec["title"]}", [')
        for h, w, a, f in sec["cols"]:
            L.append(f'        ({json.dumps(h) + ",":<19} {w:>3}, "{a}", "{f}"),')
        L.append('    ]),')
    L += [']', '',
          f'META = {json.dumps(s.get("meta", []))}',
          f'TILES = {json.dumps(s.get("tiles", []))}', '',
          '# Launch inputs. NO default - a parameter with a defaultValueExpression is one the',
          '# report supplies itself (the logo), and eSeries binds the two differently.',
          'PARAMS = [']
    for p in s.get("params", []):
        L.append(f'    ({json.dumps(p[0]) + ",":<15} {json.dumps(p[1]) + ",":<23} None),')
    L += [']', '', '',
          'def build():']
    if s.get("_kwargs") == "columns":
        # tabular_list takes a flat `columns` list, not sections. Its parse_cols honours a
        # 4-tuple, so the field NAMES from the spec survive - do not fall back to c1..cN.
        L += ['    return T.build(columns=[c for _, _, cols in SECTIONS for c in cols],',
              '                   name=NAME, params=PARAMS)']
    else:
        L += ['    return T.build(sections=SECTIONS, meta=META, tiles=TILES, name=NAME,'
              ' params=PARAMS)']
    L += [
          '', '',
          'if __name__ == "__main__":',
          '    out = pathlib.Path(__file__).parent / f"{NAME}.jrxml"',
          '    out.write_text(build())',
          '    print(f"wrote {out.name}  ({len(SECTIONS)} sections, "',
          '          f"{sum(len(s[2]) for s in SECTIONS)} columns, {len(PARAMS)} parameters)")', '']
    return "\n".join(L)


def gen_fixture(s, declared):
    """`declared` is the field list of the jrxml that was JUST generated, read back off
    disk - never a guess about what this template's masthead is called.

    Found by forward-testing 2026-09-08: this used to hardcode record_summary's contract
    (recTitle / m1v / t1v), so scaffolding onto tabular_list produced a fixture missing
    rptTitle / rptSubtitle / rptSlug. render_check catches it, but only after a render -
    and the fix loop is exactly the cost this script exists to remove. Deriving the keys
    from the artifact makes the fixture and the layout agree by construction.
    """
    keys = list(declared)
    sec_fields = {c[3] for sec in s["sections"] for c in sec["cols"]}
    masthead = [k for k in keys if k not in sec_fields and k != "section"]

    first = s["sections"][0]
    fields = [c[3] for c in first["cols"]]
    L = ['#!/usr/bin/env python3', '"""',
         f'Fixture rows for {s["title"]} - LAYOUT ONLY.', '',
         'Hand-written in the shape the rule emits: these rows prove the PAGE, never the',
         'model. A green render says the layout holds, not that any traversal resolves.', '',
         'KEYS is the field list of the generated .jrxml, read off the artifact itself, so',
         'the fixture cannot drift from the layout. Regenerate both together.', '',
         'TODO: make these rows AWKWARD. Tidy rows prove nothing worth knowing - what earns',
         'its keep is the label too long for its column, the row with a field missing, the',
         'hyphenated identifier. Every layout defect this harness has caught came from a',
         'deliberately ugly row.',
         '"""', 'import pathlib', 'import sys', '',
         f'KEYS = {json.dumps(keys)}', '',
         f'# TODO: real, awkward rows. Columns: {", ".join(fields)}',
         f'{first["key"]} = [',
         '    (' + ', '.join(f'"TODO {f}"' for f in fields) + '),',
         '    # ... a row with a missing value, a row with an over-long label ...', ']', '']

    extra = s["sections"][1:]
    for sec in extra:
        f2 = [c[3] for c in sec["cols"]]
        L += [f'# Columns: {", ".join(f2)}',
              f'{sec["key"]} = [', '    (' + ', '.join(f'"TODO {f}"' for f in f2) + '),', ']', '']

    L += ['# Every non-column field the jrxml declares. These are read in the title band, so',
          '# a missing one blanks the header for the whole report.', 'MASTHEAD = {']
    for k in masthead:
        if k in ("recTitle", "rptTitle"):
            L.append(f'    {json.dumps(k)}: {json.dumps(s["title"])},')
        elif k.startswith("t") and k.endswith("v"):
            L.append(f'    {json.dumps(k)}: "0",')
        else:
            L.append(f'    {json.dumps(k)}: "TODO {k}",')
    L += ['}', '', '',
          'def _row(**kw):',
          '    r = {k: "" for k in KEYS}',
          '    r.update(MASTHEAD)',
          '    r.update(kw)',
          '    return r', '', '',
          'def rows(mode=""):',
          '    if mode == "none":',
          '        # The no-matches page must still SAY so. A blank page and a page that',
          '        # reports zero look identical to the harness and nothing alike to a reader.',
          '        return [_row(' + (f'section={json.dumps(first["key"])}, '
                                    if "section" in keys else '')
          + f'{fields[0]}="No rows matched")]']
    L += [f'    out = [_row(' + (f'section={json.dumps(first["key"])}, '
                                if "section" in keys else '')
          + ', '.join(f'{f}={f[0]}{i}' for i, f in enumerate(fields)) + ')',
          '           for ' + ', '.join(f'{f[0]}{i}' for i, f in enumerate(fields))
          + f' in {first["key"]}]']
    for sec in extra:
        f2 = [c[3] for c in sec["cols"]]
        L.append(f'    out += [_row(section={json.dumps(sec["key"])}, '
                 + ', '.join(f'{f}={f[0]}{i}' for i, f in enumerate(f2)) + ')')
        L.append('            for ' + ', '.join(f'{f[0]}{i}' for i, f in enumerate(f2))
                 + f' in {sec["key"]}]')
    L += ['    return out', '', '',
          'if __name__ == "__main__":',
          '    mode = sys.argv[1] if len(sys.argv) > 1 else ""',
          '    # One TSV per variant: run.sh writes them all first, then fills them from a',
          '    # SINGLE compile. A shared fixture.tsv would be overwritten by the next',
          '    # variant before the JVM had read it.',
          '    out = pathlib.Path(__file__).parent / f"fixture_{mode or \'full\'}.tsv"',
          '    rs = rows(mode)',
          '    with out.open("w") as f:',
          '        f.write("\\t".join(KEYS) + "\\n")',
          '        for r in rs:',
          '            f.write("\\t".join(str(r[k]).replace("\\t", " ") for k in KEYS) + "\\n")',
          '    print(f"wrote {out.name}  ({len(rs)} rows, mode={mode or \'full\'})")', '']
    return "\n".join(L)


def gen_groovy_fixture(s):
    """The object graph `rulecheck.groovy` runs the rule against.

    This is what makes the rule EXECUTE locally rather than merely be inspected. Without it
    the only gates are text comparisons, and a rule ending `data = rows` - one character
    short of `_data` - passed all of them and died on first use in eSeries (09/17).

    Maps, not Expandos: a missing key answers null, which is exactly how a rule's guarded
    accessors expect an absent property to behave. Start minimal and add only what the rule
    actually reads - a fixture that answers everything proves nothing about guards.
    """
    root = s.get("root", "Case")
    return "\n".join([
        f'// Object graph for {s["title"]} - drives rulecheck.groovy, NOT the page render.',
        '// (verification/fixture.py holds the ROW fixture that drives the layout.)',
        '//',
        '// Maps, not Expandos: a missing key answers null, which is how the rule\'s guarded',
        '// accessors expect an absent property to behave. Add keys only as the rule needs',
        '// them - a fixture that answers everything stops proving the guards work.',
        f'ROOT_FIXTURE = [id: \'{s.get("id", "19")}\', caseNumber: \'CF-2026-00184\']',
        '',
        '// What DomainObject.find() returns. A single-record report can leave this alone;',
        '// a search rule should list a few rows here.',
        'SEARCH_RESULTS = [ROOT_FIXTURE]',
        '',
    ])


def gen_run(s):
    variants = s.get("variants", ["full", "none"])
    name = s["name"]
    L = ['#!/bin/sh',
         f'# Regenerate, compile, fill and raster every page of {s["title"]}.',
         '#',
         '#   ./verification/run.sh render          every variant  (' + ' '.join(variants) + ')',
         '#   ./verification/run.sh render full     ONE variant - use this during a fix loop',
         '#',
         '# The whole pass is ONE JVM: the jrxml is compiled once and each variant filled',
         '# from that compile. Measured 2026-09-04 - a JVM start plus JasperReports class',
         '# init is ~5.8s before any work happens, while a warm second fill is a fraction of',
         '# that, so a variant per process paid the startup again for identical output.',
         '# Narrowing to one variant during a fix loop still helps: the no-matches page only',
         '# has to be right at the end, the populated one has to be right every time.',
         '# Render every variant before reporting back - an unexamined page is worth nothing.',
         '#',
         '# LAYOUT ONLY. The fixture is hand-written, so a green run proves the page and',
         '# says nothing about whether any path resolves in the target environment.',
         'set -e',
         '# JRS override wins; otherwise take the newest install found. A hardcoded version',
         '# number is another way this worked on one machine only.',
         'if [ -z "${JRS:-}" ]; then',
         '  for c in /Applications/jasperreports-server-* "$HOME"/jasperreports-server-*; do',
         '    [ -d "$c/java/bin" ] && JRS="$c"',
         '  done',
         'fi',
         'JRS="${JRS:-/Applications/jasperreports-server-9.0.0}"',
         'JAVA="$JRS/java/bin/java"',
         'CP="$JRS/buildomatic/lib/groovy-3.0.13.jar:$JRS/apache-tomcat/webapps/jasperserver-pro/WEB-INF/lib/*"',
         '[ -x "$JAVA" ] || { echo "no JVM at $JAVA - set JRS to your JasperReports Server install"; exit 2; }',
         'HERE=$(cd "$(dirname "$0")/.." && pwd)',
         '',
         '# FIND the plugin; never hardcode a home directory. Until 09/18 this line read',
         '# TPL="$HOME/JaspersoftWorkspace/MyReports/jti-reports-plugin/templates", baked into',
         '# every generated harness - so the scripts worked on exactly one machine and broke',
         '# silently, per report, for anyone else.',
         'find_plugin() {',
         '  if [ -n "${JTI_PLUGIN:-}" ] && [ -d "$JTI_PLUGIN/templates" ]; then',
         '    echo "$JTI_PLUGIN"; return',
         '  fi',
         '  d="$HERE"',
         '  while [ "$d" != "/" ]; do',
         '    if [ -d "$d/jti-reports-plugin/templates" ]; then echo "$d/jti-reports-plugin"; return; fi',
         '    if [ -d "$d/templates" ] && [ -d "$d/skills/jasper-reports" ]; then echo "$d"; return; fi',
         '    d=$(dirname "$d")',
         '  done',
         '  # the installed plugin snapshot, newest version last',
         '  for c in "$HOME"/.claude/plugins/cache/*/jti-reports/*/; do',
         '    [ -d "$c/templates" ] && p="$c"',
         '  done',
         '  [ -n "${p:-}" ] && echo "${p%/}"',
         '}',
         'PLUGIN=$(find_plugin)',
         '[ -n "$PLUGIN" ] || { echo "cannot find jti-reports-plugin - set JTI_PLUGIN to its folder"; exit 2; }',
         'TPL="$PLUGIN/templates"',
         'SKILL="$PLUGIN/skills/jasper-reports"',
         'cd "$HERE"',
         '',
         f'WANT="${{2:-{" ".join(variants)}}}"',
         'rm -f verification/*_p*.png verification/*.pdf verification/fixture_*.tsv',
         'python3 gen_jrxml.py',
         '',
         '# A TSV per variant, written BEFORE the JVM starts - one shared fixture.tsv would',
         '# be overwritten by the next variant before the JVM had read it.',
         'ARGS=""',
         'for v in $WANT; do',
         '  case "$v" in full) mode="";; *) mode="$v";; esac',
         '  python3 verification/fixture.py "$mode" >/dev/null',
         '  ARGS="$ARGS --variant ${v}_sample=verification/fixture_${v}.tsv"',
         'done',
         '',
         '# $ARGS is deliberately unquoted - it is a list of flags, not one word.',
         '#',
         '# The JVM is piped through grep to drop the log4j wall - and in a pipeline $? is',
         "# GREP's status, not the render's, so a CONTRACT FAIL exit(3) was swallowed and the",
         '# build reported success. Caught 2026-09-08 forward-testing: finish.sh printed "All',
         '# gates passed" over a render that had failed. Capture the status, THEN filter.',
         '# `|| rc=$?` and not a bare call: under `set -e` a failing JVM aborts the script',
         '# at this line, before the captured log is ever printed - so the build fails with',
         '# no diagnostic at all. Making it a condition lets the log through first.',
         'log=$(mktemp); rc=0',
         '"$JAVA" -Djava.awt.headless=true -cp "$CP" groovy.ui.GroovyMain \\',
         f'  "$TPL/render_check.groovy" "$HERE/{name}.jrxml" --out verification $ARGS \\',
         '  >"$log" 2>&1 || rc=$?',
         "grep -vE '^\\s+at |^\\s+\\.\\.\\. |log4j|SLF4J|Illegal reflective|font \"Times\"|^$' \"$log\" || true",
         'rm -f "$log"',
         '[ $rc -eq 0 ] || { echo "  render FAILED (exit $rc)"; exit $rc; }',
         '',
         '# The PNGs render_check writes come from AWT and show glyphs the PDF drops (see',
         '# jti_style._winansi). Re-raster from the PDF so the page inspected is the page',
         '# that ships. Same filenames, so nothing downstream changes.',
         'for p in verification/*_sample.pdf; do',
         '  [ -f "$p" ] && python3 "$SKILL/scripts/pdfraster.py" "$p" >/dev/null 2>&1',
         'done',
         'echo "output in verification/"',
         '']
    return "\n".join(L)


def main():
    if '--example' in sys.argv:
        print(json.dumps(EXAMPLE, indent=2)); return
    if len(sys.argv) < 2 or sys.argv[1].startswith('-'):
        print(__doc__); sys.exit(2)

    spec = json.load(open(sys.argv[1], encoding='utf8'))
    # A "match this picture" spec carries no template on purpose: the builder could not pick
    # one and neither can this script - something has to LOOK at the reference first. Say
    # that, rather than "spec is missing 'template'", which reads like a corrupt file.
    if not spec.get('template') and spec.get('look_like'):
        print(f"  this spec says: match {spec['look_like']} - no template chosen yet.\n"
              f"  A picture has to be read before a starting template can be named, so run\n"
              f"  /jti-reports:build-report on it instead of scaffolding it directly.")
        sys.exit(2)
    # A brief-only spec: a template is chosen but the columns were left to the brief rather
    # than typed. The columns do not exist yet, so scaffolding would emit an empty grid. Say
    # so plainly - the same shape of message as look_like - rather than "missing 'sections'",
    # which reads like a corrupt file. /build-report derives the columns from `intent`.
    if spec.get('template') and not spec.get('sections') and (spec.get('intent') or '').strip():
        print(f"  this spec has a brief but no columns yet:\n"
              f"    \"{spec['intent'].strip()[:72]}\"\n"
              f"  The columns come from that brief, and something has to derive them first, so\n"
              f"  run /jti-reports:build-report on it instead of scaffolding it directly.")
        sys.exit(2)
    for k in ('name', 'title', 'template', 'sections'):
        if not spec.get(k):
            print(f"  spec is missing '{k}'"); sys.exit(2)

    # Refuse at scaffold time rather than emitting a gen_jrxml.py that dies on first run.
    kw = build_kwargs(spec['template'])
    if kw is None:
        print(f"  cannot read templates/{spec['template']}.py - check the template name")
        sys.exit(2)
    if 'sections' in kw:
        spec['_kwargs'] = 'sections'
    elif 'columns' in kw:
        spec['_kwargs'] = 'columns'
    else:
        print(f"  templates/{spec['template']}.py cannot be parameterised.\n"
              f"  Its build() takes no arguments - it reads module-level COLUMNS and NAME, so a\n"
              f"  report using it would have to edit the shared template and break it for every\n"
              f"  other report. Use a template whose build() accepts sections= or columns=\n"
              f"  (record_summary, eseries_summary, tabular_list), or open this one up first.")
        sys.exit(2)

    out = os.path.abspath(sys.argv[sys.argv.index('--out') + 1]) if '--out' in sys.argv \
        else os.path.dirname(os.path.abspath(sys.argv[1]))
    force = '--force' in sys.argv
    os.makedirs(os.path.join(out, 'verification'), exist_ok=True)

    # Write and RUN gen_jrxml first: the fixture's key list is read off the generated
    # jrxml, so it cannot disagree with the layout it is meant to fill.
    gj = os.path.join(out, 'gen_jrxml.py')
    if not os.path.exists(gj) or force:
        open(gj, 'w', encoding='utf8').write(gen_jrxml(spec))
        print(f"  wrote   gen_jrxml.py  ({len(gen_jrxml(spec).splitlines())} lines)")
    else:
        print("  kept    gen_jrxml.py  (exists - --force to overwrite)")
    r = subprocess.run([sys.executable, 'gen_jrxml.py'], cwd=out,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        print("  gen_jrxml.py failed - fix the spec before scaffolding the rest")
        sys.exit(1)
    print("  " + r.stdout.strip())
    jrxml = os.path.join(out, spec['name'] + '.jrxml')
    declared = re.findall(r'<field\s+name="([^"]+)"', open(jrxml, encoding='utf8').read())

    if '--fixture-only' in sys.argv:
        # After hand-editing gen_jrxml.py, the fixture's KEYS are stale - and --force would
        # overwrite the very generator that was edited. This refreshes ONLY the fixture.
        fp = os.path.join(out, 'verification', 'fixture.py')
        open(fp, 'w', encoding='utf8').write(gen_fixture(spec, declared))
        print(f"  wrote   verification/fixture.py  (KEYS refreshed from {spec['name']}.jrxml)")
        print("  Re-fill the rows - they were replaced with TODOs.")
        return

    files = [(os.path.join('verification', 'fixture.py'), gen_fixture(spec, declared), False),
             (os.path.join('verification', 'Fixture.groovy'), gen_groovy_fixture(spec), False),
             (os.path.join('verification', 'run.sh'), gen_run(spec), True)]
    for rel, body, ex in files:
        p = os.path.join(out, rel)
        if os.path.exists(p) and not force:
            print(f"  kept    {rel}  (exists - --force to overwrite)")
            continue
        open(p, 'w', encoding='utf8').write(body)
        if ex:
            os.chmod(p, 0o755)
        print(f"  wrote   {rel}  ({len(body.splitlines())} lines)")

    print(f"\n  Next, and none of it is boilerplate:")
    print(f"    1. the .groovy rule - every line is a decision")
    print(f"    2. real AWKWARD fixture rows (the TODOs in fixture.py)")
    print(f"    3. run the gates:  finish.sh <rule>.groovy {spec['name']}.jrxml --code ...")


if __name__ == '__main__':
    main()
