#!/usr/bin/env python3
"""
Diff a Groovy rule against its .jrxml. Run it before every deploy.

    python3 contract_check.py <rule>.groovy <report>.jrxml

Three ways a report goes wrong in silence, all of them a set difference:

  declared but not emitted   the column prints blank, and nothing errors
  emitted but not declared   the rule computed data the page throws away. A WARNING
                             only: key detection is heuristic, so an ordinary local
                             variable can land here.
  declared but not placed    dead weight - usually a leftover from an older cut

and a fourth, which breaks the deploy rather than the page:

  parameter mismatch         the registration binds parameters by name; a rule that
                             reads _StartDate against a jrxml declaring StartDate2
                             fails at run time, not at build time

Exits 1 if the first two, or the parameter check, fail. Dead weight is reported but
does not fail - it is untidy, not broken.
"""
import pathlib
import re
import sys


def check(rule_path, jrxml_path):
    rule = pathlib.Path(rule_path).read_text()
    jr = pathlib.Path(jrxml_path).read_text()

    # Keys the rule puts into a row map. The corpus does this three ways and a
    # checker that knows only one of them reports every field as blank:
    #   map.put("k", v)        the older reports
    #   [ k : "", ... ]        a seeded base map literal
    #   m.k = v                filling a row in place
    emits = set(re.findall(r'\.put\(\s*"([A-Za-z0-9_]+)"', rule))
    # a map key sits at a line start, or straight after '[' or ',' - anywhere on the
    # line, because a rule may open the literal mid-expression: `rows << [ section : ...`
    emits |= set(re.findall(r'(?:^|[\[,])\s*([A-Za-z][A-Za-z0-9_]*)\s*:', rule, re.M))
    emits |= set(re.findall(r'\b[a-z]\w*\.([A-Za-z][A-Za-z0-9_]*)\s*=[^=]', rule))
    # _Foo in the rule is <parameter name="Foo"> in the jrxml. Underscore-lowercase
    # names (_data, _startDate) are matched too - the corpus is inconsistent about case.
    reads = {m for m in re.findall(r'\b_([A-Za-z][A-Za-z0-9_]*)\b', rule)
             if m != "data"}
    decl = set(re.findall(r'<field name="([^"]+)"', jr))
    placed = set(re.findall(r'\$F\{([A-Za-z0-9_]+)\}', jr))
    prm = set(re.findall(r'<parameter name="([^"]+)"', jr)) - {"journalLogo"}

    blank = sorted(decl - emits)
    lost = sorted(emits - decl)
    dead = sorted(decl - placed)
    # compare case-insensitively: the rule may read _CollectingAgency or _collectingAgency
    pmiss = sorted({p for p in prm if p.lower() not in {r.lower() for r in reads}})
    pextra = sorted({r for r in reads if r.lower() not in {p.lower() for p in prm}})

    print(f"rule    {pathlib.Path(rule_path).name}")
    print(f"jrxml   {pathlib.Path(jrxml_path).name}")
    print(f"        {len(emits)} keys emitted, {len(decl)} fields declared, "
          f"{len(placed)} placed, {len(prm)} parameters")
    ok = True
    for lbl, items, fatal in (
            ("declared but NOT emitted (prints blank)", blank, True),
            ("emitted but NOT declared (data discarded, or just a local)", lost, False),
            ("parameters in jrxml the rule never reads", pmiss, True),
            ("parameters the rule reads, absent from jrxml", pextra, True),
            ("declared but NOT placed on the page (dead weight)", dead, False)):
        if items:
            print(f"  {'FAIL' if fatal else 'warn'}  {lbl}: {items}")
            ok = ok and not fatal
    if ok and not (blank or lost or dead or pmiss or pextra):
        print("  OK    contract is exact on all three axes")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__.strip())
        sys.exit(2)
    sys.exit(check(sys.argv[1], sys.argv[2]))
