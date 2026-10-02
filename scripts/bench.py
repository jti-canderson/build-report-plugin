#!/usr/bin/env python3
"""bench.py - time a report's verification pipeline without touching the report.

    python3 bench.py <report folder> [--mode legacy|fast] [--runs N] [--json OUT.jsonl]
                     [--mutate nodata|contract|clip|gstring] [--keep]
    python3 bench.py --compare A.json B.json      # legacy vs fast artifact manifests

Every run works on a TEMPORARY COPY. The report folder you point at is only ever read.

WHAT IS MEASURED
  wall        seconds for the whole verification command, as a user waits on it
  jvms        JVM launches, counted by a shim `java` (see below) - exact
  jvm_secs    time spent inside those JVMs
  compiles    JRXML compilations      } exact when the fast verifier reports them;
  rule_evals  executions of the rule   } DERIVED from script semantics for legacy runs
  stages      per-stage seconds, from verification/perf.jsonl when the pipeline writes it

HOW JVMs ARE COUNTED WITHOUT CHANGING THE LEGACY SCRIPTS: finish.sh and every generated
run.sh launch "$JRS/java/bin/java", and both honour a JRS already in the environment. So a
throwaway JRS directory is built whose java/bin/java logs one line and execs the real java,
with buildomatic/ and apache-tomcat/ symlinked through, so the classpath is identical. The
code under test is byte-for-byte what a user runs.

DERIVED COUNTS (legacy only), from reading the scripts on 2026-09-28:
  rulecheck.groovy     0 compiles, 2 rule executions (normal id + unresolvable id),
                       plus whatever an Assertions.groovy calls run() for - not counted
  render.groovy        1 compile, 1 rule execution, per invocation (= per variant)
  render_check.groovy  1 compile per invocation, no rule execution (fills from TSVs)
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
REAL_JRS = os.environ.get("JRS") or next(
    (p for p in sorted(__import__("glob").glob("/Applications/jasperreports-server-*"))
     if os.path.isdir(os.path.join(p, "java", "bin"))), None)

SEMANTICS = {
    "rulecheck.groovy":    {"compiles": 0, "rule_evals": 2},
    "render.groovy":       {"compiles": 1, "rule_evals": 1},
    "render_check.groovy": {"compiles": 1, "rule_evals": 0},
}

SHIM = r"""#!/bin/bash
# bench.py JVM counter: one line per launch, then the real java, exit status preserved.
t0=$(/usr/bin/perl -MTime::HiRes -e 'printf "%.3f", Time::HiRes::time()')
script=""; for a in "$@"; do case "$a" in *.groovy) script="$a"; break;; esac; done
"__REAL__" "$@"; rc=$?
t1=$(/usr/bin/perl -MTime::HiRes -e 'printf "%.3f", Time::HiRes::time()')
echo "$t0 $t1 $rc $(basename "$script")" >> "$JTI_BENCH_JVM_LOG"
exit $rc
"""


def make_shim(root):
    """A JRS directory whose java counts launches. Same jars, same JVM."""
    if not REAL_JRS:
        sys.exit("  no JasperReports Server install found - set JRS")
    shim = os.path.join(root, "jrs-shim")
    os.makedirs(os.path.join(shim, "java", "bin"))
    for d in ("buildomatic", "apache-tomcat"):
        os.symlink(os.path.join(REAL_JRS, d), os.path.join(shim, d))
    java = os.path.join(shim, "java", "bin", "java")
    with open(java, "w") as f:
        f.write(SHIM.replace("__REAL__", os.path.join(REAL_JRS, "java", "bin", "java")))
    os.chmod(java, 0o755)
    return shim


def detect(folder):
    """The rule, layout, code and name a real finish.sh call would be given."""
    names = os.listdir(folder)
    jrxml = [n for n in names if n.endswith(".jrxml")]
    rules = [n for n in names if n.endswith(".groovy")]
    if len(jrxml) != 1 or not rules:
        raise SystemExit(f"  cannot tell which rule/jrxml to use in {folder}: {rules} {jrxml}")
    rule = next((r for r in rules if re.search(r"_V\d+\.groovy$", r)), rules[0])
    code = name = template = ""
    reg = layout.find(folder, "RULE_REGISTRATION.txt")
    if os.path.exists(reg):
        t = open(reg, encoding="utf8").read()
        m = re.search(r"^Code\s+(\S+)", t, re.M); code = m.group(1) if m else ""
        m = re.search(r"^Name\s+(.+)$", t, re.M); name = m.group(1).strip() if m else ""
    con = layout.find(folder, "JRXML_CONTRACT.txt")
    if os.path.exists(con):
        m = re.search(r"Template:\s*(\S+)", open(con, encoding="utf8").read())
        template = m.group(1) if m else ""
    spec = layout.find(folder, "spec.json")
    if os.path.exists(spec):
        s = json.load(open(spec, encoding="utf8"))
        template = template or s.get("template") or ""
        name = name or s.get("title") or ""
    stem = jrxml[0][:-6]
    return {"rule": rule, "jrxml": jrxml[0], "code": code or stem,
            "name": name or stem.replace("_", " "), "template": template}


# ── mutations: each breaks exactly ONE thing, on the temp copy ──────────────────────────
def mutate(folder, kind, d):
    rule = os.path.join(folder, d["rule"])
    src = open(rule, encoding="utf8").read()
    if kind == "nodata":
        new, n = re.subn(r"(?m)^(\s*)_data(\s*=[^=])", r"\1data\2", src, count=1)
        assert n, "no `_data =` line to break"
        open(rule, "w", encoding="utf8").write(new)
    elif kind == "contract":
        jr = open(os.path.join(folder, d["jrxml"]), encoding="utf8").read()
        fields = re.findall(r'<field name="([^"]+)"', jr)
        f = next((x for x in fields if re.search(rf"\b{re.escape(x)}\s*:", src)), None)
        assert f, "no jrxml field found as a map key in the rule"
        open(rule, "w", encoding="utf8").write(
            re.sub(rf"\b{re.escape(f)}(\s*:)", rf"{f}Renamed\1", src))
    elif kind == "gstring":
        # a GString value: the classic "looks like a String, is not one"
        new, n = re.subn(r'(\w+\s*:\s*)"([A-Za-z][^"$\n]{2,30})"', r'\1"${1 + 1} \2"', src, count=1)
        assert n, "no plain string literal to turn into a GString"
        open(rule, "w", encoding="utf8").write(new)
    elif kind == "clip":
        # Lengthen EVERY value in the first fixture row. Lengthening only the first one did
        # nothing on Cases By Type: that column wraps (correct - it is not a truncation), so
        # the mutation proved nothing in either mode. Some column in a real layout has a
        # fixed height; with every value long, at least one must be cut, and the gate has to
        # notice.
        fx = os.path.join(folder, "verification", "fixture.py")
        t = open(fx, encoding="utf8").read()
        i = t.index("ROWS")
        row = re.search(r"\(([^()\n]*)\)", t[i:])
        assert row, "no tuple row in fixture ROWS to lengthen"
        a, b = i + row.start(1), i + row.end(1)
        tail = " Extended Far Beyond Any Reasonable Column Width Whatsoever Indeed Truly"
        new_row = re.sub(r'"([^"\n]+)"', lambda m: f'"{m.group(1)}{tail}"', t[a:b])
        open(fx, "w", encoding="utf8").write(t[:a] + new_row + t[b:])
    else:
        raise SystemExit(f"  unknown mutation {kind}")


# ── the two pipelines ───────────────────────────────────────────────────────────────────
def pipeline_cmd(mode, d):
    # BOTH modes go through finish.sh: the verifier is chosen by JTI_VERIFIER, exactly
    # as a real build selects it (JTI_VERIFIER), so the switch itself is exercised on every fast run.
    cmd = [os.path.join(PLUGIN, "scripts", "finish.sh"), d["rule"], d["jrxml"],
           "--code", d["code"], "--name", d["name"]]
    if d["template"]:
        cmd += ["--template", d["template"]]
    return cmd


def run_once(src, mode, mutation=None, keep=False):
    tmp = tempfile.mkdtemp(prefix="jti-bench-")
    work = os.path.join(tmp, os.path.basename(src.rstrip("/")))
    shutil.copytree(src, work, ignore=shutil.ignore_patterns("*.png", "*_sample.pdf", "Out"))
    shim = make_shim(tmp)
    d = detect(work)
    if mutation:
        mutate(work, mutation, d)
    log = os.path.join(tmp, "jvm.log")
    env = dict(os.environ, JRS=shim, JTI_PLUGIN=PLUGIN, JTI_BENCH_JVM_LOG=log,
               JTI_VERIFIER=mode)
    t0 = time.perf_counter()
    p = subprocess.run(pipeline_cmd(mode, d), cwd=work, env=env,
                       capture_output=True, text=True)
    wall = time.perf_counter() - t0
    out = p.stdout + p.stderr
    jv = []
    if os.path.exists(log):
        for ln in open(log):
            a, b, rc, script = (ln.split() + ["?"])[:4]
            jv.append({"secs": round(float(b) - float(a), 3), "rc": int(rc), "script": script})
    rec = {"report": os.path.basename(src.rstrip("/")), "mode": mode,
           "mutation": mutation, "rc": p.returncode, "wall": round(wall, 3),
           "jvms": len(jv), "jvm_secs": round(sum(j["secs"] for j in jv), 3),
           "jvm_detail": jv, "failed_gate": failed_gate(out)}
    stats = re.search(r"^VERIFY-STATS (\{.*\})$", out, re.M)
    if stats:                                     # the fast verifier reports its own counts
        s = json.loads(stats.group(1))
        rec["compiles"], rec["rule_evals"] = s["compiles"], s["rule_evals"]
        rec["counts"] = "exact"
    else:
        rec["compiles"] = sum(SEMANTICS.get(j["script"], {}).get("compiles", 0) for j in jv)
        rec["rule_evals"] = sum(SEMANTICS.get(j["script"], {}).get("rule_evals", 0) for j in jv)
        rec["counts"] = "derived"
    perf = os.path.join(work, "verification", "perf.jsonl")
    if os.path.exists(perf):
        lines = [json.loads(x) for x in open(perf) if x.strip()]
        if lines:
            rec["stages"] = lines[-1].get("stages")
    rec["manifest"] = manifest(work, d) if p.returncode == 0 else None
    rec["tail"] = "\n".join(l for l in out.splitlines() if l.strip())[-1500:]
    if keep:
        rec["kept"] = work
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return rec


def failed_gate(out):
    m = re.search(r"GATE ([\d.]+) FAILED", out)
    return m.group(1) if m else None


# ── what a build produced, for legacy-vs-fast equivalence ──────────────────────────────
TODAY = re.compile(r"\b\d{2}/\d{2}/\d{4}(?: \d{1,2}:\d{2})?\b")


def manifest(folder, d):
    jr = open(os.path.join(folder, d["jrxml"]), encoding="utf8").read()
    m = {"params": sorted(set(re.findall(r'<parameter name="([^"]+)"', jr))),
         "fields_declared": sorted(set(re.findall(r'<field name="([^"]+)"', jr))),
         "fields_placed": sorted(set(re.findall(r"\$F\{([A-Za-z0-9_]+)\}", jr))),
         # uuid attributes are masked, and ONLY those: jti_style mints a fresh random uuid
         # per element on every generator run, so two back-to-back gen_jrxml.py runs with no
         # gates at all already differ there. Everything else - geometry, expressions, fonts,
         # element order - is compared byte for byte.
         "jrxml_sha": hashlib.sha1(re.sub(r'uuid="[^"]*"', 'uuid=""', jr).encode()).hexdigest()[:12],
         "jrxml_elements": jr.count("<reportElement")}
    for doc in ("RULE_REGISTRATION.txt", "JRXML_CONTRACT.txt"):
        p = layout.find(folder, doc)
        m[doc] = hashlib.sha1(open(p, "rb").read()).hexdigest()[:12] if os.path.exists(p) else None
    zips = sorted(x for x in os.listdir(folder) if x.startswith("RULE-") and x.endswith(".zip"))
    m["zip"] = {}
    for z in zips:
        with zipfile.ZipFile(os.path.join(folder, z)) as zf:
            m["zip"][z] = {n: hashlib.sha1(zf.read(n)).hexdigest()[:12] for n in zf.namelist()}
    m["pdfs"] = {}
    try:
        import fitz
    except ImportError:
        fitz = None
    # verification/ for the scaffold harness; Out/ for the hand-copied asset template, which
    # writes its pages there. Missing Out/ made a 5-variant comparison report "agree" having
    # compared no pages at all.
    found = []
    for sub in ("verification", os.path.join("verification", "Out"), "Out"):
        vd = os.path.join(folder, sub)
        if os.path.isdir(vd):
            found += [(vd, x) for x in sorted(os.listdir(vd)) if x.endswith(".pdf")]
    for vdir, pdf in found:
        entry = {}
        if fitz:
            doc = fitz.open(os.path.join(vdir, pdf))
            entry["pages"] = doc.page_count
            text = "\n".join(pg.get_text() for pg in doc)
            entry["text_sha"] = hashlib.sha1(TODAY.sub("<DATE>", text).encode()).hexdigest()[:12]
            # one raster per page at a fixed scale, for a pixel comparison later
            entry["raster"] = [hashlib.sha1(pg.get_pixmap(matrix=fitz.Matrix(1, 1)).samples)
                               .hexdigest()[:12] for pg in doc]
        pngs = sorted(x for x in os.listdir(vdir) if x.startswith(pdf[:-4] + "_p") and x.endswith(".png"))
        entry["pngs"] = len(pngs)
        m["pdfs"][os.path.relpath(os.path.join(vdir, pdf), folder)] = entry
    return m


def compare(a, b):
    """Name every artifact that differs between two manifests. Silence means agreement."""
    diffs = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            diffs.append((k, a.get(k), b.get(k)))
    return diffs


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--mode", default="legacy", choices=["legacy", "fast"])
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--mutate")
    ap.add_argument("--json")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help or not (a.folder or a.compare):
        print(__doc__); return 0
    if a.compare:
        x, y = (json.load(open(p)) for p in a.compare)
        diffs = compare(x.get("manifest") or {}, y.get("manifest") or {})
        for k, u, v in diffs:
            print(f"  DIFFERS {k}:\n    {u}\n    {v}")
        print("  manifests agree" if not diffs else f"  {len(diffs)} difference(s)")
        return 1 if diffs else 0
    recs = [run_once(os.path.abspath(a.folder), a.mode, a.mutate, a.keep) for _ in range(a.runs)]
    walls = [r["wall"] for r in recs]
    r0 = recs[0]
    print(f"  {r0['report']}  mode={a.mode}  mutation={a.mutate or '-'}  runs={a.runs}")
    print(f"  wall  median {statistics.median(walls):.2f}s  (min {min(walls):.2f}, max {max(walls):.2f})")
    print(f"  jvms {r0['jvms']}  jvm_secs {r0['jvm_secs']}  compiles {r0['compiles']}  "
          f"rule_evals {r0['rule_evals']} ({r0['counts']})  rc {r0['rc']}  "
          f"failed_gate {r0['failed_gate']}")
    if a.json:
        with open(a.json, "a") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
