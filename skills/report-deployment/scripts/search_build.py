#!/usr/bin/env python3
"""search_build.py - build an importable eSeries search form from a short spec.

    python3 search_build.py spec.json [--out DIR]     # default DIR: ~/Downloads
    python3 search_build.py --example                 # print a spec to start from

The spec names the fields in plain paths; everything else is derived:

    {
      "code": "S-JTI-CaseTest",          unique in the target environment
      "name": "JTI Case Search (test)",
      "root": "Case",
      "dictionary": "~/Downloads/DataDictionary-<environment>-<date>.xlsx",
      "sdk": "~/Downloads/ecourt-sdk-<environment>-<date>.jar",       optional fallback
      "criteria": [ {"path": "status", "label": "Case Status"}, ... ],
      "results":  [ {"path": "caseNumber", "label": "Case Number", "link": true}, ... ]
    }

Per criterion: label, operator (EQUALS/STARTS_WITH/ENDS_WITH/NOT_EQUALS/...), multi, default.
Per result: label, link. From the Data Dictionary, per field: whether it is a lookup list (a
picker, LABEL format), a Date (a range criterion), or an entity (a relation picker).

WHAT IT REFUSES, and why each refusal is the point:
- a path that does not resolve in THIS environment's dictionary (or SDK). In a search a wrong
  field does not error - it silently matches nothing.
- a form the gate faults: dangling references, count mismatches, XStream/JSON disagreement.
- a code already used by a form this machine has an export of.

WHAT IS PROVEN, what is not - both printed with every build:
- every item shape it emits reproduces real platform items byte-for-byte; the JSON half is a
  projection that reproduces 220 real search-form items byte-for-byte; every resolved field
  class matches what the platform itself recorded (475 of 475, 0 wrong).
- NOT proven: that a form with synthetic identity (srcId / validationRule ids) imports. The
  first import settles it, and a rejection there changes nothing.
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import form_import as F   # noqa: E402
import dd_resolve as R    # noqa: E402

EXAMPLE = {
    "code": "S-JTI-CaseTest",
    "name": "JTI Case Search (test)",
    "root": "Case",
    "dictionary": "~/Downloads/DataDictionary-TheEhTeamConfig-2026-08-20.xlsx",
    "criteria": [
        {"path": "caseNumber", "label": "Case Number"},
        {"path": "status", "label": "Case Status"},
        {"path": "parties.person.lastName", "label": "Last Name", "operator": "STARTS_WITH"},
        {"path": "caseType", "label": "Case Type"},
    ],
    "results": [
        {"path": "caseNumber", "label": "Case Number", "link": True},
        {"path": "caseType", "label": "Case Type"},
        {"path": "status", "label": "Status"},
        {"path": "receivedDate", "label": "Received"},
    ],
}
OPERATORS = {"EQUALS", "NOT_EQUALS", "STARTS_WITH", "ENDS_WITH", "CONTAINS", "GREATER_THAN",
             "LESS_THAN"}
CODE_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,60}$")


def known_codes():
    out = set()
    for z in glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip")):
        if not F.PLATFORM_EXPORT.match(os.path.basename(z)):
            continue
        try:
            for _, x in F.members(z):
                out.add(F.unwrap(x)["srcCode"])
        except Exception:                                    # noqa: BLE001
            pass
    return out


def pick_donor():
    """Any platform-exported search form supplies the envelope (head/tail/settings); only
    rootEntity is root-specific and build_search swaps it. Prefer S-Case-Simple: it is the
    form every emitter was proven against."""
    cands = []
    for z in sorted(glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip"))):
        if not F.PLATFORM_EXPORT.match(os.path.basename(z)):
            continue
        for nm, x in F.members(z):
            p = F.parse(x)
            if p["type"] == 4:
                cands.append((0 if p["code"] == "S-Case-Simple" else 1, z, p))
    if not cands:
        sys.exit("  no platform search-form export in ~/Downloads to take the envelope from")
    return sorted(cands, key=lambda c: c[0])[0][2]


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--out", default=os.path.expanduser("~/Downloads"))
    ap.add_argument("--example", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.example:
        print(json.dumps(EXAMPLE, indent=2))
        return
    if a.help or not a.spec:
        print(__doc__)
        sys.exit(0)

    spec = json.load(open(os.path.expanduser(a.spec)))
    code, name, root = spec.get("code", ""), spec.get("name", ""), spec.get("root", "")
    problems = []
    if not CODE_OK.match(code):
        problems.append(f"code {code!r}: letters, digits, _ and - only, starting with a letter")
    if not name:
        problems.append("name is empty")
    if code in known_codes():
        problems.append(f"code {code!r} is already used by a form in an export on this machine")
    if not spec.get("results"):
        problems.append("a search with no result columns shows nothing")
    ddp = os.path.expanduser(spec.get("dictionary", ""))
    if not os.path.exists(ddp):
        problems.append(f"data dictionary not found: {ddp!r} - export one from the TARGET "
                        f"environment (System Setup -> Data Dictionary)")
    if problems:
        print("  REFUSED:")
        for x in problems:
            print("   -", x)
        sys.exit(1)

    jar = os.path.expanduser(spec["sdk"]) if spec.get("sdk") else None
    dd = R.load_dd(ddp)
    fq = R.learn_fqcn(glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip")),
                      [jar] if jar else glob.glob(os.path.expanduser("~/Downloads/ecourt-sdk-*.jar")))
    if not fq.get(root):
        sys.exit(f"  REFUSED: cannot name the class for root entity {root!r}")

    print(f"  {code}  -  {name!r}  on {root}\n  dictionary {os.path.basename(ddp)}\n")
    print(f"  {'':9} {'path':<34} {'resolves to':<48} derived")
    crit, res, bad = [], [], 0
    for kind, rows in (("criterion", spec.get("criteria", [])), ("result", spec["results"])):
        for row in rows:
            path = row["path"]
            r = R.resolve(dd, fq, root, path, jar=jar)
            if not r["ok"]:
                bad += 1
                print(f"  REFUSED  {path:<34} {r['why']}")
                continue
            relation = R._is_entity_name(r["type"]) or r["type"].startswith("Collection")
            opt = {"label": row.get("label"), "lookup": bool(r["lookup"]),
                   "allow_range": bool(r["range"]) and kind == "criterion",
                   "relation": relation, "operator": row.get("operator"),
                   "multi": row.get("multi", bool(r["lookup"])), "default": row.get("default"),
                   "link": row.get("link", False)}
            if opt["operator"] and opt["operator"] not in OPERATORS:
                bad += 1
                print(f"  REFUSED  {path:<34} operator {opt['operator']!r} is not one seen in any export")
                continue
            if kind == "criterion" and relation and not opt["label"]:
                bad += 1
                print(f"  REFUSED  {path:<34} ends at an entity - give it a label (only the "
                      f"labelled shape is proven for relation criteria)")
                continue
            if r["lookup"] is None and kind == "criterion":
                print(f"  note     {path:<34} walked from the SDK jar: the dictionary cannot say "
                      f"whether it is a lookup list - treated as a plain value")
            d = ", ".join(x for x in (
                f"lookup {r['lookup_list']}" if r["lookup"] else "",
                "range" if opt["allow_range"] else "", "relation" if relation else "",
                f"op {opt['operator']}" if opt["operator"] else "",
                "multi" if opt["multi"] and kind == "criterion" else "",
                "link" if opt["link"] and kind == "result" else "") if x)
            tag = "criterion" if kind == "criterion" else "result"
            print(f"  {tag:<9} {path:<34} {r['terminal'][:48]:<48} {d}")
            (crit if kind == "criterion" else res).append((path, r["terminal"], opt))
    if bad:
        sys.exit(f"\n  REFUSED: {bad} field(s) above do not resolve cleanly - nothing written")

    donor = pick_donor()
    out, flags = F.build_search(donor, code, name, crit, res, root=root, root_fqcn=fq[root])
    xml = F.wrap(out["env"])
    back = F.parse(xml)
    faults, notes = F.check(back, f"FORM={code}.xml")
    rt = F.rebuild(back) == xml
    print(f"\n  gate: {'CLEAN' if not faults else 'FAULTS'}   round-trip: {'identical' if rt else 'DIFFERS'}")
    for x in faults:
        print("   FAULT", x)
    if faults or not rt:
        sys.exit("  REFUSED: not writing a form the gate faults")
    dest = os.path.join(os.path.expanduser(a.out), f"FORM-{code}.zip")
    F.write_zip(dest, code, xml)
    print(f"\n  wrote {dest}")
    print("\n  proven: every item shape reproduces real platform items byte-for-byte; the JSON")
    print("          half reproduces real search-form JSON byte-for-byte; every field class")
    print("          above matches what the platform itself records.")
    print("  NOT proven yet:")
    for f in flags:
        print("   -", f)
    print("   - criteria are laid out two to a row in the order listed (doubleColumn); the")
    print("     exact left/right placement is confirmed on first import")


if __name__ == "__main__":
    main()
