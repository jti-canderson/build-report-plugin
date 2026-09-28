#!/usr/bin/env python3
"""perf.py - record how long a verification run took, stage by stage. Measures, never decides.

    perf.py record --marks "start:T0 contract:T1 ..." --rc N [--mode legacy|fast]
                   [--jvms N --compiles N --rule-evals N] [--out verification/perf.jsonl]
    perf.py show [verification/perf.jsonl]        # the last run, one readable line

`--marks` is a space-separated list of name:epoch-seconds, each mark being the moment that
stage BEGAN; a stage's duration runs to the next mark, and the final mark `end` closes the
last one. A run that stops early simply has fewer marks - the last stage that began and never
reached the next one is the stage that failed.

One JSON line is APPENDED per run, so a folder keeps its whole history: a build that took
four passes through the gates to get green shows four lines. That count is itself a result.

PRIVACY: nothing here reads report data. The record holds stage names, durations, counts,
the mode, the exit status and a short hash of the folder path - no field values, no names,
no paths.
"""
import argparse
import hashlib
import json
import os
import sys
import time


def parse_marks(s):
    out = []
    for tok in (s or "").split():
        name, _, ts = tok.rpartition(":")
        try:
            out.append((name, float(ts)))
        except ValueError:
            continue
    return out


def record(a):
    marks = parse_marks(a.marks)
    stages, failed = {}, None
    for (n, t), (_, t2) in zip(marks, marks[1:]):
        stages[n] = round(t2 - t, 3)
    if marks and marks[-1][0] != "end":
        # the run stopped inside the last stage that began
        failed = marks[-1][0]
        stages[marks[-1][0]] = round(time.time() - marks[-1][1], 3)
    if a.rc and failed is None:
        # exit happened after the last mark - attribute it to the last real stage
        real = [n for n, _ in marks if n not in ("start", "end")]
        failed = real[-1] if real else None
    stages.pop("start", None)
    rec = {
        "ts": round(time.time(), 3),
        "mode": a.mode,
        "rc": a.rc,
        "ok": a.rc == 0,
        "failed_stage": failed if a.rc else None,
        "wall": round((marks[-1][1] if marks else time.time()) - marks[0][1], 3) if marks else None,
        "stages": stages,
        "jvms": a.jvms, "compiles": a.compiles, "rule_evals": a.rule_evals,
        "report": hashlib.sha1(os.getcwd().encode()).hexdigest()[:8],
    }
    # Never CREATE a folder to hold the record: a report without verification/ must come out
    # of a gate run exactly as it went in. No folder, no file - the summary line still prints.
    d = os.path.dirname(a.out) or "."
    if os.path.isdir(d):
        with open(a.out, "a") as f:
            f.write(json.dumps(rec) + "\n")
    print("  " + human(rec))


def human(r):
    st = "  ".join(f"{k} {v:.1f}s" for k, v in (r.get("stages") or {}).items())
    counts = ""
    if r.get("jvms") is not None:
        counts = f"  |  {r['jvms']} JVM, {r['compiles']} compile, {r['rule_evals']} rule run"
    verdict = "ok" if r["ok"] else f"FAILED at {r['failed_stage']}"
    return f"perf [{r['mode']}] {r['wall']:.1f}s {verdict}  |  {st}{counts}"


def show(path):
    if not os.path.exists(path):
        print(f"  no {path}"); return 1
    lines = [json.loads(x) for x in open(path) if x.strip()]
    if not lines:
        print("  empty"); return 1
    print(f"  {len(lines)} run(s) recorded; last:")
    print("  " + human(lines[-1]))
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?")
    ap.add_argument("path", nargs="?")
    ap.add_argument("--marks", default="")
    ap.add_argument("--rc", type=int, default=0)
    ap.add_argument("--mode", default="legacy")
    ap.add_argument("--jvms", type=int)
    ap.add_argument("--compiles", type=int)
    ap.add_argument("--rule-evals", type=int, dest="rule_evals")
    ap.add_argument("--out", default="verification/perf.jsonl")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help or a.cmd not in ("record", "show"):
        print(__doc__); return 0
    if a.cmd == "record":
        record(a); return 0
    return show(a.path or "verification/perf.jsonl")


if __name__ == "__main__":
    sys.exit(main())
