#!/usr/bin/env python3
"""precedents.py - pick ONE good precedent report instead of exploring several folders.

    precedents.py --root Case --template eseries_summary --financial
    precedents.py --root Case --params CaseId --sections OBLIGATIONS,PAYPLANS
    precedents.py --index                   # every report found, one line each

WHY: a build used to open report folders one by one looking for something similar - each a
tool call, each re-sending the conversation - and then read whole rules to judge. The facts
that decide "is this a good precedent" are few and all on disk: root entity, template,
parameters, sections, financial or not, environment, and what its handoff says went wrong.

HOW: every report folder under the workspace root (a folder holding a .jrxml and a .groovy)
is read afresh on each call - nothing is cached, so nothing goes stale. Candidates are scored
on the criteria given and the best few are printed with the reasons, the rule to open, and
the handoff's warnings. The rule itself is NOT printed: open the one you choose.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project as P                        # noqa: E402  - the workspace root, one definition

FIN = re.compile(r"\b(amount|balance|cents|receipt|payment|obligation|restitution|voucher|"
                 r"deposit|payPlan|payplan|invoice|assessment|disburse\w*|fee)\b", re.I)
SKIP_DIRS = {"jti-reports-plugin", "jti-report-deploy-plugin", "Presentation",
             "bin", "lib", "Entities", "verification", "Out", "reference", "sdk"}
# Archive folders hold superseded copies. A precedent is what to build ON, and copying from a
# version someone already replaced is how an old bug comes back.
ARCHIVE = re.compile(r"^(old|older versions|outdated versions|not used|archive|backup)\b", re.I)


def report_dirs(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")
                  and not ARCHIVE.match(d) and "(not mine)" not in d.lower()]
        if os.path.abspath(dp) == os.path.abspath(root):
            continue                  # the workspace root's loose files are not one report
        if any(f.endswith(".jrxml") for f in fns) and any(f.endswith(".groovy") for f in fns):
            yield dp


def read(p):
    try:
        return open(p, encoding="utf8", errors="ignore").read()
    except OSError:
        return ""


def describe(d):
    fns = os.listdir(d)
    jr = next((f for f in fns if f.endswith(".jrxml")), "")
    rules = [f for f in fns if f.endswith(".groovy") and not f.startswith(("Fixture", "Assert"))]
    rule = next((r for r in rules if re.search(r"_V\d+\.groovy$", r)), rules[0] if rules else "")
    rt, jt = read(os.path.join(d, rule)), read(os.path.join(d, jr))
    spec = {}
    if "spec.json" in fns:
        try:
            spec = json.loads(read(os.path.join(d, "spec.json")))
        except ValueError:
            spec = {}
    con = read(os.path.join(d, "JRXML_CONTRACT.txt"))
    hand = read(os.path.join(d, "HANDOFF.md"))
    reg = read(os.path.join(d, "RULE_REGISTRATION.txt"))
    tpl = spec.get("template") or (re.search(r"Template:\s*(\S+)", con) or [None, ""])[1] or \
        (re.search(r"^import (\w+) as T", read(os.path.join(d, "gen_jrxml.py")), re.M) or [None, ""])[1]
    # root entity: what the spec says, else the class the rule loads or searches
    root = spec.get("root") or ""
    if not root:
        m = re.search(r"\b([A-Z][A-Za-z]+)\.get\(", rt) or \
            re.search(r"DomainObject\.find\(\s*([A-Z][A-Za-z]+)(?:\.class)?", rt) or \
            re.search(r"\bfind\(\s*([A-Z][A-Za-z]+)\.class", rt)
        root = m.group(1) if m else ""
    params = sorted(set(re.findall(r'<parameter name="([^"]+)"', jt)) - {"journalLogo"})
    secs = [s.get("key", "") for s in spec.get("sections") or [] if isinstance(s, dict)]
    if not secs:
        secs = re.findall(r"^\s{4}([A-Z][A-Z_]{2,})\s{2,}", con, re.M)
    env = ""
    m = re.search(r"(?:built against|Environment:?)\s*([^\n.]{3,80})", reg + "\n" + hand, re.I)
    if m:
        env = m.group(1).strip()
    return_traps = warnings(hand, con, reg)
    return {"path": d, "name": os.path.basename(d), "rule": rule, "jrxml": jr,
            "template": tpl, "root": root, "params": params, "sections": secs[:8],
            "financial": len(FIN.findall(rt)) >= 5, "env": env,
            "harness": ("scaffold" if "render_check" in read(os.path.join(d, "verification", "run.sh"))
                        else "asset" if os.path.exists(os.path.join(d, "verification", "run.sh")) else "none"),
            "verified": any(f.endswith(".pdf") for f in os.listdir(os.path.join(d, "verification")))
                        if os.path.isdir(os.path.join(d, "verification")) else False,
            "traps": return_traps}


WARN_HEAD = re.compile(r"not (verified|proven)|open items|fragile|corrected guesses|traps?\b|"
                       r"do not re-introduce|unproven", re.I)


def warnings(*docs):
    """The lines a report's own handoff marks as unverified, fragile or wrong-before.

    Bullets under a warning heading (HANDOFF.md) or under a WHAT IS NOT PROVEN line (the
    NOTES blocks). Table rows and prose are skipped: a precedent's warnings should read as
    warnings, not as a random sentence that happened to contain "never"."""
    out = []
    for doc in docs:
        on = False
        for ln in doc.splitlines():
            st = ln.strip()
            if re.match(r"^#{1,4} ", st) or re.match(r"^[A-Z][A-Z ,/'-]{8,}(:|$| -)", st):
                on = bool(WARN_HEAD.search(st))
                continue
            if not st:
                continue
            if on and re.match(r"^([-*]|\d+\.)\s+", st) and not st.startswith("|"):
                t = re.sub(r"^([-*]|\d+\.)\s+", "", st).replace("**", "").replace("`", "")
                if len(t) > 15:
                    out.append(t)
    return list(dict.fromkeys(out))[:4]


def score(r, q):
    s, why = 0, []
    if q.root and r["root"].lower() == q.root.lower():
        s += 5; why.append(f"root {r['root']}")
    if q.template and r["template"] == q.template:
        s += 4; why.append(f"template {r['template']}")
    if q.financial is not None and r["financial"] == q.financial:
        s += 3; why.append("financial" if q.financial else "non-financial")
    for p in q.params:
        if any(p.lower() == x.lower() for x in r["params"]):
            s += 2; why.append(f"param {p}")
    for sec in q.sections:
        if any(sec.lower() == x.lower() for x in r["sections"]):
            s += 1; why.append(f"section {sec}")
    if q.env and q.env.lower() in r["env"].lower():
        s += 1; why.append("env")
    if s:
        # prefer a precedent that was actually verified with the current harness
        if r["harness"] == "scaffold":
            s += 1; why.append("scaffold harness")
        if r["verified"]:
            s += 1; why.append("rendered")
    return s, why


def line(r):
    return (f"  {r['name'][:34]:<34} root={r['root'] or '?':<14} tpl={r['template'] or '?':<16} "
            f"{'FIN ' if r['financial'] else '    '}params={','.join(r['params'])[:30]:<30} "
            f"harness={r['harness']}")


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--root"); ap.add_argument("--template"); ap.add_argument("--env")
    ap.add_argument("--financial", dest="financial", action="store_true", default=None)
    ap.add_argument("--non-financial", dest="financial", action="store_false")
    ap.add_argument("--params", default="")
    ap.add_argument("--sections", default="")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--index", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    q = ap.parse_args()
    q.params = [x for x in q.params.split(",") if x]
    q.sections = [x for x in q.sections.split(",") if x]
    asked = q.root or q.template or q.financial is not None or q.params or q.sections or q.env
    if q.help or not (asked or q.index):
        print(__doc__); return 0
    reps = [describe(d) for d in report_dirs(str(P.ROOT))]
    if q.index or not asked:
        print(f"{len(reps)} report(s) under {P.ROOT}")
        for r in sorted(reps, key=lambda r: r["name"]):
            print(line(r))
        return 0
    ranked = sorted(((score(r, q), r) for r in reps), key=lambda x: -x[0][0])
    ranked = [(s, r) for s, r in ranked if s[0] > 0][:q.limit]
    if not ranked:
        print("  NO PRECEDENT matches - this is a new shape here. Build from the template and")
        print("  model-facts; do not force a precedent that does not fit.")
        return 0
    print(f"  {len(reps)} reports scanned; best {len(ranked)}:\n")
    for (sc, why), r in ranked:
        print(f"  [{sc}] {r['name']}   ({', '.join(why)})")
        print(f"       open  {os.path.relpath(os.path.join(r['path'], r['rule']), str(P.ROOT))}")
        print(f"       shape root={r['root']} template={r['template']} params={r['params']} "
              f"sections={r['sections']}")
        if r["env"]:
            print(f"       env   {r['env']}")
        for t in r["traps"]:
            print(f"       note  {t[:150]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
