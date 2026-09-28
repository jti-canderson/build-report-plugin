#!/usr/bin/env python3
"""build_mode.py - the rollout switches, resolved in ONE place.

    build_mode.py                 print every setting, where it came from, and any warning
    build_mode.py get verifier    print one value (for scripts)

Each risky change has its own switch, so one can be enabled without the others:

    JTI_VERIFIER     legacy | fast         the gates: two JVMs, or the one-JVM verifier
                                           (fast still falls back for any harness it cannot prove)
    JTI_INTERACTION  confirm | unattended  confirm: SDK picker + brief-only column check in chat;
                                           unattended: project.py sdk-decide, derived columns
                                           recorded not confirmed
    JTI_LOOKUP       full | targeted       read all of model-facts.md, or query facts.py and
                                           precedents.py
    JTI_BUILD_PLAN   off | opt-in          build_plan.py refuses to run unless opt-in

Defaults are the FIRST value of each - the pre-optimisation behaviour.

JTI_REPORT_BUILD_MODE is a DEPRECATED alias kept for this release: `fast` sets verifier=fast,
interaction=unattended, lookup=targeted - and NOT the build plan, which stays opt-in. A
switch set explicitly always wins over the alias. Unrecognised values warn and use the default.
"""
import os
import sys

SWITCHES = {
    "verifier":    ("JTI_VERIFIER", ("legacy", "fast")),
    "interaction": ("JTI_INTERACTION", ("confirm", "unattended")),
    "lookup":      ("JTI_LOOKUP", ("full", "targeted")),
    "build_plan":  ("JTI_BUILD_PLAN", ("off", "opt-in")),
}
ALIAS = "JTI_REPORT_BUILD_MODE"
ALIAS_FAST = {"verifier": "fast", "interaction": "unattended", "lookup": "targeted"}


def resolve(env=None):
    env = os.environ if env is None else env
    out, src, notes = {}, {}, []
    alias = env.get(ALIAS, "").strip()
    if alias and alias not in ("legacy", "fast"):
        notes.append(f"{ALIAS}={alias!r} is not legacy or fast - ignored, defaults used")
        alias = ""
    if alias == "fast":
        notes.append(f"{ALIAS}=fast (deprecated alias) enables verifier=fast, "
                     f"interaction=unattended, lookup=targeted. The build plan stays OFF "
                     f"(set JTI_BUILD_PLAN=opt-in to enable it).")
    for key, (var, allowed) in SWITCHES.items():
        v = env.get(var, "").strip()
        if v and v not in allowed:
            notes.append(f"{var}={v!r} is not one of {'/'.join(allowed)} - using {allowed[0]}")
            v = ""
        if v:
            out[key], src[key] = v, var
        elif alias == "fast" and key in ALIAS_FAST:
            out[key], src[key] = ALIAS_FAST[key], ALIAS
        else:
            out[key], src[key] = allowed[0], "default"
    return out, src, notes


def main():
    vals, src, notes = resolve()
    if len(sys.argv) >= 3 and sys.argv[1] == "get":
        for n in notes:
            print("  " + n, file=sys.stderr)
        print(vals.get(sys.argv[2], ""))
        return 0
    for n in notes:
        print("  NOTE  " + n)
    for k, (var, _) in SWITCHES.items():
        print(f"  {k:<12} {vals[k]:<11} ({src[k]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
