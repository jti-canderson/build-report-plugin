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
            ok = rc2 == 0 and "Nothing else moved." in d and "item text differs" not in d
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
