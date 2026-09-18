#!/usr/bin/env python3
"""
The regression suite. One command, non-zero on any failure.

    python3 tests/run.py [-v]

WHY IT EXISTS: every defect in this plugin so far was found by hand, and two of them were
regressions I introduced - a scaffold that silently stopped calling rulecheck (so a rule
producing no output shipped and failed on first use), and a page that hand-copied a filter
and immediately disagreed with the original. A gate that can quietly disappear is not a
guarantee. These tests make a missing gate fail the same day.

HOW IT WORKS: a known-good report is built in a temp workspace, then each negative test
copies it, breaks ONE thing, and asserts the RIGHT gate rejects it. A test that fails
because the fixture drifted would fail the baseline first, so the signal stays readable.

Tests needing JasperReports SKIP loudly when it is absent. A skip is not a pass.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
VERBOSE = "-v" in sys.argv

JRS = os.environ.get("JRS") or next(
    (p for p in sorted(__import__("glob").glob("/Applications/jasperreports-server-*"))
     if os.path.isdir(os.path.join(p, "java", "bin"))), None)

results = []


def run(cmd, cwd=None, env=None):
    e = dict(os.environ, JTI_PLUGIN=PLUGIN)
    if env:
        e.update(env)
    p = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, shell=isinstance(cmd, str))
    return p.returncode, p.stdout + p.stderr


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok and detail:
        for line in str(detail).strip().splitlines()[:8]:
            print(f"        {line}")
    elif VERBOSE and detail:
        for line in str(detail).strip().splitlines()[:5]:
            print(f"        {line}")


def skip(name, why):
    results.append((name, None, why))
    print(f"  SKIP  {name}  ({why})")


def build_good(ws):
    """Scaffold the probe report and fill it in. Returns its folder."""
    proj = os.path.join(ws, "Probe Project")
    os.makedirs(proj, exist_ok=True)
    spec = os.path.join(proj, "spec.json")
    shutil.copy(os.path.join(FIX, "good_spec.json"), spec)
    rc, out = run(["python3", os.path.join(PLUGIN, "scripts", "scaffold.py"), spec,
                   "--out", os.path.join(proj, "Probe_Report")])
    if rc != 0:
        return None, out
    folder = os.path.join(proj, "Probe_Report")
    shutil.copy(os.path.join(FIX, "good_rule.groovy"),
                os.path.join(folder, "Probe_Report_V1.groovy"))
    # Replace the scaffold's TODO rows with real ones.
    fx = os.path.join(folder, "verification", "fixture.py")
    t = open(fx).read()
    t = re.sub(r'ROWS = \[\n.*?\n\]',
               'ROWS = [\n    ("CF-2026-00184", "Felony"),\n    ("CM-2026-01920", "Misdemeanor"),\n]',
               t, flags=re.S)
    t = t.replace('"rptTitle": "Probe Report",', '"rptTitle": "Probe Report",')
    t = re.sub(r'"(rptSubtitle|rptSlug)": "TODO [^"]*"',
               lambda m: f'"{m.group(1)}": "probe"', t)
    open(fx, "w").write(t)
    return folder, ""


def gates(folder, *extra):
    return run([os.path.join(PLUGIN, "scripts", "finish.sh"),
                "Probe_Report_V1.groovy", "Probe_Report.jrxml",
                "--code", "Probe_Report", "--name", "Probe Report", *extra], cwd=folder)


def mutate(src, ws, tag, fn):
    """A copy of the good report with one thing broken."""
    dst = os.path.join(ws, "broken_" + tag)
    shutil.copytree(src, dst)
    fn(dst)
    return dst


def rule(f):    return os.path.join(f, "Probe_Report_V1.groovy")
def gen(f):     return os.path.join(f, "gen_jrxml.py")
def fixture(f): return os.path.join(f, "verification", "fixture.py")


def edit(path, old, new, count=1):
    t = open(path).read()
    assert old in t, f"fixture drifted: {old!r} not in {os.path.basename(path)}"
    open(path, "w").write(t.replace(old, new, count))


def main():
    print("\n  jti-reports regression suite")
    print(f"  plugin {PLUGIN}")
    print(f"  jasper {JRS or 'NOT FOUND - render and rule-execution tests will skip'}\n")

    ws = tempfile.mkdtemp(prefix="jti-tests-")
    open(os.path.join(ws, ".jti-root"), "w").close()

    # ---- 0. the baseline. Nothing below means anything if this fails. ----------
    good, err = build_good(ws)
    if good is None:
        check("baseline: scaffold builds the probe report", False, err)
        return report()
    check("baseline: scaffold builds the probe report", True)

    if JRS:
        rc, out = gates(good)
        check("baseline: the good report passes every gate", rc == 0, out)
        if rc != 0:
            return report()
    else:
        rc, out = run(["python3", os.path.join(PLUGIN, "templates", "contract_check.py"),
                       rule(good), os.path.join(good, "Probe_Report.jrxml")])
        check("baseline: the good report passes the contract gate", rc == 0, out)

    # ---- negative: each breaks ONE thing and must be caught ---------------------
    b = mutate(good, ws, "nodata", lambda f: edit(rule(f), "_data = rows", "data = rows"))
    rc, out = run(["python3", os.path.join(PLUGIN, "templates", "contract_check.py"),
                   rule(b), os.path.join(b, "Probe_Report.jrxml")])
    check("a rule that never assigns _data is rejected",
          rc != 0 and "never assigns _data" in out, out)

    b = mutate(good, ws, "param", lambda f: edit(rule(f), "_CaseType", "_NotDeclared", 2))
    rc, out = run(["python3", os.path.join(PLUGIN, "templates", "contract_check.py"),
                   rule(b), os.path.join(b, "Probe_Report.jrxml")])
    check("a parameter the jrxml never declares is rejected", rc != 0, out)

    b = mutate(good, ws, "zip", lambda f: edit(rule(f), "_CaseType", "_NotDeclared", 2))
    rc, out = run(["python3", os.path.join(PLUGIN, "scripts", "rule_zip.py"),
                   rule(b), os.path.join(b, "Probe_Report.jrxml"), "--code", "X"], cwd=b)
    check("rule_zip refuses to write a zip on a contract fault",
          rc != 0 and not os.path.exists(os.path.join(b, "RULE-X.zip")), out)

    # jti_style generate-time guards
    probe = ("import sys; sys.path.insert(0, %r); import jti_style as S; "
             % os.path.join(PLUGIN, "templates"))
    rc, out = run(["python3", "-c", probe + "S.static(0,0,100,12,'done \\u2713')"])
    check("a non-WinAnsi glyph is refused at generate time",
          rc != 0 and "WinAnsi" in out, out)
    rc, out = run(["python3", "-c", probe + "S.text(0,0,100,8,'$F{x}', size=14)"])
    check("text too small to print is refused at generate time",
          rc != 0 and "print blank" in out, out)
    rc, out = run(["python3", "-c", probe +
                   "S.parse_cols([('A Very Long Column Header Indeed', 5, 'Left', 'a')]) "
                   "and S.label(0,0,20,12,'A Very Long Column Header Indeed')"])
    check("a column header too wide for its column is refused",
          rc != 0 and "clipped" in out, out)

    # scaffold refuses a template it cannot parameterise
    sp = os.path.join(ws, "bad_tpl.json")
    s = json.load(open(os.path.join(FIX, "good_spec.json")))
    s["template"] = "grouped_summary"
    json.dump(s, open(sp, "w"))
    rc, out = run(["python3", os.path.join(PLUGIN, "scripts", "scaffold.py"), sp,
                   "--out", os.path.join(ws, "nope")])
    check("scaffold refuses a template that cannot be parameterised",
          rc != 0 and "cannot be parameterised" in out, out)

    # a "match a picture" spec: no template, a reference image beside it. scaffold must say
    # WHY rather than "missing 'template'", and the builder must have copied the picture in.
    sp = os.path.join(ws, "look.json")
    s = json.load(open(os.path.join(FIX, "good_spec.json")))
    s["template"] = ""
    s["look_like"] = "reference/screenshot.png"
    json.dump(s, open(sp, "w"))
    rc, out = run(["python3", os.path.join(PLUGIN, "scripts", "scaffold.py"), sp,
                   "--out", os.path.join(ws, "nope2")])
    check("scaffold refuses a match-a-picture spec and names build-report",
          rc != 0 and "build-report" in out and "missing" not in out, out)

    # the upload round trip, in-process: a PNG is accepted, a text file is not, and writing
    # the spec COPIES the picture into the report folder instead of leaving a temp path.
    look_probe = """
import json, os, sys
sys.path.insert(0, %r)
import serve_builder as B
png = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b'0' * 64
bad = B.keep_look(b'this is not a picture at all', 'notes.txt')
good = B.keep_look(png, 'my screen shot.PNG')
ok, msg = B.write_spec({'name': 'Look_Probe', 'project': 'Probe Project',
                        'template': '', 'look': good['token'],
                        'sections': [{'key': 'ROWS', 'title': 'Rows',
                                      'cols': [['A', 20, 'Left', 'a']]}]})
folder = os.path.join(os.environ['JTI_PROJECT_ROOT'], 'Probe Project', 'Look_Probe')
spec = json.load(open(os.path.join(folder, 'spec.json')))
notpl, why = B.write_spec({'name': 'No_Tpl', 'project': 'Probe Project', 'template': '',
                           'sections': [{'key': 'R', 'title': 'R',
                                         'cols': [['A', 20, 'Left', 'a']]}]})
print(json.dumps({'badRejected': not bad['ok'], 'goodOk': good.get('ok'),
                  'name': good.get('name'), 'wrote': ok,
                  'lookLike': spec.get('look_like'),
                  'copied': os.path.exists(os.path.join(folder, spec.get('look_like') or 'x')),
                  'refusedNoTemplate': not notpl, 'why': why}))
""" % os.path.join(PLUGIN, "scripts")
    rc, out = run(["python3", "-c", look_probe], env={"JTI_PROJECT_ROOT": ws})
    try:
        d = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        d = {}
    check("an uploaded example layout is sniffed, named and copied into the report folder",
          rc == 0 and d.get("badRejected") and d.get("goodOk")
          and d.get("name") == "my_screen_shot.png" and d.get("wrote")
          and d.get("lookLike") == "reference/my_screen_shot.png" and d.get("copied"), out)
    check("a spec with neither a template nor a picture is refused",
          bool(d.get("refusedNoTemplate")) and "picture" in (d.get("why") or ""), out)

    # the two listings that disagreed twice
    rc, out = run(["python3", "-c",
                   "import sys; sys.path.insert(0, %r); import project as P; "
                   "print([p['label'] for p in P.list_projects()])" %
                   os.path.join(PLUGIN, "scripts")], env={"JTI_PROJECT_ROOT": ws})
    rc2, out2 = run(["python3", os.path.join(PLUGIN, "scripts", "project.py"), "list"],
                    env={"JTI_PROJECT_ROOT": ws})
    names = re.findall(r"'([^']+)'", out)
    check("project listing and list_projects() agree",
          rc == 0 and rc2 == 0 and all(n.split("  ")[0] in out2 for n in names),
          out + out2)

    # the RULE writer still reproduces the platform byte for byte
    exports = [p for p in (os.path.expanduser("~/Downloads/RULE-local-2026-08-21.zip"),
                           os.path.expanduser("~/Downloads/RULE-local-2026-09-03.zip"))
               if os.path.exists(p)]
    if exports:
        ok, detail = True, ""
        for z in exports:
            rc, out = run(["python3", os.path.join(
                PLUGIN, "skills", "report-deployment", "scripts", "rule_import.py"),
                "--selftest", z])
            if "IDENTICAL" not in out:
                ok, detail = False, out
        check(f"rule_import reproduces {len(exports)} platform export(s) byte for byte",
              ok, detail)
    else:
        skip("rule_import reproduces the platform exports", "no RULE-local-*.zip on hand")

    # formexport --spec feeds the builder's upload. It must emit JSON and NOTHING else -
    # a stray banner line makes json.loads() throw, which is how the RULE case first failed.
    fe = os.path.join(PLUGIN, "skills", "jasper-reports", "scripts", "formexport.py")
    import glob as _glob
    forms = sorted(_glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip")))
    rules = sorted(_glob.glob(os.path.expanduser("~/Downloads/RULE-*.zip")))
    # Use the first export that actually CONTAINS a folder view, not whichever sorts
    # first. ~/Downloads holds FORM archives with no panels at all, so blindly taking
    # forms[0] made this test pass or fail depending on what was in the folder - a test
    # that is non-deterministic is worse than no test.
    usable = None
    for f in forms:
        rc, out = run(["python3", fe, f, "--spec"])
        try:
            _d = json.loads(out) if rc == 0 else []
            if _d and _d[0].get("panels"):
                usable, first_out = f, out
                break
        except ValueError:
            continue
    if usable:
        rc, out = 0, first_out
        ok, detail = False, out
        try:
            d = json.loads(out)
            ok = rc == 0 and isinstance(d, list) and d and d[0].get("panels")
            # field names must be unique across the WHOLE form - the jrxml declares one
            # flat list, so a `status` in two panels would collide into one field.
            names = [c["field"] for f in d for pn in f["panels"] for c in pn["columns"]]
            ok = ok and len(names) == len(set(names))
            detail = f"{len(names)} columns, {len(set(names))} distinct field names"
        except ValueError as e:
            detail = f"not JSON: {e}\n{out[:200]}"
        check(f"formexport --spec: parseable JSON, unique field names "
              f"({os.path.basename(usable)})", ok, detail)
    else:
        skip("formexport --spec emits parseable JSON",
             "no FORM-*.zip on hand that contains a folder view")

    if rules:
        rc, out = run(["python3", fe, rules[0], "--spec"])
        try:
            ok = json.loads(out) == []
        except ValueError:
            ok = False
        check("formexport --spec returns an empty list for a non-folder-view export",
              ok, out[:200])
    else:
        skip("formexport --spec on a non-folder-view export", "no RULE-*.zip on hand")

    # ---- the ones that need a JVM ---------------------------------------------
    if not JRS:
        for n in ("a rule that does not compile is rejected",
                  "a GString value is rejected",
                  "a truncated value is rejected",
                  "a failed render is not reported as success"):
            skip(n, "no JasperReports install")
        return report()

    b = mutate(good, ws, "nocompile",
               lambda f: edit(rule(f), "def w = new Where()", "def w = new Nonexistent()"))
    rc, out = gates(b)
    check("a rule that does not compile is rejected",
          rc != 0 and ("unable to resolve" in out or "GATE 1.5" in out), out)

    b = mutate(good, ws, "gstring",
               lambda f: edit(rule(f), 'rptSlug: "probe"', 'rptSlug: "${1 + 1} rows"'))
    rc, out = gates(b)
    check("a GString value is rejected", rc != 0 and "String" in out, out)

    # >85 characters: that column is 60% of a 572pt page, which holds roughly 85 at 8pt.
    # The first version of this test used 62 and failed - correctly, because nothing was
    # truncated. A negative test that does not actually break anything proves nothing.
    b = mutate(good, ws, "clip", lambda f: edit(
        fixture(f), '("CF-2026-00184", "Felony")',
        '("CF-2026-00184", "A Case Type Whose Label Runs On And On Well Past The Width Of Any '
        'Column That Could Reasonably Hold It")'))
    rc, out = gates(b)
    check("a value truncated by its column is rejected",
          rc != 0 and "TRUNCATED" in out, out)

    # the swallowed-exit-code bug: render fails, run.sh must NOT report success
    b = mutate(good, ws, "renderfail",
               lambda f: edit(fixture(f), '"caseType"', '"caseTypeXX"'))
    rc, out = run(["./verification/run.sh", "render", "full"], cwd=b)
    check("a failed render is not reported as success",
          rc != 0 and "CONTRACT FAIL" in out, out)

    return report()


def report():
    p = sum(1 for _, ok, _ in results if ok is True)
    f = sum(1 for _, ok, _ in results if ok is False)
    s = sum(1 for _, ok, _ in results if ok is None)
    print(f"\n  {p} passed, {f} failed, {s} skipped\n")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
