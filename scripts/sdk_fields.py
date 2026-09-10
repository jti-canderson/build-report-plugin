#!/usr/bin/env python3
"""
Answer MANY field questions about one SDK class in ONE javap call.

    sdk_fields.py com.sustain.cases.model.Case caseType filingDate statuses ...
    sdk_fields.py --jar path/to/sdk.jar Case caseType ...        # short class name works
    sdk_fields.py --list Case                                    # every field on the chain

Inherited members COUNT: the whole `extends` chain is walked and the `declared on` column
says where each one lives. javap prints declared members only, so asking javap about Case
alone reports its inherited getters as absent.

WHY: javap dumps the WHOLE class, so asking about one name and asking about twenty cost the
same ~2.3s of JVM startup. Asking one at a time turned twenty field questions into twenty
turns, each paying a full context prefill for an answer javap had already printed.

WHAT EACH VERDICT MEANS - and the third column is the one that misleads people:

  field      a declared instance field. This is what a Where can filter on.
  getter     a public accessor exists.
  body       field-backed  -> the getter returns the stored field (aload/getfield)
             stripped      -> the getter compiles to aconst_null/areturn

  *** A STRIPPED BODY IS NOT A DEAD GETTER. *** The SDK export empties the body of every
  DERIVED getter: 253 of 379 getters on Case are stripped, getCaseTypeLabel() among them,
  and that one demonstrably works in production. Stripped means "not a stored field",
  which is exactly what a derived getter is. It establishes only that the property cannot
  go in a Where. To conclude a getter is genuinely dead you need a SECOND source - the
  Data Dictionary's derived-getter block, an empty class, or absence from the whole corpus.
  See skills/jasper-reports/references/model-facts.md.
"""
import argparse
import os
import re
import subprocess
import sys
import glob

JRS = os.environ.get("JRS", "/Applications/jasperreports-server-9.0.0")
JAVAP = os.path.join(JRS, "java", "bin", "javap")


def find_jar(explicit):
    if explicit:
        return explicit
    # A project keeps its jar in <project>/sdk/. Newest wins - an SDK is per-environment
    # and per-date, and a stale one answers confidently about a model that has moved.
    cands = sorted(glob.glob("sdk/*.jar") + glob.glob("*/sdk/*.jar")
                   + glob.glob("../sdk/*.jar"), key=os.path.getmtime, reverse=True)
    return cands[0] if cands else None


def resolve_class(jar, name):
    """A short name like 'Case' -> its fully qualified name, by looking in the jar."""
    if "." in name:
        return name
    try:
        import zipfile
        with zipfile.ZipFile(jar) as z:
            hits = [n[:-6].replace("/", ".") for n in z.namelist()
                    if n.endswith(f"/{name}.class")]
    except Exception:
        return name
    if not hits:
        return name
    if len(hits) > 1:
        # Never guess between packages - the package varies by area and picking the wrong
        # one answers a confident question about a different entity.
        print(f"  '{name}' is ambiguous. Pass one:")
        for h in sorted(hits):
            print(f"    {h}")
        sys.exit(2)
    return hits[0]


def dump(jar, cls):
    if not os.path.exists(JAVAP):
        sys.exit(f"no javap at {JAVAP} - set JRS to your JasperReports Server install")
    r = subprocess.run([JAVAP, "-p", "-c", "-classpath", jar, cls],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(f"javap could not read {cls} from {os.path.basename(jar)}")
    return r.stdout


def superclass(out):
    m = re.search(r'^\S.*\bclass\s+[\w.$]+\s+extends\s+([\w.$]+)', out, re.M)
    return m.group(1) if m else None


def parse(out):
    fields, getters = {}, {}
    cur, body = None, []
    for line in out.splitlines():
        m = re.match(r'\s+(?:private|public|protected)?\s*(?:static\s+)?(?:final\s+)?'
                     r'([\w.$<>\[\], ?]+?)\s+(\w+);\s*$', line)
        if m and "(" not in line:
            fields[m.group(2)] = m.group(1).strip()
            continue
        g = re.match(r'\s+public\s+([\w.$<>\[\], ?]+?)\s+(get|is)(\w+)\(\);\s*$', line)
        if g:
            if cur:
                getters[cur] = "stripped" if any("aconst_null" in b for b in body[:2]) \
                    else "field-backed"
            prop = g.group(3)
            cur = prop[0].lower() + prop[1:]
            body = []
            continue
        if cur and line.strip().startswith(("0:", "1:", "2:")):
            body.append(line)
    if cur:
        getters[cur] = "stripped" if any("aconst_null" in b for b in body[:2]) \
            else "field-backed"
    return fields, getters


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cls", nargs="?")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--jar")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help or not a.cls:
        print(__doc__)
        sys.exit(0 if a.help else 2)

    jar = find_jar(a.jar)
    if not jar:
        sys.exit("no SDK jar found - pass --jar, or register one with project.py sdk-register")
    cls = resolve_class(jar, a.cls)

    # Walk UP the chain. javap prints declared members only, so Case's inherited
    # getDateCreated() (declared on DomainObject) reads as absent when you ask about Case.
    # Answering "no getter" about an inherited member is a confidently wrong answer.
    # Field owner and getter owner are tracked SEPARATELY. They differ constantly -
    # Case declares the caseType field while getCaseType() lives on CaseComponent - and
    # collapsing them into one "declared on" column reports one of the two wrongly.
    fields, getters, fowner, gowner = {}, {}, {}, {}
    cur, chain = cls, []
    while cur and cur != "java.lang.Object" and len(chain) < 12:
        try:
            out = dump(jar, cur)
        except SystemExit:
            break
        chain.append(cur)
        f, g = parse(out)
        for k, v in f.items():
            if k not in fields:
                fields[k] = v; fowner[k] = cur
        for k, v in g.items():
            if k not in getters:
                getters[k] = v; gowner[k] = cur
        cur = superclass(out)

    print(f"  {cls}")
    print(f"  jar   {os.path.basename(jar)}")
    print(f"  chain {' <- '.join(chain)}\n")

    if a.list:
        for n in sorted(fields):
            print(f"  {n:32} {short(fowner, n):22} {fields[n]}")
        print(f"\n  {len(fields)} declared field(s), {len(getters)} getter(s)")
        return

    stripped = sum(1 for v in getters.values() if v == "stripped")
    def short(d, n):
        return d.get(n, "").rsplit(".", 1)[-1]

    print(f"  {'name':24} {'field on':16} {'getter on':16} {'body':13} type")
    print(f"  {'-'*24} {'-'*16} {'-'*16} {'-'*13} ----")
    missing = []
    for n in a.names:
        f = fields.get(n)
        g = getters.get(n)
        if not f and not g:
            missing.append(n)
        print(f"  {n:24} {(short(fowner, n) or '-'):16} "
              f"{(short(gowner, n) or '-'):16} {(g or '-'):13} {f or ''}")

    print(f"\n  A stripped body means NOT A STORED FIELD, not a dead getter - {stripped} of "
          f"{len(getters)} getters across this chain are stripped.\n"
          f"  It rules the property out of a Where. It does NOT rule out reading it.\n"
          f"  Corroborate with the Data Dictionary or the corpus before calling one dead.")
    if missing:
        print(f"\n  NOT ON THIS CLASS AT ALL: {', '.join(missing)}")
        print("  Groovy will still compile `obj.thatName` and hand you null at run time.")
        sys.exit(1)


if __name__ == "__main__":
    main()
