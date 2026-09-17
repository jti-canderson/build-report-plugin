#!/usr/bin/env python3
"""
Write the importable RULE-<Code>.zip for a finished report. ALWAYS run this - a report is
not delivered without it. It is how a human loads the rule in one action instead of
retyping every parameter row into the editor, and it is the artifact that travels to
another environment.

    python3 rule_zip.py <rule>.groovy <report>.jrxml [--code CODE] [--name "Human Name"]
                        [--out DIR] [--url <srcActionUrl>]

The parameter rows are DERIVED, never hand-listed, because hand-listing is where a zip
silently stops matching the report it ships with.

  inputs   the jrxml's <parameter name="X"> that the rule actually reads as _X, in jrxml
           order, with the jrxml's own class="..." .
  output   data / java.util.List / REQUIRED, always. Omit it and the report renders a
           blank page while every screen reports success.

WHY NOT "parameters with a defaultValueExpression are self-supplied": that heuristic is
wrong and was caught here on 09/03. User_Logins_By_Role declares
<parameter name="Role" class="java.lang.String"><defaultValueExpression>""</defaultValueExpression>
- a default AND a launch input. Only journalLogo is genuinely self-supplied. Reading the
rule is the only way to tell the two apart.

Anything the rule reads that the jrxml never declares (or the reverse) is a CONTRACT fault:
this script reports it and exits 1 rather than shipping a zip that disagrees with the
layout. Fix the contract, do not fix the zip.

IMPORTING IS A WRITE. This writes a file; it never touches an environment.
"""
import sys, os, re, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'skills', 'report-deployment', 'scripts'))
import rule_import
import contract_docs

# journalLogo is the masthead image, supplied by the template's own defaultValueExpression.
# It is never a launch input and never appears on the rule.
SELF_SUPPLIED = {'journalLogo'}


def jrxml_params(path):
    """[(name, className)] in declaration order, minus the self-supplied ones."""
    xml = open(path, encoding='utf8').read()
    out = []
    for m in re.finditer(r'<parameter\s+name="([^"]+)"(?:\s+class="([^"]+)")?', xml):
        name, cls = m.group(1), m.group(2) or 'java.lang.String'
        if name not in SELF_SUPPLIED:
            out.append((name, cls))
    return out


def rule_reads(path):
    """The _Name parameters the rule actually reads. Comments stripped first - a _Name that
    only appears in the header comment block is documentation, not a parameter."""
    src = open(path, encoding='utf8').read()
    src = re.sub(r'/\*.*?\*/', ' ', src, flags=re.S)
    src = re.sub(r'//[^\n]*', ' ', src)
    # _data is the OUTPUT; it is declared separately and is not a launch input.
    return {n for n in re.findall(r'\b_([A-Za-z][A-Za-z0-9_]*)', src)} - {'data'}


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('groovy'); ap.add_argument('jrxml')
    ap.add_argument('--code'); ap.add_argument('--name'); ap.add_argument('--description', default='')
    ap.add_argument('--category', default='Reports')
    ap.add_argument('--url', default='')
    ap.add_argument('--out')
    ap.add_argument('--template', default='')
    ap.add_argument('-h', '--help', action='store_true')
    a = ap.parse_args()
    if a.help:
        print(__doc__); sys.exit(0)

    declared = jrxml_params(a.jrxml)
    read = rule_reads(a.groovy)
    names = {n for n, _ in declared}

    # The same two faults contract_check.py fails on. Checked again here because THIS is the
    # artifact that gets imported - a zip whose parameter rows disagree with the layout
    # produces a report that binds nothing, with no error anywhere.
    missing = sorted(read - names)          # rule reads it, jrxml never declares it
    unread = sorted(names - read)           # jrxml declares it, rule never reads it
    if missing or unread:
        for n in missing:
            print(f"  FAIL  rule reads _{n}, jrxml declares no parameter '{n}'")
        for n in unread:
            print(f"  FAIL  jrxml declares '{n}', rule never reads _{n}")
        print("\n  Contract fault - not writing a zip. Fix the rule or the jrxml.")
        sys.exit(1)

    inputs = [rule_import.parse_param(f'{n}:{c}') for n, c in declared]
    outputs = [rule_import.parse_param('data:java.util.List:REQUIRED')]

    code = a.code or os.path.basename(a.groovy).split('.')[0]
    meta = {'code': code, 'name': a.name or code.replace('_', ' '),
            'description': a.description, 'category': a.category,
            'transactional': False, 'srcActionUrl': a.url}
    xml = rule_import.wrapper(meta, inputs, outputs, open(a.groovy, encoding='utf8').read())

    out_dir = a.out or os.path.dirname(os.path.abspath(a.groovy))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f'RULE-{code}.zip')
    rule_import.write_zip(out, code, xml)

    print(f"wrote {out}  ({os.path.getsize(out)} bytes)")
    print(f"  rule   {code}  category {a.category}  engine ScriptingRuleEngine")
    for p in inputs:
        print(f"  input  {p['name']:22} {p['className']:24} {p['type']}")
    for p in outputs:
        print(f"  output {p['name']:22} {p['className']:24} {p['type']}")
    # The two text files are a restatement of the tables above, so they are written from the
    # same parse rather than retyped. Human notes in each survive regeneration - see
    # contract_docs.py; finish.sh re-runs this on every iteration.
    present = SELF_SUPPLIED & set(re.findall(r'<parameter\\s+name="([^"]+)"',
                                            open(a.jrxml, encoding='utf8').read()))
    reg, con = contract_docs.write(out_dir, meta, inputs, outputs, present, a.jrxml, a.template)
    for f in (reg, con):
        print(f"  wrote  {os.path.basename(f)}")
    print("\n  Fill the NOTES block in each - the generated part is the mechanical half only.")

    print("\n  IMPORTING IS A WRITE - hand this to the user; do not import it yourself.")
    print('  Send it with SendUserFile display:"attach" - it is a download, not a preview.')


if __name__ == '__main__':
    main()
