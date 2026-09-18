#!/usr/bin/env python3
"""
Write an eSeries RULE config export that can be IMPORTED, instead of hand-typing a rule into
the editor and declaring its parameters one row at a time.

    # build an importable zip from a .groovy file
    python3 rule_import.py --groovy Certified_Discovery_Report_V1.groovy \
        --code Certified_Discovery_Report --name "Certified Discovery Report" \
        --input caseId:java.lang.Long --input discoveryItemId:java.lang.Long \
        --output data:java.util.List --out RULE-Certified_Discovery_Report.zip

    # prove the writer against a real export: regenerate it and diff
    python3 rule_import.py --selftest ~/Downloads/RULE-local-2026-08-21.zip

An --input is  name:className[:LOOKUP_LIST][:REQUIRED]  - the bare name, no leading
underscore; the rule reads it as _name. Shorthands: date, string, long, bool, lookup.

FORMAT (reverse-engineered from RULE=Official_Depository_Ticket.xml, okdac-qa 08/21/2026, and
now reproduced BYTE-IDENTICALLY for all 11 real exports on hand - 5 environments, 2024 to 2026,
scripting and Java-engine rules, transactional and not, with and without outputs and presets.
`--selftest` over every one of them is the oracle; run it against each new export that shows up,
because each of these behaviours was found only by a diff, never by reading the file:

  - outputs always print '???' whatever their class; inputs print a per-class literal
  - a presetValue prints RAW and unquoted, overriding the class literal
  - Long / Double / Integer all print -1; a domain class prints new <SimpleName>()
  - the transactional banner follows the LAST parameter block and adds a blank line
  - no outputs means the OUTPUT block is omitted, not emitted empty
  - an empty collection is <outputs/>, not <outputs></outputs>
  - a Java-engine rule ends srcContent with new <engine>().run(); and carries NO <script>
  - the script's trailing newlines are data: never add one, never strip one):

  <com.sustain.api.model.ConfigExportRsp> with, in this order, srcActionUrl, srcContent,
  srcImportContent, srcRoot, srcHash, srcCode, srcId. No XML declaration.

  srcContent        the round-trip TEXT form: the parameters as example assignments
                    (_startDate = new Date();  _agency = 'ABC';  _data = '???';) inside
                    // --- INPUT PARAMETERS START/END ---, OUTPUT ..., RULE CONTENT ...
                    LOSSY - it cannot express lookupListName or REQUIRED vs OPTIONAL.
  srcImportContent  a com.sustain.rule.model.RuleDef: code, name, description, category,
                    the system/api/case/doc/batch flags, <inputs> of RuleInputParam,
                    <outputs> of RuleOutputParam, engineClassName, transactional, script.
                    AUTHORITATIVE - this is what the importer consumes.

  Both payloads live in XML text nodes, XStream-escaped: & < > " ' become entities, and
  because the payload uses CRLF, every CR becomes &#xd; with the LF left literal. Getting
  that wrong is the likeliest reason a hand-built file is rejected.

  Each nested param carries <ruleDef reference="../../.."/> - an XStream back-reference to
  the owning RuleDef. It is structural, not data; emit it verbatim.

VERIFIED 2026-09-03 (eh-team-config-symphony.logan-symphony.com): a hand-built file DOES
import - it created rule 10130 there, script and both parameter rows intact. The importer
requires srcActionUrl/srcHash/srcId to be NON-EMPTY; empty tags fail as "error reading zip
file" (see the note in wrapper()). Endpoint, for reference, is a multipart POST to
/ecms/admin/rule/index/import with the file in a part named 'file' plus the page's CSRF
token; it answers 200 with JSON {errors:[...], messages:[...]} either way, so the JSON - not
the status - is what says whether it worked.

STILL UNVERIFIED: what the importer does when the target already has a rule with this Code.
Reports Admin's own Import creates rather than updates, so assume this may too until proven.
Importing is a WRITE: hand the zip to the user, never import it yourself.
"""
import sys, os, re, html, zipfile, argparse, hashlib, difflib

CLASSES = {'date': 'java.util.Date', 'string': 'java.lang.String', 'long': 'java.lang.Long',
           'int': 'java.lang.Integer', 'bool': 'java.lang.Boolean',
           'boolean': 'java.lang.Boolean', 'list': 'java.util.List',
           'lookup': 'com.sustain.lookuplist.model.LookupItem',
           'decimal': 'java.math.BigDecimal'}

# The example literal each class takes in srcContent's text form. These are the PLATFORM's
# literals, not ours - a selftest diff is the only way to learn one. Long is -1 and Double is
# -1 (evidenced by RULE=CHECK_GENERAL okdac-qa 09/03/2026 and RULE=ADD_FEE ocda-config
# 09/03/2026); Integer/BigDecimal are still guesses.
#
# java.util.List used to sit here mapped to '???'. That was a misreading: '???' is what the
# platform writes for EVERY output regardless of class (ADD_FEE's output is an Invoice and
# still prints '???'), and the only List we had seen happened to be an output. Outputs are
# now handled by literal(is_output=True) and a List *input* is genuinely unknown.
EXAMPLE = {'java.util.Date': 'new Date()', 'java.lang.String': "'ABC'",
           'com.sustain.lookuplist.model.LookupItem': 'new LookupItem()',
           'java.lang.Boolean': 'true', 'java.lang.Long': '-1',
           'java.lang.Double': '-1',
           'java.lang.Integer': '-1', 'java.math.BigDecimal': 'new BigDecimal(0)'}


def literal(param, is_output=False):
    """The example assignment srcContent shows for one parameter.

    Outputs are always '???'. An input carrying a presetValue prints that value RAW - not
    quoted, not escaped as a literal - so `_sqlQuery = SELECT TOP 10 * FROM tCase;` and
    `_DateField = receivedDate;` (evidenced by RULE=WGT_SQL_QUERY okdac-08-config 08/21/2025
    and RULE=CASE_AGE_CASELOAD 03/14/2025). Only a preset-less input falls back to a per-class
    literal, and a domain class the table does not name gets `new <SimpleName>()`, which is how
    Case, Party and LookupItem all print.
    """
    if is_output:
        return "'???'"
    preset = (param.get('presetValue') or '').strip()
    if preset:
        return preset
    cls = param['className']
    if cls in EXAMPLE:
        return EXAMPLE[cls]
    if cls.startswith('java.'):
        return 'null'
    return 'new %s()' % cls.rsplit('.', 1)[-1]

ENGINE = 'com.sustain.rule.engine.ScriptingRuleEngine'


def esc(text):
    """XStream-style: full entity escaping, CR as &#xd;, LF left literal."""
    out = (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
               .replace('"', '&quot;').replace("'", '&apos;'))
    return out.replace('\r', '&#xd;')


def crlf(text):
    return text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')


def parse_param(spec):
    bits = spec.split(':')
    name, cls = bits[0], CLASSES.get(bits[1].lower(), bits[1]) if len(bits) > 1 else 'java.lang.String'
    lookup, ptype = '', 'OPTIONAL'
    for extra in bits[2:]:
        if extra.upper() in ('REQUIRED', 'OPTIONAL'):
            ptype = extra.upper()
        else:
            lookup = extra
    return {'name': name, 'className': cls, 'presetValue': '', 'type': ptype,
            'lookupListName': lookup}


def src_content(inputs, outputs, script, meta=None):
    meta = meta or {}
    L = ['', '// --- INPUT PARAMETERS START ---']
    for p in inputs:
        L.append(f"_{p['name']} = {literal(p)};")
    L.append('// --- INPUT PARAMETERS END ---')
    # With no outputs the platform omits the whole OUTPUT block rather than emitting empty
    # markers.
    if outputs:
        L += ['', '// --- OUTPUT PARAMETERS START ---']
        for p in outputs:
            L.append(f"_{p['name']} = {literal(p, is_output=True)};")
        L.append('// --- OUTPUT PARAMETERS END ---')
    # A rule running a compiled Java engine has no script: srcContent ends by invoking the
    # engine, with no RULE CONTENT markers and no trailing newline (evidenced by RULE=ADD_FEE).
    engine = meta.get('engineClassName', ENGINE)
    if engine != ENGINE:
        L.append(f'new {engine}().run();')
        return '\n'.join(L)
    # The transactional banner sits after the LAST parameter block - after the outputs when
    # there are any, after the inputs when there are none - and costs an extra blank line
    # before the rule content (evidenced by RULE=WGT_SQL_QUERY, which has outputs, and
    # RULE=Add_New_Charge_Count, which has none).
    if str(meta.get('transactional', False)).lower() == 'true':
        L += ['// DB TRANSACTION BEGIN IF NEEDED: DUE TO RULE BEING MARKED TRANSACTIONAL', '']
    L += ['', '// --- RULE CONTENT START ---']
    # The scaffolding uses plain LF; the script keeps the CRLF the platform stores it with.
    # Its trailing newlines are DATA - the platform round-trips exactly what it holds, in both
    # directions. rstrip'ing them drops a &#xd; line per blank; ADDING one to a script that
    # ends without a newline (as this did until 09/03) inserts a &#xd; and a blank line that
    # the platform does not have - RULE=COPY_DISCOVERY_FROM_PREVIOUS_PRETRIAL, dupage-pd-aux
    # 05/21/2024, ends on `}` with no newline at all. Normalise nothing either way.
    L.append(crlf(script))
    L += ['// --- RULE CONTENT END ---', '']   # the script's own trailing CRLF is the blank line
    return '\n'.join(L)


def rule_def(meta, inputs, outputs, script):
    def params(rows, tag, with_lookup):
        out = []
        for i, p in enumerate(rows):
            out.append(f'    <com.sustain.rule.model.{tag}>')
            out.append(f"      <name>{esc(p['name'])}</name>")
            out.append(f"      <className>{p['className']}</className>")
            out.append(f"      <presetValue>{esc(p['presetValue'])}</presetValue>")
            out.append(f'      <pos>{i}</pos>')
            out.append('      <ruleDef reference="../../.."/>')
            out.append(f"      <type>{p['type']}</type>")
            if with_lookup:
                out.append(f"      <lookupListName>{esc(p['lookupListName'])}</lookupListName>")
            out.append(f'    </com.sustain.rule.model.{tag}>')
        return out

    L = ['<com.sustain.rule.model.RuleDef>',
         f"  <code>{esc(meta['code'])}</code>",
         f"  <name>{esc(meta['name'])}</name>",
         f"  <description>{esc(meta.get('description', ''))}</description>",
         f"  <category>{esc(meta.get('category', 'Reports'))}</category>",
         f"  <commitMessage>{esc(meta.get('commitMessage', ''))}</commitMessage>"]
    for flag in ('system', 'apiEnabled', 'caseEnabled', 'docEnabled', 'batchEnabled'):
        L.append(f"  <{flag}>{str(meta.get(flag, False)).lower()}</{flag}>")
    # An empty collection is written self-closing, not as an open/close pair (evidenced by
    # <outputs/> in RULE=Add_New_Charge_Count, elko-da-aux 07/11/2024).
    if inputs:
        L.append('  <inputs>')
        L += params(inputs, 'RuleInputParam', True)
        L.append('  </inputs>')
    else:
        L.append('  <inputs/>')
    if outputs:
        L.append('  <outputs>')
        L += params(outputs, 'RuleOutputParam', False)
        L.append('  </outputs>')
    else:
        L.append('  <outputs/>')
    L.append(f"  <engineClassName>{meta.get('engineClassName', ENGINE)}</engineClassName>")
    L.append(f"  <transactional>{str(meta.get('transactional', False)).lower()}</transactional>")
    # <script> is a nested doc, and its <content> is escaped one level deeper than the
    # tags around it - the whole RuleDef gets escaped again when it goes into the wrapper,
    # so a CR ends up as &amp;#xd; in the file. Emitting single-escaped Groovy here is the
    # subtlest way to produce a file that looks right and imports wrong.
    # A rule backed by a compiled Java engine has no <script> element at all - not an empty
    # one (evidenced by RULE=ADD_FEE, ocda-config 09/03/2026).
    if meta.get('engineClassName', ENGINE) == ENGINE:
        L.append('  <script>')
        L.append(f"    <code>{esc(meta['code'])}</code>")
        L.append('    <category>RULE</category>')
        L.append(f"    <language>{meta.get('language', 'groovy')}</language>")
        L.append(f"    <content>{esc(crlf(script))}</content>")
        L.append('  </script>')
    L.append('</com.sustain.rule.model.RuleDef>')
    return '\n'.join(L)


def wrapper(meta, inputs, outputs, script):
    sc = esc(src_content(inputs, outputs, script, meta))
    imp = esc(rule_def(meta, inputs, outputs, script))
    # srcActionUrl / srcHash / srcId MUST NOT be empty tags. PROVEN 2026-09-03 against
    # eh-team-config-symphony.logan-symphony.com: an export that is byte-valid in every other
    # respect but leaves these three empty is rejected with the single message
    # "error reading zip file" - HTTP 200, nothing logged server-side, and the message blames
    # the zip container even though the container is fine (a deliberately non-zip payload is
    # accepted with NO error at all, which is how the container was ruled out). Populating all
    # three made the identical file import as "<name> saved successfully."
    # Synthesised values are accepted - the importer does not check that the id or the hash
    # correspond to anything, and for a rule that was never exported from anywhere there is no
    # truthful value to give. Only non-emptiness is established; the exact values are not.
    action_url = meta.get('srcActionUrl') or (
        'https://%s/ecms/admin/rule/edit/onView?id=%s' % (
            meta.get('srcHost', 'generated.invalid'), meta.get('srcId') or '0'))
    src_hash = meta.get('srcHash') or hashlib.sha1(imp.encode('utf8')).hexdigest()[:8]
    src_id = str(meta.get('srcId') or '0')
    return ('<com.sustain.api.model.ConfigExportRsp>\n'
            f"  <srcActionUrl>{esc(action_url)}</srcActionUrl>\n"
            f'  <srcContent>{sc}</srcContent>\n'
            f'  <srcImportContent>{imp}</srcImportContent>\n'
            '  <srcRoot>RULE</srcRoot>\n'
            f"  <srcHash>{src_hash}</srcHash>\n"
            f"  <srcCode>{esc(meta['code'])}</srcCode>\n"
            f"  <srcId>{src_id}</srcId>\n"
            '</com.sustain.api.model.ConfigExportRsp>')


def write_zip(path, code, xml):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'RULE={code}.xml', xml)
    return path


def selftest(src):
    """Regenerate a real export from its own parsed parts and diff. Proves the writer."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import formexport
    for name, xml in formexport.members(src):
        m = formexport.meta(xml)
        r = formexport.ruledef(formexport.import_content(xml))
        meta = {'code': r['code'], 'name': r['name'], 'description': r['description'],
                'category': r['category'], 'commitMessage': '',
                'engineClassName': r['engineClassName'],
                'transactional': r['transactional'] == 'true',
                'srcActionUrl': m['srcActionUrl'], 'srcHash': m['srcHash'], 'srcId': m['srcId']}
        for f in ('system', 'apiEnabled', 'caseEnabled', 'docEnabled', 'batchEnabled'):
            meta[f] = r[f] == 'true'
        built = wrapper(meta, r['inputs'], r['outputs'], r['script'])
        a, b = xml.splitlines(), built.splitlines()
        if a == b:
            print(f"  {name}: IDENTICAL ({len(a)} lines) - writer reproduces the platform's output")
            return True
        print(f"  {name}: {sum(1 for _ in difflib.unified_diff(a, b))} diff lines")
        for ln in list(difflib.unified_diff(a, b, 'platform', 'generated', lineterm=''))[:24]:
            print('   ', ln[:150])
        return False


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--selftest')
    ap.add_argument('--groovy'); ap.add_argument('--code'); ap.add_argument('--name')
    ap.add_argument('--description', default=''); ap.add_argument('--category', default='Reports')
    ap.add_argument('--input', action='append', default=[])
    # NOT default=[...] - argparse APPENDS to a list default, which silently declares the
    # output twice and the rule then has two 'data' rows.
    ap.add_argument('--output', action='append')
    ap.add_argument('--transactional', action='store_true')
    ap.add_argument('--out')
    ap.add_argument('-h', '--help', action='store_true')
    a = ap.parse_args()
    if a.help or (not a.selftest and not a.groovy):
        print(__doc__); sys.exit(0 if a.help else 1)
    if a.selftest:
        sys.exit(0 if selftest(a.selftest) else 1)

    script = open(a.groovy, encoding='utf8').read()
    code = a.code or os.path.basename(a.groovy).split('.')[0]
    meta = {'code': code, 'name': a.name or code.replace('_', ' '),
            'description': a.description, 'category': a.category,
            'transactional': a.transactional}
    inputs = [parse_param(s) for s in a.input]
    outputs = [parse_param(s) for s in (a.output or ['data:java.util.List:REQUIRED'])]
    xml = wrapper(meta, inputs, outputs, script)
    out = a.out or f'RULE-{code}.zip'
    write_zip(out, code, xml)
    print(f"wrote {out}  ({os.path.getsize(out)} bytes)")
    print(f"  rule   {code}  category {a.category}  engine ScriptingRuleEngine")
    for p in inputs:
        print(f"  input  {p['name']:22} {p['className']:44} {p['type']}"
              + (f"  lookup={p['lookupListName']}" if p['lookupListName'] else ''))
    for p in outputs:
        print(f"  output {p['name']:22} {p['className']:44} {p['type']}")
    print("\n  IMPORTING IS A WRITE - hand this to the user; do not import it yourself.")


if __name__ == '__main__':
    main()
