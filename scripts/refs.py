#!/usr/bin/env python3
"""
Print several reference documents in ONE call.

    refs.py model-facts report-rules criteria-api
    refs.py --list

WHY: the references are read as separate calls, and every call re-sends the whole
conversation before it returns a file that was sitting on disk. Three reads is three
prefills for one answer. Names resolve against skills/jasper-reports/references/, with or
without the .md.

This does not decide WHICH to read - `model-facts` first, always, and then the one or two
the task needs. Reading all of them is not thoroughness, it is 1500 lines of standing
context that crowds out the report.
"""
import os
import sys

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "skills", "jasper-reports", "references")


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    avail = sorted(f[:-3] for f in os.listdir(REF) if f.endswith(".md"))
    if "--list" in sys.argv or not names:
        print(__doc__)
        print("  available:")
        for n in avail:
            lines = sum(1 for _ in open(os.path.join(REF, n + ".md"), encoding="utf8"))
            print(f"    {n:22} {lines:>4} lines")
        sys.exit(0 if "--list" in sys.argv else 2)

    missing = [n for n in (x[:-3] if x.endswith(".md") else x for x in names)
               if n not in avail]
    if missing:
        sys.exit(f"  no such reference: {', '.join(missing)}\n  available: {', '.join(avail)}")

    for n in names:
        n = n[:-3] if n.endswith(".md") else n
        path = os.path.join(REF, n + ".md")
        print(f"\n{'=' * 78}\n=== {n}.md\n{'=' * 78}\n")
        sys.stdout.write(open(path, encoding="utf8").read())


if __name__ == "__main__":
    main()
