#!/usr/bin/env python3
"""verify_fast.py - finish.sh's gates, with the rule gate and the render gate in ONE JVM.

    verify_fast.py <rule>.groovy <report>.jrxml --code CODE --name "Human Name" [...]

Selected by JTI_REPORT_BUILD_MODE=fast (finish.sh hands over to this). Run from inside the
report folder, exactly like finish.sh. Same gates, same order, same "GATE n FAILED" lines.

WHAT IS DIFFERENT, AND WHY EACH IS SAFE
  one JVM      verify.groovy runs the UNCHANGED rulecheck.groovy and render_check.groovy in
               one process instead of two. Their checks and messages are their own.
  C1 JIT       -XX:TieredStopAtLevel=1 by default (JTI_JVM_OPTS overrides; set it empty to
               turn it off). It picks the fast-starting compiler; program semantics are the
               same. Measured: rulecheck 5.64s -> 3.30s, render_check 9.22s -> 5.95s.
  one regen    gen_jrxml.py runs once. run.sh used to run it a second time, on the same
               inputs, producing the same file.
  one raster   render_check draws AWT page images that run.sh then overwrote from the PDF
               with pdfraster.py. Only the PDF raster is done now. If PyMuPDF is missing the
               AWT images are kept instead, as they effectively were before.
  one process  the per-PDF Python steps (raster, truncation) run in this process instead of
               one interpreter each.

WHAT IS STRICTER
  - a page that cannot be rasterised FAILS the render gate. Before, pdfraster errors were
    thrown away and the AWT images - which show glyphs the PDF drops - were what got looked
    at. A page nobody can inspect is not a verified page.
  - a packaging failure is labelled GATE 4 (finish.sh says GATE 3 - a mislabel).

WHEN IT DOES NOT APPLY - it hands over to the legacy gates, unchanged, and says why:
  - no verification/run.sh, or one that is not the scaffold's one-JVM render_check harness
    (the hand-copied asset template, or a report's own custom script)
  - no verification/fixture.py to write the render TSVs
"""
import glob
import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL = os.path.join(ROOT, "skills", "jasper-reports")
TPL = os.path.join(ROOT, "templates")
NOISE = re.compile(r'^\s+at |^\s+\.\.\. |log4j|SLF4J|Illegal reflective|font "Times"|^VERIFY-|^$')
DEFAULT_JVM_OPTS = "-XX:TieredStopAtLevel=1"

T0 = time.time()
stages = {}                 # stage -> seconds, accumulated
current = [None, T0]        # the stage running now, and when it began
counts = {"jvms": 0, "compiles": 0, "rule_evals": 0}


def mark(name):
    """Close the running stage and open `name`. The stage open at a failure is the one
    the record blames - the same rule finish.sh's marks follow."""
    now = time.time()
    if current[0]:
        stages[current[0]] = round(stages.get(current[0], 0.0) + now - current[1], 3)
    current[0], current[1] = name, now


def perf_record(rc):
    """Same record shape as finish.sh's, written directly rather than via a subprocess."""
    failed = current[0] if rc else None
    mark(None)
    rec = {"ts": round(time.time(), 3), "mode": "fast", "rc": rc, "ok": rc == 0,
           "failed_stage": failed,
           "wall": round(time.time() - T0, 3), "stages": stages, **counts,
           "report": hashlib.sha1(os.getcwd().encode()).hexdigest()[:8]}
    if os.path.isdir("verification"):
        with open(os.path.join("verification", "perf.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
    st = "  ".join(f"{k} {v:.1f}s" for k, v in stages.items())
    verdict = "ok" if rc == 0 else f"FAILED at {failed}"
    print(f"  perf [fast] {rec['wall']:.1f}s {verdict}  |  {st}  |  "
          f"{counts['jvms']} JVM, {counts['compiles']} compile, {counts['rule_evals']} rule run")
    print("VERIFY-STATS " + json.dumps(counts))


def done(rc):
    perf_record(rc)
    sys.exit(rc)


def fail(gate, why):
    print()
    print(f"  GATE {gate} FAILED - {why}")
    print("  Fix it and re-run finish.sh. Later gates were not run.")
    done(1)


def header(t):
    print(f"== {t} " + "=" * max(0, 58 - len(t)))


def legacy(reason):
    """Hand over to the legacy gates, unchanged. Never a silent downgrade."""
    print(f"  fast verifier: {reason} - running the legacy gates instead.")
    # FLUSH before exec. Under a pipe - which is how every real build captures this - Python
    # block-buffers stdout, and execve replaces the process without flushing it, so the one
    # line saying the downgrade happened was silently thrown away. The suite caught it.
    env = dict(os.environ, JTI_REPORT_BUILD_MODE="legacy")
    # The legacy scripts start their own JVMs, which cannot be handed a flag without editing
    # them - but every JVM reads JAVA_TOOL_OPTIONS. So the fast-start JIT still applies to a
    # harness this file does not understand: measured on the 5-variant asset-template report,
    # 66.8s -> 47.2s with identical artifacts. JTI_JVM_OPTS="" turns it off here too.
    opts = os.environ.get("JTI_JVM_OPTS", DEFAULT_JVM_OPTS).strip()
    if opts:
        env["JAVA_TOOL_OPTIONS"] = (os.environ.get("JAVA_TOOL_OPTIONS", "") + " " + opts).strip()
        print(f"  (its JVMs still get the fast-start JIT: JAVA_TOOL_OPTIONS={env['JAVA_TOOL_OPTIONS']})")
    sys.stdout.flush()
    os.execve(os.path.join(HERE, "finish.sh"), [os.path.join(HERE, "finish.sh")] + sys.argv[1:], env)


def find_jrs():
    if os.environ.get("JRS"):
        return os.environ["JRS"]
    found = None
    for c in sorted(glob.glob("/Applications/jasperreports-server-*")) + \
            sorted(glob.glob(os.path.expanduser("~/jasperreports-server-*"))):
        if os.path.isdir(os.path.join(c, "java", "bin")):
            found = c                    # newest wins, as in the generated run.sh
    return found or "/Applications/jasperreports-server-9.0.0"


def run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def run_py_inprocess(path, argv):
    """Run a plugin script's main() in this interpreter; return its exit status."""
    old = sys.argv
    sys.argv = [path] + argv
    try:
        runpy.run_path(path, run_name="__main__")
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.argv = old


def main():
    # Line-buffered, so a gate's header lands BEFORE the output of the child process under
    # it. Block-buffered (the default under a pipe) printed rule_zip's lines ahead of the
    # "== 4/4 rule zip" header - the log read as though packaging had printed nothing.
    sys.stdout.reconfigure(line_buffering=True)
    if len(sys.argv) < 3:
        print(__doc__.split("\n\n")[0]); sys.exit(2)
    rule, jrxml, extra = sys.argv[1], sys.argv[2], sys.argv[3:]
    for f in (rule, jrxml):
        if not os.path.isfile(f):
            print(f"  no such file: {f}"); sys.exit(2)

    # ---- does this report have the harness the fast path understands? -------------------
    runsh = os.path.join("verification", "run.sh")
    if not os.path.isfile(runsh):
        legacy("no verification/run.sh")
    rs = open(runsh, encoding="utf8").read()
    # EXACT, versioned, unmodified scaffold output only - never inferred from substrings. A
    # customised run.sh can keep render_check/--variant/WANT and add a required step; fast
    # mode would skip that step. harness_marker.check() proves the file is untouched.
    import harness_marker
    ok, why = harness_marker.check(rs)
    if not ok:
        legacy(why)
    if not os.path.isfile(os.path.join("verification", "fixture.py")):
        legacy("no verification/fixture.py to write the render fixtures")
    # The variant list is READ from the harness, never assumed. Two existing reports use
    # render_check but spell their variants some other way; defaulting to "full none" there
    # would render pages the legacy gate never draws, and call that the same result.
    m = re.search(r'WANT="\$\{2:-([^}]*)\}"', rs)
    if not m or not m.group(1).split():
        legacy("cannot read the variant list (WANT=...) from verification/run.sh")
    variants = m.group(1).split()
    print("  mode: fast (one JVM) - JTI_REPORT_BUILD_MODE=legacy forces the old gates")

    # ---- 0. regenerate -----------------------------------------------------------------
    mark("regenerate")
    if os.path.isfile("gen_jrxml.py"):
        header("0/4  regenerate")
        if run([sys.executable, "gen_jrxml.py"]).returncode != 0:
            fail(0, "gen_jrxml.py failed")
        print()

    # ---- 1. contract -------------------------------------------------------------------
    mark("contract")
    header("1/4  contract")
    if run([sys.executable, os.path.join(TPL, "contract_check.py"), rule, jrxml]).returncode != 0:
        fail(1, "the rule and the layout disagree")

    # ---- render inputs: the TSVs run.sh wrote before its JVM ----------------------------
    mark("fixtures")
    for p in glob.glob(os.path.join("verification", "fixture_*.tsv")):
        os.remove(p)
    vargs = []
    for v in variants:
        mode = "" if v == "full" else v
        r = run([sys.executable, os.path.join("verification", "fixture.py"), mode],
                capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            fail(2, f"verification/fixture.py could not write the {v} fixture")
        vargs += ["--variant", f"{v}_sample=verification/fixture_{v}.tsv"]

    # ---- 1.5 + 2. rule executes, then render: ONE JVM ----------------------------------
    mark("jvm")
    header("1.5/4  rule executes")
    fx = os.path.join("verification", "Fixture.groovy")
    rule_not_run = not os.path.isfile(fx)
    if rule_not_run:
        print("  NO verification/Fixture.groovy - the rule was NOT executed, only inspected.")
        print("  Scaffold one, or copy the pattern from a recent report. A rule that is never run")
        print("  can still fail on its first use in eSeries.")
    try:
        import fitz  # noqa: F401  - decides who draws the pages
        have_fitz = True
    except ImportError:
        have_fitz = False
    jrs = find_jrs()
    java = os.path.join(jrs, "java", "bin", "java")
    if not os.access(java, os.X_OK):
        fail(1.5, f"no JVM at {java} - set JRS to your JasperReports Server install")
    cp = (f"{jrs}/buildomatic/lib/groovy-3.0.13.jar:"
          f"{jrs}/apache-tomcat/webapps/jasperserver-pro/WEB-INF/lib/*")
    opts = os.environ.get("JTI_JVM_OPTS", DEFAULT_JVM_OPTS).split()
    cmd = [java, "-Djava.awt.headless=true", *opts, "-cp", cp, "groovy.ui.GroovyMain",
           os.path.join(SKILL, "scripts", "verify.groovy"),
           "--skill", SKILL, "--tpl", TPL, "--rule", rule, "--jrxml", jrxml,
           "--out", "verification"]
    if not rule_not_run:
        cmd += ["--fixture", fx]
    if not have_fitz:
        cmd += ["--awt-raster", "1"]
    cmd += vargs
    counts["jvms"] += 1
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = p.stdout + p.stderr
    res = re.search(r"^VERIFY-RESULT (\{.*\})$", out, re.M)
    sts = re.search(r"^VERIFY-STATS (\{.*\})$", out, re.M)
    if sts:
        s = json.loads(sts.group(1))
        counts["compiles"], counts["rule_evals"] = s.get("compiles", 0), s.get("rule_evals", 0)
        # split the one JVM stage into start-up / rule / render, from the JVM's own clock
        jvm_wall = time.time() - current[1]
        rs_, ds_ = s.get("rule_secs", 0.0), s.get("render_secs", 0.0)
        stages["jvm_startup"] = round(max(0.0, jvm_wall - rs_ - ds_), 3)
        stages["rule"], stages["render"] = rs_, ds_
        current[0], current[1] = None, time.time()
    result = json.loads(res.group(1)) if res else {"gate": "render" if p.returncode else None,
                                                   "rc": p.returncode}
    lines = [ln for ln in out.splitlines() if not NOISE.search(ln)]
    # split the JVM's output at the render's first line so each gate prints under its header
    cut = next((i for i, ln in enumerate(lines) if ln.startswith("compiled ")), len(lines))
    rule_lines, render_lines = lines[:cut], lines[cut:]
    if result.get("gate") == "rule":
        print("\n".join(rule_lines))
        current[0] = "rule"              # the stage the record must blame
        fail(1.5, "the rule did not execute cleanly")
    if not rule_not_run:
        print("\n".join(rule_lines))
    print()
    mark("raster")
    header("2/4  render")
    if result.get("gate") == "render" or p.returncode != 0:
        current[0] = "render"
        print("\n".join(render_lines or rule_lines))
        print(f"  render FAILED (exit {result.get('rc') or p.returncode})")
        fail(2, "the jrxml did not compile or fill")
    print("\n".join(render_lines))
    pdfs = sorted(glob.glob(os.path.join("verification", "*_sample.pdf")))
    if have_fitz:
        for pdf in pdfs:
            rc = run_py_inprocess(os.path.join(SKILL, "scripts", "pdfraster.py"), [pdf])
            if rc != 0:
                fail(2, f"could not rasterise {pdf} for inspection")
    print("output in verification/")

    # ---- 3. truncation -----------------------------------------------------------------
    print()
    mark("truncation")
    header("3/4  truncation")
    clip = False
    for pdf in pdfs:
        v = os.path.basename(pdf)[:-len("_sample.pdf")]
        tsv = os.path.join("verification", f"fixture_{v}.tsv")
        if os.path.isfile(tsv):
            if run_py_inprocess(os.path.join(HERE, "cliphunt.py"), [pdf, tsv]) != 0:
                clip = True
    if clip:
        fail(3, "a value was truncated - widen it, shorten it, or make the fixture carry the "
                "abbreviated form")
    if not os.path.isfile(os.path.join("verification", "fixture_full.tsv")):
        print("  (no per-variant fixtures - skipped)")

    # ---- 4. package --------------------------------------------------------------------
    print()
    mark("package")
    header("4/4  rule zip")
    if run([sys.executable, os.path.join(HERE, "rule_zip.py"), rule, jrxml, *extra]).returncode != 0:
        fail(4, "contract fault - no zip written")

    # ---- verdict -----------------------------------------------------------------------
    print()
    mark("verdict")
    header("verdict")
    ok = True
    for f in [rule, jrxml] + (glob.glob("RULE-*.zip") or ["RULE-*.zip"]) + \
             ["RULE_REGISTRATION.txt", "JRXML_CONTRACT.txt"]:
        if os.path.isfile(f):
            print(f"  ok      {f}")
        else:
            print(f"  MISSING {f}"); ok = False
    if rule_not_run:
        print("  WARN    rule never executed - no Fixture.groovy")
    allpdf = glob.glob(os.path.join("verification", "*.pdf"))
    if allpdf:
        print(f"  ok      {len(allpdf)} rendered PDF(s) - LOOK AT EVERY PAGE before reporting back")
    if not ok:
        done(1)
    print()
    print("  All gates passed. Fill the NOTES blocks, then hand over the zip.")
    print("  IMPORTING IS A WRITE - the user imports it, not you.")
    done(0)


if __name__ == "__main__":
    main()
