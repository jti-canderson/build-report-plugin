#!/usr/bin/env python3
"""Where each file of a report folder lives. One answer, shared by every script.

The top of a report folder holds only what gets deployed:

    <Name>.jrxml   <Name>_V1.groovy   RULE-<Code>.zip   <Name>_Launcher.vm

Everything else - the spec, the layout generator, the registration notes, the handoff, the
fixtures and the rendered samples - lives in SUPPORT, so the folder is easy to navigate.

Reports built before this kept those files at the top. `find()` reads either place, and
`migrate()` moves a flat folder's files into SUPPORT (scaffold.py and finish.sh call it), so
an old report rebuilds into the new layout without anyone moving files by hand.

    python3 layout.py migrate <report folder>
"""
import os
import re
import shutil
import sys

SUPPORT = "verification"
# The files that used to sit at the top of the folder and now live in SUPPORT.
MOVED = ("spec.json", "spec.submitted.json", "gen_jrxml.py",
         "HANDOFF.md", "JRXML_CONTRACT.txt", "RULE_REGISTRATION.txt")


def support(folder):
    return os.path.join(folder, SUPPORT)


def path(folder, name):
    """Where `name` is written now."""
    return os.path.join(folder, SUPPORT, name)


def find(folder, name):
    """Where `name` is - SUPPORT first, then the top (a report built before the move)."""
    new = path(folder, name)
    old = os.path.join(folder, name)
    return new if os.path.exists(new) or not os.path.exists(old) else old


def report_dir(spec_path):
    """The report folder a spec.json belongs to: its folder, or the one above SUPPORT."""
    d = os.path.dirname(os.path.abspath(spec_path))
    return os.path.dirname(d) if os.path.basename(d) == SUPPORT else d


def _fix_harness(folder):
    """An UNMODIFIED scaffold run.sh from before the move calls `python3 gen_jrxml.py` at
    the top. Point it at SUPPORT and re-stamp it, so it stays the exact harness the fast
    verifier accepts. A hand-edited run.sh is left exactly as it is."""
    import harness_marker as HM
    p = path(folder, "run.sh")
    if not os.path.isfile(p):
        return False
    text = open(p, encoding="utf8").read()
    ok, _ = HM.check(text)
    if not ok or not re.search(r"^python3 gen_jrxml\.py$", text, re.M):
        return False
    lines = text.split("\n")
    body = "\n".join(lines[:1] + lines[2:])          # drop the old marker
    body = re.sub(r"^python3 gen_jrxml\.py$", f"python3 {SUPPORT}/gen_jrxml.py", body, flags=re.M)
    open(p, "w", encoding="utf8").write(HM.stamp(body))
    return True


# The line every generated gen_jrxml.py used to write its .jrxml with: beside ITSELF, which
# inside SUPPORT is the wrong folder. Both new forms work from either place.
OLD_OUT = 'out = pathlib.Path(__file__).parent / f"{NAME}.jrxml"'
NEW_OUT = ('here = pathlib.Path(__file__).resolve().parent\n'
           '    out = (here.parent if here.name == "' + SUPPORT + '" else here) / f"{NAME}.jrxml"')


def _fix_generator(folder):
    p = path(folder, "gen_jrxml.py")
    if not os.path.isfile(p):
        return False
    text = open(p, encoding="utf8").read()
    if OLD_OUT not in text:
        return False
    open(p, "w", encoding="utf8").write(text.replace(OLD_OUT, NEW_OUT))
    return True


def migrate(folder):
    """Move a flat folder's support files into SUPPORT. Returns the names moved.

    Never overwrites: a file already in SUPPORT wins and the top-level copy is left for a
    person to look at."""
    moved = []
    for name in MOVED:
        old = os.path.join(folder, name)
        if os.path.isfile(old) and not os.path.exists(path(folder, name)):
            os.makedirs(support(folder), exist_ok=True)
            shutil.move(old, path(folder, name))
            moved.append(name)
    _fix_generator(folder)
    _fix_harness(folder)
    return moved


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "migrate":
        sys.exit(__doc__.strip().splitlines()[-1].strip())
    for n in migrate(sys.argv[2]):
        print(f"  moved   {n} -> {SUPPORT}/{n}")
