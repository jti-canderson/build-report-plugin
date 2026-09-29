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

TWO TIERS, counted separately:
  core         self-contained and deterministic: everything it reads is in tests/fixtures or
               is built in a temp workspace (including a fake SDK jar). Needs only the local
               JasperReports install.
  integration  reads private material that is NOT in this repo - platform FORM/RULE exports
               and data dictionaries in ~/Downloads, the newest SDK jar registered in the real
               workspace. Skips when it is absent; what it proves depends on what is there.

Both tiers need the local TOOLS: JasperReports (its JDK too) and PyMuPDF.

    python3 tests/run.py --core-only   HOME is pointed at an empty temp dir first, so no
                                       integration input can be reached, and those tests are
                                       reported as not run
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
CORE_ONLY = "--core-only" in sys.argv
if CORE_ONLY:
    # Nothing under the real home is reachable - ~/Downloads included - so a core test that
    # quietly depended on private material fails here instead of passing by luck.
    _home = tempfile.mkdtemp(prefix="jti-nohome-")
    # The ONE thing a scaffolded report reaches through HOME: gen_jrxml.py and run.sh load
    # the templates from ~/JaspersoftWorkspace/MyReports/jti-reports-plugin. Point that at
    # the plugin under test, explicitly, and nothing else.
    os.makedirs(os.path.join(_home, "JaspersoftWorkspace", "MyReports"))
    os.symlink(PLUGIN, os.path.join(_home, "JaspersoftWorkspace", "MyReports", "jti-reports-plugin"))
    # Tools, not data: keep the user's Python packages (PyMuPDF lives in the per-user
    # site-packages, which is found through HOME) - without it the render gate fails.
    import site as _site
    os.environ.setdefault("PYTHONUSERBASE", _site.getuserbase())
    os.environ["HOME"] = _home
TIER = "core"


def tier(name):
    global TIER
    TIER = name

JRS = os.environ.get("JRS") or next(
    (p for p in sorted(__import__("glob").glob("/Applications/jasperreports-server-*"))
     if os.path.isdir(os.path.join(p, "java", "bin"))), None)

results = []

sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.path.insert(0, HERE)
import build_mode  # noqa: E402
SWITCHES = build_mode.resolve()[0]


def run(cmd, cwd=None, env=None):
    e = dict(os.environ, JTI_PLUGIN=PLUGIN)
    if env:
        e.update(env)
    p = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, shell=isinstance(cmd, str))
    return p.returncode, p.stdout + p.stderr


def check(name, ok, detail=""):
    results.append((name, ok, detail, TIER))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok and detail:
        for line in str(detail).strip().splitlines()[:8]:
            print(f"        {line}")
    elif VERBOSE and detail:
        for line in str(detail).strip().splitlines()[:5]:
            print(f"        {line}")


def skip(name, why):
    if TIER == "integration" and CORE_ONLY:
        why = "not run: --core-only"
    results.append((name, None, why, TIER))
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

        # PERF RECORD (phase 1). The instrumentation must MEASURE and never change an
        # outcome: a passing run records every stage; a failing run records WHERE it failed
        # and still exits non-zero with the same "GATE n FAILED" message as before.
        pj = os.path.join(good, "verification", "perf.jsonl")
        last = json.loads(open(pj).read().strip().splitlines()[-1]) if os.path.exists(pj) else {}
        # The suite runs with either verifier (JTI_VERIFIER=fast python3 tests/run.py
        # proves the fast path against every gate test below); each one names its stages.
        mode = SWITCHES["verifier"]
        want = {"regenerate", "contract", "rule", "render", "truncation", "package", "verdict"}
        if mode == "fast":
            want |= {"fixtures", "jvm_startup", "raster"}
        check(f"finish.sh records a perf line with every stage on a passing run ({mode})",
              last.get("ok") is True and want <= set(last.get("stages") or {})
              and last.get("mode") == mode, json.dumps(last)[:300])
        bf = mutate(good, ws, "perf_fail", lambda f: edit(rule(f), "_data = rows", "data = rows"))
        rc_f, out_f = gates(bf)
        lf = json.loads(open(os.path.join(bf, "verification", "perf.jsonl")).read()
                        .strip().splitlines()[-1])
        check("a failing gate run still exits 1, says GATE 1 FAILED, and records the stage",
              rc_f == 1 and "GATE 1 FAILED" in out_f and lf.get("failed_stage") == "contract"
              and lf.get("ok") is False, f"rc={rc_f} rec={lf}")
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

    # BRIEF-ONLY. A template plus a plain-English brief and NO typed columns must be accepted
    # (Claude derives the columns downstream, as the chat interview does), a template with
    # neither columns nor a brief must be refused, and scaffold must refuse the brief-only
    # spec with a message that names build-report rather than "missing 'sections'".
    brief_probe = """
import json, os, sys, subprocess
sys.path.insert(0, %r)
import serve_builder as B
brief = B.write_spec({'name': 'Brief_Ok', 'project': 'Probe Project',
                      'template': 'tabular_list', 'intent': 'every case in a date range',
                      'sections': []})
empty = B.write_spec({'name': 'Empty_No', 'project': 'Probe Project',
                      'template': 'tabular_list', 'intent': '', 'sections': []})
folder = os.path.join(os.environ['JTI_PROJECT_ROOT'], 'Probe Project', 'Brief_Ok')
spec = json.load(open(os.path.join(folder, 'spec.json')))
sc = subprocess.run([sys.executable, os.path.join(%r, 'scaffold.py'),
                     os.path.join(folder, 'spec.json'), '--out', os.path.join(folder, 'x')],
                    capture_output=True, text=True)
print(json.dumps({'briefAccepted': brief[0], 'intentKept': bool(spec.get('intent')),
                  'noSections': spec.get('sections') == [],
                  'emptyRefused': not empty[0], 'emptyWhy': empty[1],
                  'scaffoldRefused': sc.returncode != 0,
                  'scaffoldNamesBuildReport': 'build-report' in (sc.stdout + sc.stderr)}))
""" % (os.path.join(PLUGIN, "scripts"), os.path.join(PLUGIN, "scripts"))
    rc, out = run(["python3", "-c", brief_probe], env={"JTI_PROJECT_ROOT": ws})
    try:
        b = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        b = {}
    check("a brief-only spec (template + words, no typed columns) is accepted and keeps intent",
          rc == 0 and b.get("briefAccepted") and b.get("intentKept") and b.get("noSections"), out)
    check("a spec with a template but nothing said about the page is refused",
          bool(b.get("emptyRefused")) and "page" in (b.get("emptyWhy") or ""), out)
    check("scaffold refuses a brief-only spec and names build-report (not 'missing sections')",
          bool(b.get("scaffoldRefused")) and bool(b.get("scaffoldNamesBuildReport")), out)

    # THE LISTENER. Two things have to hold or the Write button lies to the user: a spec
    # written while Claude is parked must reach it, and the "Claude is watching" flag must
    # go FALSE when the client hangs up. The second one was broken on 09/18 - curl's
    # --max-time kills the client, not the server thread, so the count stayed up forever
    # and the page said "Claude has picked this up" to nobody.
    import socket as _socket
    import urllib.request as _u
    with _socket.socket() as _s:
        _s.bind(("127.0.0.1", 0))
        port = _s.getsockname()[1]
    srv = subprocess.Popen(
        ["python3", os.path.join(PLUGIN, "scripts", "serve_builder.py"),
         "--port", str(port), "--no-open"],
        env=dict(os.environ, JTI_PROJECT_ROOT=ws, JTI_PLUGIN=PLUGIN),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"

    def api(path, body=None):
        req = _u.Request(base + path, data=body, method="POST" if body else "GET")
        with _u.urlopen(req, timeout=20) as r:
            return json.load(r)

    try:
        for _ in range(50):                      # wait for the port to answer
            try:
                api("/api/watching"); break
            except Exception:
                __import__("time").sleep(0.2)

        idle = api("/api/watching")
        # Park a waiter, then ABANDON it - the client goes away without the server being told
        holder = subprocess.Popen(
            ["curl", "-s", "--max-time", "3", f"{base}/api/wait?since=0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        __import__("time").sleep(1.5)
        parked = api("/api/watching")
        holder.wait(timeout=15)
        __import__("time").sleep(2.5)
        released = api("/api/watching")

        # and the happy path: parked, a spec is written, the waiter gets it
        holder2 = subprocess.Popen(
            ["curl", "-s", "--max-time", "25", f"{base}/api/wait?since=0"],
            stdout=subprocess.PIPE, text=True)
        __import__("time").sleep(1.5)
        wrote = api("/api/spec", json.dumps({
            "name": "Listener_Probe", "project": "Probe Project",
            "template": "record_summary",
            "sections": [{"key": "ROWS", "title": "Rows",
                          "cols": [["A", 20, "Left", "a"]]}]}).encode())
        delivered = json.loads((holder2.communicate(timeout=30)[0] or "{}").strip() or "{}")
    finally:
        srv.terminate()

    check("the Write button reaches a waiting Claude",
          parked.get("watching") and wrote.get("watched")
          and delivered.get("spec", "").endswith("Listener_Probe/spec.json"),
          f"parked={parked} wrote={wrote} delivered={delivered}")
    check("a Claude that hung up stops counting as watching",
          not idle.get("watching") and not released.get("watching"),
          f"idle={idle} released={released}")

    # ======== INTEGRATION: platform FORM exports in ~/Downloads ========
    tier("integration")
    # FORM exports. A search form cannot be corrected in place after import - it has to be
    # deleted and re-uploaded - so the writer's only acceptable proof is byte equality against
    # exports the platform itself produced. These tests are that proof, plus one negative to
    # show the gate actually rejects something.
    fi = os.path.join(PLUGIN, "skills", "report-deployment", "scripts", "form_import.py")
    import glob as _g2
    form_zips = sorted(_g2.glob(os.path.expanduser("~/Downloads/FORM-*.zip")))
    if form_zips:
        rc, out = run(["python3", fi, "--selftest-all", os.path.expanduser("~/Downloads")])
        m = re.search(r"(\d+) platform export\(s\) reproduced byte-for-byte, (\d+) failed", out)
        check(f"form_import reproduces every FORM export byte-for-byte "
              f"({m.group(1) if m else '?'} platform exports)",
              rc == 0 and m is not None and m.group(2) == "0", out[-800:])

        # the gate must be clean on the platform's own output - a gate that fires on a valid
        # file is a gate people learn to ignore
        clean = True
        detail = ""
        for z in form_zips:
            rc, out = run(["python3", fi, "--check", z])
            if rc != 0:
                clean, detail = False, f"{os.path.basename(z)}\n{out}"
                break
        check("the form gate passes every platform export", clean, detail)

        # rename touches exactly the fields it claims and no items
        src = next((z for z in form_zips if "2026-09-21.zip" in z), form_zips[0])
        dst = os.path.join(ws, "renamed.zip")
        rc, out = run(["python3", fi, "--copy", src, "--code", "S-Probe-Renamed",
                       "--name", "Probe Renamed", "--rehash", "--out", dst])
        ok = rc == 0 and os.path.exists(dst)
        if ok:
            rc2, d = run(["python3", fi, "--diff", src, dst])
            ok = rc2 == 0 and "Nothing else moved" in d and "item text differs" not in d
            detail = d
        check("renaming a form changes the code everywhere and the items nowhere", ok, detail)

        # NEGATIVE: an empty srcHash must be caught. This is the fault that gets reported as
        # "error reading zip file", which blames the container and sends you looking in the
        # wrong place entirely.
        import zipfile as _zf
        broken = os.path.join(ws, "broken.zip")
        with _zf.ZipFile(src) as zin:
            nm = [n for n in zin.namelist() if n.endswith(".xml")][0]
            xml = zin.read(nm).decode("utf8")
        xml = re.sub(r"<srcHash>.*?</srcHash>", "<srcHash></srcHash>", xml, flags=re.S)
        with _zf.ZipFile(broken, "w") as zout:
            zout.writestr(nm, xml)
        rc, out = run(["python3", fi, "--check", broken])
        check("the form gate rejects an empty srcHash",
              rc != 0 and "srcHash" in out and "error reading zip file" in out, out)
    else:
        for n in ("form_import reproduces every FORM export byte-for-byte",
                  "the form gate passes every platform export",
                  "renaming a form changes the code everywhere and the items nowhere",
                  "the form gate rejects an empty srcHash"):
            skip(n, "no FORM-*.zip in ~/Downloads")

    # FROM-SCRATCH item synthesis. The proof that /build-search can emit items for paths no
    # export contains: re-synthesise real CLEAN (no-configSourceId) items from their semantics
    # alone and require byte equality. If the emitter drifts, this count drops.
    if form_zips:
        probe = """
import sys, re, glob, os
sys.path.insert(0, %r)
import form_import as F
def fid(it):
    m=re.search(r'<com\\.sustain\\.form\\.model\\.FormItem>\\s*<default>',it); s=m.end(); d=1
    for mm in re.finditer(r'</?default>',it[s:]):
        d+=1 if mm.group(0)=='<default>' else -1
        if d==0: return it[s:s+mm.start()]
CRIT={"grid","hidden","link","noHoliday","noWeekend","num","readonly","required","type","associatedForm","carryOver","conditionalFormats","conditions","existingEntityConditions","filterConditions","lookupItemFormat","multiSelectLookup","newColumn","newRow","operator","panelAutoCompleteMinChars","parameters","path","showIfValues","showIfValues2","userSelectedList","widgetInMassType","xrefConditions"}
RES=CRIT|{"autoFillNullValue","carryOverWhenRepeated","displayInactive","dropdown","exactMatchToCode","existingSelectAll","fillPanelOnSelect","filterListByUser","forceDefaultValue","freeFormLookup","inPlaceEditable","includeNulls","innerJoin","label","labelIsTemplate","lookupDefaultValues","noLabel","onlyAutoFillEmptyField","openInNewTab","panelAutoCompleteWithAllData","preventPanelLookups","previewSummary","readonlyIfEmpty","readonlyIfNotEmpty","repeatPanelsOnPanelLookup","requiredTime","runLookup","showIfNullValueWhenHidden","useCommaDisplayMask"}
c_ok=r_ok=0
for z in glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip")):
    if not F.PLATFORM_EXPORT.match(os.path.basename(z)): continue
    for nm,x in F.members(z):
        for it in F.parse(x)["items"]:
            if F.is_ref(it): continue
            sm=F.item_summary(it); b=fid(it) or ""
            if "<configSourceId>" in it or sm["nested"]: continue
            term=re.search(r'<string>(.*?)</string>',it)
            if not term: continue
            if sm["kind"]=="criterion" and not (set(re.findall(r'<(\\w+)',b))-CRIT):
                op=re.search(r'<operator>(.*?)</operator>',b)
                got=F.synth_criterion(sm["num"],sm["path"],term.group(1),lookup="<lookupItemFormat>" in b,operator=op.group(1) if op else None,allow_range="<allowRange>true</allowRange>" in it)
                c_ok+= got==it
            if sm["kind"]=="result" and not (set(re.findall(r'<(\\w+)',b))-RES) and re.search(r'<displayRowTotals>false.*?<hqlExpression></hqlExpression>',it,re.S) and "<aggregateFunction>" not in it and "<compoundCriteriaField>" not in it:
                lab=re.search(r'<label>(.*?)</label>',b)
                got=F.synth_result(sm["num"],sm["path"],term.group(1),lab.group(1) if lab else None,link="<link>true</link>" in b,lookup="<lookupItemFormat>" in b)
                r_ok+= got==it
# and build_search produces a gate-clean, round-tripping form
(nm,x),=F.members(sorted(glob.glob(os.path.expanduser("~/Downloads/FORM-*2026-09-21.zip")))[0])[:1]
d=F.parse(x)
built,flags=F.build_search(d,"S-Probe-Scratch","Probe",[("caseNumber","com.sustain.cases.model.Case.caseNumber",{})],[("caseName","com.sustain.cases.model.Case.caseName",{"link":True,"label":None})])
xml=F.wrap(built["env"]); back=F.parse(xml); faults,_=F.check(back,"FORM=S-Probe-Scratch.xml")
rt = F.rebuild(back)==xml
print("SCRATCH", c_ok, r_ok, len(faults), rt)
""" % os.path.join(PLUGIN, "skills", "report-deployment", "scripts")
        rc, out = run(["python3", "-c", probe])
        m = re.search(r"SCRATCH (\d+) (\d+) (\d+) (\w+)", out)
        check("from-scratch item synthesis reproduces real clean items byte-for-byte "
              f"({m.group(1) if m else '?'} criteria, {m.group(2) if m else '?'} results)",
              bool(m) and int(m.group(1)) >= 11 and int(m.group(2)) >= 6, out[-600:])
        check("build_search assembles a gate-clean, round-tripping from-scratch form",
              bool(m) and m.group(3) == "0" and m.group(4) == "True", out[-600:])
    else:
        skip("from-scratch item synthesis byte-equality", "no FORM-*.zip in ~/Downloads")
        skip("build_search assembles a gate-clean from-scratch form", "no FORM-*.zip in ~/Downloads")

    # THE 2026-09-22 REVIEW. Each of these is a bug that shipped in a file in ~/Downloads, or
    # a check that would have caught it. A test per failure, so none of them comes back.
    if form_zips:
        review = """
import sys, re, json, glob, os, zipfile
sys.path.insert(0, %r)
import form_import as F
src = sorted(glob.glob(os.path.expanduser("~/Downloads/FORM-*2026-09-21.zip")))[0]
(nm, x), = F.members(src)[:1]
donor = F.parse(x)
# 1. compose(donor -> itself) must BE the platform file, both halves, reference entry included
crit = [sm["path"] for sm in donor["summaries"] if sm["kind"] == "criterion"]
o = F.compose(donor, crit, donor["code"], donor["name"]); F.reproject_json(o)
o["env"]["srcImportContent"] = o["head"] + "".join(a+b for a,b in zip(o["seps"], o["items"])) + o["seps"][-1] + o["tail"]
ident = F.wrap(o["env"]) == x
# 2. the gate has ZERO false faults on the platform's own exports
false = 0
for z in glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip")):
    if not F.PLATFORM_EXPORT.match(os.path.basename(z)): continue
    for n2, x2 in F.members(z):
        false += bool(F.check(F.parse(x2), n2)[0])
# 3. the gate CATCHES a JSON half that disagrees (the S-Case-Quick bug): swap two entries
j = json.loads(donor["env"]["srcContent"]); j["formItems"][2], j["formItems"][7] = j["formItems"][7], j["formItems"][2]
bad = x.replace(F.esc(donor["env"]["srcContent"]), F.esc(json.dumps(j, indent=2, ensure_ascii=False)))
caught_json = any("disagree" in f for f in F.check(F.parse(bad), nm)[0])
# 4. the gate CATCHES a dangling reference (the S-Case-Scratch bug): drop the OR parent
imp = donor["env"]["srcImportContent"]
env2 = dict(donor["env"])
env2["srcImportContent"] = imp.replace('reference="../com.sustain.form.model.SearchCriteriaFormItem/',
                                       'reference="../com.sustain.form.model.SearchCriteriaFormItem[99]/', 1)
assert env2["srcImportContent"] != imp
caught_ref = any("dangling" in f for f in F.check(F.parse(F.wrap(env2)), nm)[0])
# 5. the projection reproduces search-form JSON byte-for-byte (keys, order, values)
proj_ok = proj_bad = 0
for z in glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip")):
    if not F.PLATFORM_EXPORT.match(os.path.basename(z)): continue
    for n2, x2 in F.members(z):
        p2 = F.parse(x2)
        if p2["type"] != 4: continue
        for it, jj in zip(p2["items"], p2["cfg"]["formItems"]):
            if F.is_ref(it) or "reference=" in re.sub(r'<(associatedForm|formItem|additionalItemTo)\\s+reference="[^"]*"\\s*/>', "", it): continue
            if json.dumps(F.project(it)) == json.dumps(jj): proj_ok += 1
            else: proj_bad += 1
print("REVIEW", ident, false, caught_json, caught_ref, proj_ok, proj_bad)
""" % os.path.join(PLUGIN, "skills", "report-deployment", "scripts")
        rc, out = run(["python3", "-c", review])
        m = re.search(r"REVIEW (\w+) (\d+) (\w+) (\w+) (\d+) (\d+)", out)
        g = m.groups() if m else ("?",) * 6
        check("compose(donor -> itself) reproduces the platform file byte-for-byte",
              g[0] == "True", out[-500:])
        check("the form gate has zero false faults on every platform export", g[1] == "0", out[-500:])
        check("the form gate catches a JSON half that disagrees with the XStream",
              g[2] == "True", out[-500:])
        check("the form gate catches a dangling XStream reference", g[3] == "True", out[-500:])
        check(f"srcContent projection is byte-identical on search-form items ({g[4]} items)",
              g[4] not in ("?", "0") and g[5] == "0", out[-500:])
    else:
        for t in ("compose(donor -> itself) reproduces the platform file byte-for-byte",
                  "the form gate has zero false faults on every platform export",
                  "the form gate catches a JSON half that disagrees with the XStream",
                  "the form gate catches a dangling XStream reference",
                  "srcContent projection is byte-identical on search-form items"):
            skip(t, "no FORM-*.zip in ~/Downloads")

    tier("core")
    # usage.py counts each API response ONCE. Claude Code writes every content block of a
    # response as its own transcript line carrying the SAME usage, so a per-line sum doubled
    # every cost figure the plugin reported, until 2026-09-22.
    u = {"input_tokens": 10, "cache_creation_input_tokens": 0,
         "cache_read_input_tokens": 1000, "output_tokens": 100}
    fake = [json.dumps({"type": "assistant", "message": {"id": "msg_A", "usage": u,
                        "content": [{"type": "thinking", "thinking": "x"}]}}),
            json.dumps({"type": "assistant", "message": {"id": "msg_A", "usage": u,
                        "content": [{"type": "text", "text": "y"}]}}),
            json.dumps({"type": "assistant", "message": {"id": "msg_A", "usage": u,
                        "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}),
            json.dumps({"type": "assistant", "message": {"id": "msg_B", "usage": u,
                        "content": [{"type": "text", "text": "z"}]}}),
            json.dumps({"type": "assistant", "message": {"usage": u, "content": []}})]
    probe_u = ("import sys, json; sys.path.insert(0, %r); import usage as U; "
               "L = json.loads(sys.argv[1]); t, raw, by, n, e = U.scan(L); "
               "print(json.dumps({'turns': n, 'out': raw['output_tokens'], "
               "'bash': 'Bash' in by}))" % os.path.join(PLUGIN, "scripts"))
    rc, out = run(["python3", "-c", probe_u, json.dumps(fake)])
    try:
        du = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        du = {}
    # msg_A (3 lines) + msg_B (1) + one id-less line = 3 responses, 300 output tokens,
    # and msg_A's tool call must still be attributed even though it was its third line.
    check("usage.py counts one API response once, not once per content-block line",
          rc == 0 and du.get("turns") == 3 and du.get("out") == 300 and du.get("bash"), out)

    # ======== INTEGRATION: data dictionaries + FORM exports in ~/Downloads ========
    tier("integration")
    # /build-search, end to end: the resolver never names a wrong class, refuses what does not
    # exist in THIS environment, and the builder writes a gate-clean form or nothing at all.
    sb_dir = os.path.join(PLUGIN, "skills", "report-deployment", "scripts")
    dd_eh = os.path.expanduser("~/Downloads/DataDictionary-TheEhTeamConfig-2026-08-20.xlsx")
    dd_ok = os.path.expanduser("~/Downloads/DataDictionary-local-2026-09-02.xlsx")
    if form_zips and os.path.exists(dd_ok):
        probe = """
import sys, glob, os, re
sys.path.insert(0, %r)
import dd_resolve as R, form_import as F
fq = R.learn_fqcn(glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip")), glob.glob(os.path.expanduser("~/Downloads/ecourt-sdk-*.jar")))
jar = next(iter(sorted(glob.glob(os.path.expanduser("~/Downloads/ecourt-sdk-local-*.jar")))), None)
dd = R.load_dd(%r)
same = wrong = refused = 0
for z in glob.glob(os.path.expanduser("~/Downloads/FORM-local-*.zip")):
    if not F.PLATFORM_EXPORT.match(os.path.basename(z)): continue
    for nm, x in F.members(z):
        p = F.parse(x)
        for it in p["items"]:
            if F.is_ref(it): continue
            sm = F.item_summary(it); terms = re.findall(r"<string>(com\\.sustain\\.[\\w.]+)</string>", it)
            if not sm["path"] or not terms or sm["type"] == "7": continue
            r = R.resolve(dd, fq, p["root_json"], sm["path"], jar=jar)
            if not r["ok"]: refused += 1
            elif r["terminal"] == terms[0]: same += 1
            else: wrong += 1
typo = R.resolve(dd, fq, "Case", "parties.person.lastNmae", jar=jar)["ok"]
print("RESOLVE", same, wrong, refused, typo)
""" % (sb_dir, dd_ok)
        rc, out = run(["python3", "-c", probe])
        m = re.search(r"RESOLVE (\d+) (\d+) (\d+) (\w+)", out)
        check(f"the field resolver names the platform's own class for every path "
              f"({m.group(1) if m else '?'} identical, {m.group(2) if m else '?'} wrong)",
              bool(m) and int(m.group(1)) > 100 and m.group(2) == "0", out[-500:])
        check("the field resolver refuses a misspelt field",
              bool(m) and m.group(4) == "False", out[-500:])
    else:
        skip("the field resolver names the platform's own class for every path", "no OKDAC dictionary")
        skip("the field resolver refuses a misspelt field", "no OKDAC dictionary")

    if form_zips and os.path.exists(dd_eh):
        sb = os.path.join(sb_dir, "search_build.py")
        rc, ex = run(["python3", sb, "--example"])
        spec = json.loads(ex)
        spec["code"] = "S-Probe-Built"
        sp = os.path.join(ws, "search_spec.json"); json.dump(spec, open(sp, "w"))
        outdir = os.path.join(ws, "search_out"); os.makedirs(outdir, exist_ok=True)
        rc, out = run(["python3", sb, sp, "--out", outdir])
        built = os.path.join(outdir, "FORM-S-Probe-Built.zip")
        check("search_build writes a gate-clean, round-tripping form from a spec",
              rc == 0 and os.path.exists(built) and "gate: CLEAN" in out
              and "round-trip: identical" in out, out[-700:])
        # a form from another environment's field must be refused - and nothing written
        spec["code"] = "S-Probe-Refused"
        spec["results"].append({"path": "cf_courtNum"})     # OKDAC custom field, not in Eh Team
        sp2 = os.path.join(ws, "search_spec_bad.json"); json.dump(spec, open(sp2, "w"))
        rc, out = run(["python3", sb, sp2, "--out", outdir])
        check("search_build refuses a field that does not exist in the target environment",
              rc != 0 and "REFUSED" in out and not os.path.exists(os.path.join(outdir, "FORM-S-Probe-Refused.zip")),
              out[-500:])
    else:
        skip("search_build writes a gate-clean form from a spec", "no Eh Team dictionary")
        skip("search_build refuses a field from another environment", "no Eh Team dictionary")

    tier("core")
    # ---- phase 3: no pause for a current SDK - decided in code ---------------------
    # sdk-decide exits 0 only for a current AND readable SDK; anything the user would have to
    # fix (none, gone, stale, unreadable) exits 10 so the build asks. Each case is built here.
    import zipfile as _zfd
    pd = os.path.join(ws, "SDK Probe")
    os.makedirs(pd, exist_ok=True)
    jar = os.path.join(ws, "ecourt-sdk-probe.jar")
    with _zfd.ZipFile(jar, "w") as z:
        z.writestr("com/sustain/cases/model/Case.class", b"\xca\xfe\xba\xbe")
    proj = os.path.join(PLUGIN, "scripts", "project.py")
    penv = {"JTI_PROJECT_ROOT": ws}
    rc0, o0 = run(["python3", proj, "sdk-decide", pd], env=penv)
    run(["python3", proj, "sdk-register", pd, jar], env=penv)
    rc1, o1 = run(["python3", proj, "sdk-decide", pd], env=penv)
    meta_p = os.path.join(pd, ".jti-project.json")
    meta = json.load(open(meta_p))
    meta["sdk"]["registered"] = "2025-01-01"
    json.dump(meta, open(meta_p, "w"))
    rc2, o2 = run(["python3", proj, "sdk-decide", pd], env=penv)
    meta["sdk"]["registered"] = __import__("datetime").date.today().isoformat()
    json.dump(meta, open(meta_p, "w"))
    open(os.path.join(pd, meta["sdk"]["stored"]), "wb").write(b"<html>404 Not Found</html>")
    rc3, o3 = run(["python3", proj, "sdk-decide", pd], env=penv)
    check("sdk-decide: current readable SDK -> no question (exit 0, one SDK line)",
          rc1 == 0 and o1.startswith("SDK ") and "used without asking" in o1, o1)
    check("sdk-decide asks when the SDK is missing, stale, or unreadable (exit 10)",
          rc0 == 10 and rc2 == 10 and "days old" in o2 and rc3 == 10 and "cannot be read" in o3,
          f"none={rc0} stale={rc2} {o2.strip()} unreadable={rc3} {o3.strip()}")
    cmd_md = open(os.path.join(PLUGIN, "commands", "build-report.md"), encoding="utf8").read()
    check("build-report: unattended decides the SDK in code, confirm keeps its confirmation",
          "sdk-decide" in cmd_md and "INTERACTION: unattended" in cmd_md and '"derived"' in cmd_md
          and "**Still current** / **I'll send a newer one**" in cmd_md
          and "**`interaction: confirm`:** confirm the derived columns" in cmd_md
          and "scripts/build_mode.py" in cmd_md, "command text")

    # ---- rollout switches: each independent, the old variable only an alias -------------
    bm = build_mode.resolve
    a = bm({"JTI_REPORT_BUILD_MODE": "fast"})
    check("JTI_REPORT_BUILD_MODE=fast enables verifier+interaction+lookup, NOT the build plan, "
          "and says so", a[0] == {"verifier": "fast", "interaction": "unattended",
                                  "lookup": "targeted", "build_plan": "off"}
          and any("build plan stays OFF" in n for n in a[2]), a)
    v = bm({"JTI_VERIFIER": "fast"})[0]
    i = bm({"JTI_INTERACTION": "unattended"})[0]
    check("the fast verifier and unattended sdk-decide can each be enabled alone",
          v == {"verifier": "fast", "interaction": "confirm", "lookup": "full", "build_plan": "off"}
          and i == {"verifier": "legacy", "interaction": "unattended", "lookup": "full",
                    "build_plan": "off"}, f"{v} {i}")
    o = bm({"JTI_REPORT_BUILD_MODE": "fast", "JTI_VERIFIER": "legacy", "JTI_BUILD_PLAN": "opt-in"})
    check("an explicit switch overrides the alias; the plan needs its own opt-in",
          o[0]["verifier"] == "legacy" and o[0]["build_plan"] == "opt-in"
          and o[1]["verifier"] == "JTI_VERIFIER" and o[1]["interaction"] == "JTI_REPORT_BUILD_MODE", o)
    d = bm({})
    bad = bm({"JTI_VERIFIER": "fsat", "JTI_BUILD_PLAN": "on"})
    check("defaults are the pre-optimisation behaviour; a misspelt value warns and uses it",
          d[0] == {"verifier": "legacy", "interaction": "confirm", "lookup": "full",
                   "build_plan": "off"}
          and bad[0] == d[0] and len(bad[2]) == 2, bad)

    # ---- phase 4: targeted knowledge retrieval --------------------------------------
    facts = os.path.join(PLUGIN, "scripts", "facts.py")
    mf_path = os.path.join(PLUGIN, "skills", "jasper-reports", "references", "model-facts.md")
    mf = open(mf_path, encoding="utf8").read()
    rc, out = run(["python3", facts, "--entity", "PayPlan", "--field", "balance",
                   "--domain", "financial"])
    # up to the next heading of EITHER level: facts.py indexes each ### on its own
    fin = re.search(r"^## FINANCIALS: every dollar getter.*?(?=^#{2,3} )", mf, re.S | re.M)
    check("facts.py returns matching sections VERBATIM, and less than the whole file",
          rc == 0 and fin is not None and fin.group(0).strip() in out
          and len(out) < 0.5 * len(mf) and "index of the other" in out, out[:300])
    rc, out = run(["python3", facts, "--entity", "Zyzzogeton"])
    check("facts.py says NO SECTION MATCHED for an unknown entity, and still lists the index",
          rc == 0 and "NO SECTION MATCHED" in out and "index of the other" in out, out[:300])
    # nothing cached: a section added to the source is found on the very next call
    mf2 = os.path.join(ws, "model-facts-copy.md")
    open(mf2, "w").write(mf + "\n## Zyzzogeton traversal is real\n\nProbe section.\n")
    rc, out = run(["python3", facts, "--entity", "Zyzzogeton", "--file", mf2])
    check("facts.py reads the source every call - an added section is found at once",
          rc == 0 and "## Zyzzogeton traversal is real" in out and "NO SECTION" not in out, out[:300])

    prec = os.path.join(PLUGIN, "scripts", "precedents.py")
    rc, out = run(["python3", prec, "--root", "Case", "--template", "tabular_list"],
                  env={"JTI_PROJECT_ROOT": ws})
    check("precedents.py finds the matching report and names the rule to open",
          rc == 0 and "Probe_Report" in out and "Probe_Report_V1.groovy" in out, out[:400])
    rc, out = run(["python3", prec, "--root", "Zyzzogeton"], env={"JTI_PROJECT_ROOT": ws})
    check("precedents.py says NO PRECEDENT rather than forcing a poor match",
          rc == 0 and "NO PRECEDENT" in out, out[:300])

    # usage.activity() splits wall time into active vs waiting-on-the-user. BOTH ways of
    # waiting must count: a turn that ended (stop_reason end_turn) until the next line, and a
    # picker question, whose answer arrives as a tool_result rather than as user text - the
    # first cut of this missed the second and scored every picker question as zero wait.
    T = lambda s: f"2026-09-28T10:{s // 60:02d}:{s % 60:02d}.000Z"
    ev = [
        {"type": "assistant", "timestamp": T(0), "message": {"id": "m1", "stop_reason": "tool_use",
         "content": [{"type": "tool_use", "id": "q1", "name": "AskUserQuestion", "input": {}}]}},
        {"type": "user", "timestamp": T(60), "message": {"content": [
            {"type": "tool_result", "tool_use_id": "q1", "content": "Still current"}]}},
        {"type": "assistant", "timestamp": T(70), "message": {"id": "m2", "stop_reason": "tool_use",
         "content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {}}]}},
        {"type": "user", "timestamp": T(75), "message": {"content": [
            {"type": "tool_result", "tool_use_id": "b1", "content": "ok"}]}},
        {"type": "assistant", "timestamp": T(80), "message": {"id": "m3", "stop_reason": "end_turn",
         "content": [{"type": "text", "text": "done?"}]}},
        {"type": "user", "timestamp": T(110), "message": {"content": [{"type": "text", "text": "yes"}]}},
    ]
    probe_a = ("import sys, json; sys.path.insert(0, %r); import usage as U; "
               "print(json.dumps(U.activity([json.dumps(e) for e in json.loads(sys.argv[1])])))"
               % os.path.join(PLUGIN, "scripts"))
    rc, out = run(["python3", "-c", probe_a, json.dumps(ev)])
    try:
        av = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        av = {}
    check("usage.py counts picker questions AND ended turns as time waiting on the user",
          rc == 0 and av.get("user_idle_secs") == 90.0 and av.get("active_secs") == 20.0
          and av.get("questions") == 1 and av.get("tool_calls") == 2 and av.get("turns") == 3, out)

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

    # ======== INTEGRATION: platform RULE / FORM exports in ~/Downloads ========
    tier("integration")
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

    tier("core")
    # ---- /test-report: the browser-contained build (job coordinator + helper) --------
    import jobs_tests
    jobs_tests.run(check, skip, {"plugin": PLUGIN, "ws": ws, "jrs": JRS, "fix": FIX,
                                 "build_good": build_good, "rule": rule, "fixture": fixture,
                                 "edit": edit})

    # ---- the ones that need a JVM ---------------------------------------------
    if not JRS:
        for n in ("a rule that does not compile is rejected",
                  "a GString value is rejected",
                  "a truncated value is rejected",
                  "a failed render is not reported as success",
                  "ALL build-plan tests (the fake SDK jar needs javac/javap)",
                  "ALL fast-verifier and harness-marker tests"):
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

    # ---- phase 5: build-plan.json and the one orchestration command ----------------
    # Resolves against a FAKE SDK jar compiled here from tests/fixtures/fake_sdk, so none of
    # this depends on a client's export. (Needs the JasperReports JDK for javac/javap, which
    # every JVM test above already needs.)
    bp = os.path.join(PLUGIN, "scripts", "build_plan.py")
    pw = os.path.join(ws, "planws")
    os.makedirs(os.path.join(pw, "Proj"))
    open(os.path.join(pw, ".jti-root"), "w").close()
    jdk = os.path.join(JRS, "java", "bin")
    cls_dir = os.path.join(ws, "fake_sdk_classes")
    os.makedirs(cls_dir)
    import glob as _g5
    rc_j, out_j = run([os.path.join(jdk, "javac"), "-d", cls_dir,
                       *sorted(_g5.glob(os.path.join(FIX, "fake_sdk", "com", "sustain", "cases",
                                                     "model", "*.java")))])
    fake_jar = os.path.join(ws, "ecourt-sdk-fake.jar")
    if rc_j == 0:
        rc_j, out_j = run([os.path.join(jdk, "jar"), "cf", fake_jar, "com"], cwd=cls_dir)
    check("the fake SDK jar builds", rc_j == 0, out_j)

    def _plan_tests():
        run(["python3", os.path.join(PLUGIN, "scripts", "project.py"), "sdk-register",
             os.path.join(pw, "Proj"), fake_jar], env={"JTI_PROJECT_ROOT": pw})
        spec = json.load(open(os.path.join(FIX, "good_spec.json")))
        plan = {"plan_version": 1, "lane": "fast",
                "report": {"folder": "Proj/Plan_Probe", "name": "Plan_Probe", "title": "Plan Probe",
                           "code": "Plan_Probe", "subtitle": "every case type", "slug": "probe"},
                "template": spec["template"], "root": "Case", "rule": "Plan_Probe_V1.groovy",
                "strategy": {"kind": "query-list", "entity": "Case"},
                "params": [{"name": n, "class": c} for n, c in spec["params"]],
                "sections": spec["sections"],
                "outputs": {"caseNumber": "str(c?.caseNumber)", "caseType": "str(c?.caseType)"},
                "traversals": {"caseNumber": "Case.caseNumber", "caseType": "Case.caseType"},
                "provenance": {"caseNumber": {"kind": "sdk"}, "caseType": {"kind": "sdk"}},
                "fixture": {"rows": [{"caseNumber": "CF-2026-00184", "caseType": "Felony"}]},
                "assumptions": ["one row per case"], "unverified": ["labels"],
                "flags": {"financial_calc": False, "custom_layout": False,
                          "conflicting_sources": False, "unusual_grouping": False}}
        def plan_run(p, cmd="run", extra=None, raw=None):
            path = os.path.join(pw, f"plan-{abs(hash(raw or json.dumps(p))) % 10**8}.json")
            open(path, "w").write(raw if raw is not None else json.dumps(p))
            rc, out = run(["python3", bp, cmd, path], env=dict(
                {"JTI_PROJECT_ROOT": pw, "JTI_BUILD_PLAN": "opt-in", "JTI_VERIFIER": "fast"},
                **(extra or {})))
            m = re.search(r"^BUILD-RESULT (\{.*\})$", out, re.M)
            return rc, out, (json.loads(m.group(1)) if m else {})
        def variant(tag, fn):
            v = json.loads(json.dumps(plan))
            v["report"]["folder"] = "Proj/Plan_" + tag; v["report"]["name"] = "Plan_" + tag
            fn(v)
            return v
        def invalid(p, *needles, cmd="validate", raw=None):
            rc, out, d = plan_run(p, cmd, raw=raw)
            errs = " | ".join(d.get("errors", []))
            return (rc == 2 and all(n in errs for n in needles) and "Traceback" not in out,
                    f"rc={rc} {errs or out[-300:]}")

        rc, out, d = plan_run(plan, extra={"JTI_BUILD_PLAN": "", "JTI_REPORT_BUILD_MODE": "fast"})
        check("build_plan refuses to run unless JTI_BUILD_PLAN=opt-in (the alias is not enough)",
              rc == 4 and d.get("stage") == "switch"
              and not os.path.exists(os.path.join(pw, "Proj", "Plan_Probe")), out[-300:])
        rc, out, d = plan_run(plan)
        check("build_plan run stops at the rule (exit 3) - it never generates one",
              rc == 3 and d.get("stage") == "rule" and d.get("lane") == "fast", out[-400:])
        shutil.copy(os.path.join(FIX, "good_rule.groovy"),
                    os.path.join(pw, "Proj", "Plan_Probe", "Plan_Probe_V1.groovy"))
        rc, out, d = plan_run(plan)
        a = d.get("artifacts") or {}
        check("build_plan run builds and verifies a fast-lane plan in one call",
              rc == 0 and d.get("ok") and a.get("zip") and a.get("pdfs") and a.get("pages")
              and (d.get("perf") or {}).get("jvms") == 1
              and {r["field"] for r in d.get("resolved", [])} == {"caseNumber", "caseType"},
              out[-600:])
        notes = open(os.path.join(pw, "Proj", "Plan_Probe", "JRXML_CONTRACT.txt")).read()
        check("build_plan fills the untouched NOTES seed from the plan",
              "ASSUMPTIONS - decisions made without asking" in notes
              and "TODO before this ships" not in notes, notes[-400:])
        rc, out, d = plan_run(plan, extra={"JTI_VERIFIER": "legacy"})
        check("the build plan runs with the LEGACY verifier too (the switches are independent)",
              rc == 0 and d.get("ok") and "mode: fast" not in out, out[-400:])

        # FIELD COVERAGE. Every field a section shows must have declared provenance, and the
        # other lists must agree with it. A field nothing accounts for is exit 2, not a blank.
        def ghost_col(v):
            v["sections"][0]["cols"].append(["Ghost", 20, "Left", "ghost"])
        ok, why = invalid(variant("G1", ghost_col), "field 'ghost' has no provenance",
                          "field 'ghost' has no entry in outputs", "fixture row 1 omits 'ghost'")
        check("an unknown field with NO traversal is rejected (exit 2), not shipped blank", ok, why)
        def ghost_sdk_no_path(v):
            ghost_col(v); v["provenance"]["ghost"] = {"kind": "sdk"}
            v["outputs"]["ghost"] = "str(c?.ghost)"; v["fixture"]["rows"][0]["ghost"] = "x"
        ok, why = invalid(variant("G2", ghost_sdk_no_path), "'ghost' is declared sdk but has no traversal")
        check("omitted traversal coverage: an sdk field with no path is rejected", ok, why)
        def ghost_full(v):
            ghost_sdk_no_path(v); v["traversals"]["ghost"] = "Case.notARealFieldAtAll"
        rc, out, d = plan_run(variant("G3", ghost_full))
        check("a fully-declared field the SDK lacks sends the plan to the expert lane (exit 20)",
              rc == 20 and any(u.get("field") == "ghost" for u in d.get("unresolved", []))
              and not os.path.exists(os.path.join(pw, "Proj", "Plan_G3")), out[-400:])
        def renamed(v):
            v["outputs"]["caseKind"] = v["outputs"].pop("caseType")
            v["traversals"]["caseKind"] = v["traversals"].pop("caseType")
        ok, why = invalid(variant("M1", renamed), "field 'caseType' has no entry in outputs",
                          "output 'caseKind', which no section shows",
                          "traversal for 'caseKind', which no section shows",
                          "'caseType' is declared sdk but has no traversal")
        check("mismatched output / traversal names are rejected, each named", ok, why)
        def short_row(v):
            v["fixture"]["rows"].append({"caseNumber": "CM-2026-01920"})
        ok, why = invalid(variant("F1", short_row), "fixture row 2 omits 'caseType'")
        check("a fixture row that omits a field is rejected, not silently blanked", ok, why)
        def declared_blank(v):
            short_row(v); v["fixture"]["intentional_blanks"] = ["caseType"]
        rc, out, d = plan_run(variant("F2", declared_blank), "validate")
        check("...unless the blank is declared in fixture.intentional_blanks", rc == 0, out[-300:])
        def extra_key(v):
            v["fixture"]["rows"][0]["caseTyp"] = "Felony"
        ok, why = invalid(variant("F3", extra_key), "'caseTyp' is not a field any section shows")
        check("a fixture row key no section shows is rejected (a typo, not a column)", ok, why)
        def computed_no_reason(v):
            v["provenance"]["caseType"] = {"kind": "computed", "reason": "  "}
        def computed_with_path(v):
            v["provenance"]["caseType"] = {"kind": "computed", "reason": "label from a lookup"}
        ok1, w1 = invalid(variant("C1", computed_no_reason), "'caseType' is computed - it needs a reason")
        ok2, w2 = invalid(variant("C2", computed_with_path),
                          "'caseType' is computed but also has a traversal")
        def computed_ok(v):
            computed_with_path(v); del v["traversals"]["caseType"]
        rc, out, d = plan_run(variant("C3", computed_ok), "resolve")
        check("computed/constant fields need a reason and are NEVER counted as resolved SDK paths",
              ok1 and ok2 and rc == 0 and [r["field"] for r in d.get("resolved", [])] == ["caseNumber"]
              and d.get("provenance", {}).get("caseType") == "computed", f"{w1}\n{w2}\n{out[-300:]}")
        bad_kinds = [("K1", {"kind": "SDK"}), ("K2", "sdk"), ("K3", {"kind": 3}), ("K4", {})]
        res_k = [invalid(variant(t, lambda v, x=x: v["provenance"].__setitem__("caseType", x)))
                 for t, x in bad_kinds]
        check("provenance that is missing a kind, not an object, or not a known kind is rejected",
              all(r[0] for r in res_k), "\n".join(r[1] for r in res_k))
        dup = json.dumps(plan).replace('"provenance": {', '"provenance": {"caseType": {"kind": "sdk"}, ', 1)
        ok, why = invalid(None, "key 'caseType' is given more than once", raw=dup)
        check("a key given twice (json would keep only the last) is rejected", ok, why)
        bad_paths = [("P1", 42), ("P2", ""), ("P3", "Case..caseType"), ("P4", "Case.case-type"),
                     ("P5", ["Case", "caseType"]), ("P6", "Case"), ("P7", None)]
        res_p = [invalid(variant(t, lambda v, x=x: v["traversals"].__setitem__("caseType", x)))
                 for t, x in bad_paths]
        check("malformed and non-string paths are exit 2 with the reason, never a traceback",
              all(r[0] for r in res_p), "\n".join(r[1] for r in res_p))
        check("a path that is only the root entity is rejected",
              "only the root entity" in res_p[5][1], res_p[5][1])
        def deep(v):
            v["traversals"]["caseType"] = "Case" + ".parent" * 9 + ".caseType"
        rc, out, d = plan_run(variant("D1", deep))
        check("a traversal past the depth limit is recorded UNRESOLVED and goes expert (exit 20)",
              rc == 20 and any(u.get("field") == "caseType" and "depth limit" in u.get("why", "")
                               for u in d.get("unresolved", [])), out[-400:])
        def shallow(v):
            v["traversals"]["caseType"] = "Case" + ".parent" * 3 + ".caseType"
        rc, out, d = plan_run(variant("D2", shallow), "resolve")
        check("...while a deep path inside the limit still resolves", rc == 0, out[-300:])
        # THE RULE. An sdk path the rule never reads means the plan describes some other rule.
        pr = variant("R1", lambda v: v["traversals"].__setitem__("caseType", "Case.caseTypeLabel"))
        pr["rule"] = "Plan_R1_V1.groovy"
        plan_run(pr)
        shutil.copy(os.path.join(FIX, "good_rule.groovy"),
                    os.path.join(pw, "Proj", "Plan_R1", "Plan_R1_V1.groovy"))
        rc, out, d = plan_run(pr)
        check("a plan path the rule does not read goes to the expert lane, naming the path",
              rc == 20 and "never reads '.caseTypeLabel'" in out and d.get("lane") == "expert"
              and not (d.get("gates") or {}).get("rc") == 0, out[-400:])

        fin = json.loads(json.dumps(plan)); fin["flags"]["financial_calc"] = True
        rc1, _, d1 = plan_run(fin, "validate")
        tpl = json.loads(json.dumps(plan)); tpl["template"] = "grouped_summary"
        rc2, _, d2 = plan_run(tpl, "validate")
        check("computed money and an unscaffoldable template both go to the expert lane",
              rc1 == 20 and rc2 == 20 and d1.get("lane") == "expert" and d2.get("lane") == "expert",
              f"{d1.get('reasons')} {d2.get('reasons')}")
        broken = {k: v for k, v in plan.items() if k != "sections"}
        rc, out, d = plan_run(broken, "validate")
        check("a malformed plan is rejected (exit 2) with the reason",
              rc == 2 and any("sections" in e for e in d.get("errors", [])), out[-300:])

    if rc_j == 0:
        _plan_tests()

    # ======== INTEGRATION: the newest SDK jar registered in the real workspace ========
    # The fake jar proves the mechanics; this proves javap output from a real, much larger
    # client jar still parses the way the fake one does.
    tier("integration")
    real = sorted(_g5.glob(os.path.join(os.path.dirname(PLUGIN), "*", "sdk", "*.jar")),
                  key=os.path.getmtime)
    if real and not CORE_ONLY:
        rw = os.path.join(ws, "realws")
        os.makedirs(os.path.join(rw, "Proj"))
        open(os.path.join(rw, ".jti-root"), "w").close()
        run(["python3", os.path.join(PLUGIN, "scripts", "project.py"), "sdk-register",
             os.path.join(rw, "Proj"), real[-1]], env={"JTI_PROJECT_ROOT": rw})
        rp = json.load(open(os.path.join(PLUGIN, "tests", "fixtures", "good_spec.json")))
        rplan = {"plan_version": 1, "lane": "fast",
                 "report": {"folder": "Proj/Real", "name": "Real", "title": "Real", "code": "Real",
                            "subtitle": "s", "slug": "s"},
                 "template": rp["template"], "root": "Case", "rule": "Real_V1.groovy",
                 "strategy": {"kind": "query-list"}, "params": [], "sections": rp["sections"],
                 "outputs": {"caseNumber": "x", "caseType": "x"},
                 "traversals": {"caseNumber": "Case.caseNumber", "caseType": "Case.caseType"},
                 "provenance": {"caseNumber": {"kind": "sdk"}, "caseType": {"kind": "sdk"}},
                 "fixture": {"rows": [{"caseNumber": "a", "caseType": "b"}]},
                 "assumptions": [], "unverified": [],
                 "flags": {"financial_calc": False, "custom_layout": False,
                           "conflicting_sources": False, "unusual_grouping": False}}
        rpath = os.path.join(rw, "plan.json")
        json.dump(rplan, open(rpath, "w"))
        rc, out = run(["python3", bp, "resolve", rpath],
                      env={"JTI_PROJECT_ROOT": rw, "JTI_BUILD_PLAN": "opt-in"})
        check(f"build_plan resolves Case.caseNumber / caseType in the real SDK "
              f"({os.path.basename(real[-1])})", rc == 0 and "2 resolved, 0 unresolved" in out,
              out[-300:])
    else:
        skip("build_plan resolves against a real client SDK jar",
             "no SDK jar registered in the real workspace")
    tier("core")

    # ---- phase 2: the one-JVM fast verifier ---------------------------------------
    # These run whatever mode the suite itself is in; they set the mode per call.
    fast_env = {"JTI_VERIFIER": "fast"}
    ff = mutate(good, ws, "fast_ok", lambda f: None)
    rc, out = run([os.path.join(PLUGIN, "scripts", "finish.sh"), "Probe_Report_V1.groovy",
                   "Probe_Report.jrxml", "--code", "Probe_Report", "--name", "Probe Report"],
                  cwd=ff, env=fast_env)
    st = re.search(r"^VERIFY-STATS (\{.*\})$", out, re.M)
    st = json.loads(st.group(1)) if st else {}
    check("fast mode: one JVM, one JRXML compile, and the rule run exactly twice (counted)",
          rc == 0 and st == {"jvms": 1, "compiles": 1, "rule_evals": 2}
          and "All gates passed" in out, out[-600:])
    # Output ORDER under a pipe: each child process's lines under its own header. Block
    # buffering printed rule_zip's lines ahead of "== 4/4 rule zip", so the log read as if
    # packaging had printed nothing.
    hz, wz = out.find("== 4/4  rule zip"), out.find("wrote ", out.find("== 3/4"))
    check("fast mode prints each gate's output under its own header (piped)",
          rc == 0 and 0 <= hz < out.find("RULE-", hz) and out.find("RULE-", hz) < out.find("== verdict"),
          out[max(0, hz - 200):hz + 300])
    pngs = sorted(x for x in os.listdir(os.path.join(ff, "verification")) if x.endswith(".png"))
    check("fast mode still leaves a page image for every rendered page",
          rc == 0 and pngs and all(os.path.getsize(os.path.join(ff, "verification", p)) > 0
                                   for p in pngs), pngs)

    # HARNESS MARKER. Fast mode may take the one-JVM path ONLY for an exact, unmodified,
    # supported scaffold harness. Everything else falls back to legacy, saying why.
    fin_cmd = [os.path.join(PLUGIN, "scripts", "finish.sh"), "Probe_Report_V1.groovy",
               "Probe_Report.jrxml", "--code", "Probe_Report", "--name", "Probe Report"]
    check("a marked, unmodified scaffold harness takes the one-JVM path",
          "mode: fast" in (run(fin_cmd, cwd=ff, env=fast_env)[1]), "")
    # a custom FAILING step, with every string the old detection looked for still present
    fc = mutate(good, ws, "fast_custom", lambda f: edit(
        os.path.join(f, "verification", "run.sh"), "python3 gen_jrxml.py\n",
        "python3 gen_jrxml.py\necho '  CUSTOM CHECK FAILED - site-specific step'; exit 7\n"))
    rs_txt = open(os.path.join(fc, "verification", "run.sh")).read()
    rcL, outL = run(fin_cmd, cwd=fc, env={"JTI_VERIFIER": "legacy"})
    rcF, outF = run(fin_cmd, cwd=fc, env=fast_env)
    check("a customised run.sh with a failing step: fast falls back and FAILS exactly as legacy",
          all(x in rs_txt for x in ("render_check.groovy", "--variant", 'WANT="${2:-'))
          and rcL != 0 and rcF != 0 and "CUSTOM CHECK FAILED" in outF and "GATE 2 FAILED" in outF
          and "modified after scaffold.py wrote it" in outF and "mode: fast" not in outF,
          f"legacy rc={rcL} fast rc={rcF}\n{outF[:500]}")
    import hashlib as _hl
    def restamp(f, ver):
        path = os.path.join(f, "verification", "run.sh")
        lines = open(path).read().split("\n")
        body = lines[:1] + lines[2:]
        lines[1] = (f"# JTI_SCAFFOLD_HARNESS_VERSION={ver} sha256="
                    + _hl.sha256("\n".join(body).encode()).hexdigest())
        open(path, "w").write("\n".join(lines))
    fv = mutate(good, ws, "fast_v2", lambda f: restamp(f, 2))
    out = run(fin_cmd, cwd=fv, env=fast_env)[1]
    check("an unsupported (newer) harness version falls back to legacy and says so",
          "version '2' is not supported" in out and "mode: fast" not in out, out[:300])
    fu = mutate(good, ws, "fast_unmarked", lambda f: edit(
        os.path.join(f, "verification", "run.sh"),
        open(os.path.join(f, "verification", "run.sh")).read().split("\n")[1] + "\n", ""))
    out = run(fin_cmd, cwd=fu, env=fast_env)[1]
    check("an unmarked harness (every pre-marker report) falls back to legacy and says so",
          "no JTI_SCAFFOLD_HARNESS_VERSION marker" in out and "mode: fast" not in out, out[:300])

    rc, out = run([os.path.join(PLUGIN, "scripts", "finish.sh"), "Probe_Report_V1.groovy",
                   "Probe_Report.jrxml", "--code", "Probe_Report", "--name", "Probe Report"],
                  cwd=ff, env={"JTI_REPORT_BUILD_MODE": "fsat", "JTI_VERIFIER": ""})
    rc2, out2 = run(fin_cmd, cwd=ff, env={"JTI_VERIFIER": "fsat"})
    check("an unrecognised verifier value (either variable) warns and runs legacy",
          "is not legacy or fast - ignored" in out and rc == 0 and "mode: fast" not in out
          and "is not one of legacy/fast - using legacy" in out2 and rc2 == 0
          and "mode: fast" not in out2, out[:300] + out2[:300])
    rc3, out3 = run(fin_cmd, cwd=ff, env={"JTI_REPORT_BUILD_MODE": "fast", "JTI_VERIFIER": ""})
    check("the deprecated alias still selects the fast verifier through finish.sh",
          rc3 == 0 and "mode: fast" in out3, out3[:300])

    return report()


def report():
    print()
    f_all = 0
    for t in ("core", "integration"):
        rs = [r for r in results if r[3] == t]
        p = sum(1 for r in rs if r[1] is True)
        f = sum(1 for r in rs if r[1] is False)
        s = sum(1 for r in rs if r[1] is None)
        f_all += f
        print(f"  {t:<12} {p} passed, {f} failed, {s} skipped")
    print(f"  verifier     {SWITCHES['verifier']}"
          + ("   (core only: HOME was an empty temp dir)" if CORE_ONLY else "") + "\n")
    return 1 if f_all else 0


if __name__ == "__main__":
    sys.exit(main())
