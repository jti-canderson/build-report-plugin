#!/usr/bin/env python3
"""
What did this report cost? Run it at the end of a build.

    python3 usage.py                # since the last /build-report in this session
    python3 usage.py --session      # the whole session
    python3 usage.py --json         # machine-readable

Reads Claude Code's own transcript for the current working directory
(~/.claude/projects/<slug>/<session>.jsonl) - a READ of the assistant's log, never of the
user's project, and it writes nothing.

EFFECTIVE tokens, not raw. The raw count is misleading because the four kinds are not
priced alike, and the biggest number is the cheapest one:

    fresh input      x1        cache WRITE  x2
    cache READ       x0.1      output       x5

So a turn that re-reads 200k of cached conversation costs about as much as 20k of new
reading - and 4k of output costs more than either. Reporting raw totals makes a long
session look catastrophic and hides where the money actually went.

THE NUMBER TO WATCH IS CONTEXT SIZE. Cache reads scale with how much is already loaded,
and they are charged on EVERY turn. If the cost here looks high, check "context/turn"
before blaming the report.

BUT HIGH CONTEXT/TURN HAS TWO DIFFERENT CAUSES AND ONLY ONE IS FIXABLE, so this script
does not guess between them - it measures. The discriminator is `entry`: the prompt size
of the build's FIRST turn, i.e. what was already loaded before any of this work started.

    entry small   the build filled its own context - the skill, model-facts, a precedent
                  rule, rendered page images. Intrinsic to the work. A fresh session
                  changes NOTHING, and saying otherwise sends someone off to re-run a
                  build that will cost exactly the same.
    entry large   there really was prior conversation, and it is re-read every turn.
                  Reported as a figure, because entry x 0.1 x turns is roughly what that
                  inheritance cost.

This used to print "a fresh session would cost materially less" whenever context/turn
crossed a threshold, with no idea which case it was in. On 2026-09-09 it said exactly
that about a build that WAS the whole session, starting from its first message - the
advice was not merely useless, it was false, and it went into a handoff.
"""
import json, os, sys, glob, pathlib, collections

W = {"input_tokens": 1.0, "cache_creation_input_tokens": 2.0,
     "cache_read_input_tokens": 0.1, "output_tokens": 5.0}
# $ per million input-equivalent tokens.
PRICE = {"opus": 5.0, "sonnet": 3.0, "haiku": 1.0}
# The marker is the SLASH-COMMAND INVOCATION, not the words "build-report". Tool results
# carry role "user" too, so a looser match lands on some Bash output that merely mentioned
# the command and silently reports a shorter, cheaper build than actually happened - it read
# 66 turns where 89 had run. Match the command tag, and require an assistant turn after it.
MARK = "<command-name>"
MARK2 = "build-report"


def transcript(cwd=None):
    cwd = pathlib.Path(cwd or os.getcwd()).resolve()
    slug = "-" + str(cwd).strip("/").replace("/", "-").replace("_", "-").replace(".", "-")
    d = pathlib.Path.home() / ".claude" / "projects" / slug
    files = sorted(glob.glob(str(d / "*.jsonl")), key=os.path.getmtime, reverse=True)
    return files[0] if files else None


def eff(u):
    return sum(W[k] * u.get(k, 0) for k in W)


def build_start(lines):
    """Index of the last REAL /build-report invocation, or 0.

    PARSED, never substring-matched against the raw line. The marker text also turns up
    inside TOOL RESULTS - which carry type "user" - so a line-level `in` test lands on
    whichever Read or Edit happened to touch a file that mentions the command. On
    2026-09-09 that made this report ONE turn of a 130-turn build, at $0.08 of a $10.46
    build: seven "hits", every one of them an edit to this very script.

    The structural difference is reliable where the text is not: a tool result is a
    content block of type "tool_result", a slash command is a "text" block. Require the
    marker to sit in a text block.
    """
    found = 0
    for i, ln in enumerate(lines):
        if MARK not in ln or MARK2 not in ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("type") != "user":
            continue
        c = (d.get("message") or {}).get("content")
        blocks = c if isinstance(c, list) else [{"type": "text", "text": c or ""}]
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text") or ""
                if MARK in t and MARK2 in t:
                    found = i
                    break
    return found


def prompt_size(u):
    """Everything the model was handed on this turn, however it was cached. Summing all
    three matters: on the FIRST turn of a session the context is a cache WRITE and
    cache_read is 0, while mid-session the same context arrives as a cache READ. Reading
    only cache_read would score a fresh start and an inherited 120k the same way."""
    return sum(u.get(k, 0) for k in
               ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def scan(lines, start=0):
    tot, turns, entry = 0.0, 0, None
    raw, bytool = collections.Counter(), collections.Counter()
    for ln in lines[start:]:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        m = d.get("message") or {}
        u = m.get("usage")
        if not u:
            continue
        # The first turn in range: what this build INHERITED, before it read anything.
        if entry is None:
            entry = prompt_size(u)
        e = eff(u); tot += e; turns += 1
        for k in W:
            raw[k] += u.get(k, 0)
        ts = [c.get("name", "") for c in (m.get("content") or [])
              if isinstance(c, dict) and c.get("type") == "tool_use"]
        bytool[ts[0] if ts else "(thinking and writing)"] += e
    return tot, raw, bytool, turns, (entry or 0)


def subagents(path):
    base = path[:-6]
    out = []
    for p in glob.glob(os.path.join(base, "subagents", "**", "*.jsonl"), recursive=True):
        if os.path.basename(p) == "journal.jsonl":
            continue
        t, _, _, n, _ = scan(open(p, errors="ignore").read().splitlines())
        out.append((os.path.basename(p), t, n))
    return out


def main():
    whole = "--session" in sys.argv
    as_json = "--json" in sys.argv
    path = transcript()
    if not path:
        print("no transcript for this directory - nothing to measure")
        return 0
    lines = open(path, errors="ignore").read().splitlines()

    start = 0 if whole else build_start(lines)
    tot, raw, bytool, turns, entry = scan(lines, start)
    subs = subagents(path) if whole else []
    sub_tot = sum(t for _, t, _ in subs)

    ctx = raw["cache_read_input_tokens"] / turns if turns else 0

    # What the build inherited = context at ITS first turn, minus what any session in
    # this directory starts with anyway. That baseline is not small - system prompt, tool
    # schemas, the skill listing, CLAUDE.md - and it is NOT conversation, so a fixed
    # floor mislabels it: the first attempt at this used 40k and duly reported an
    # "inherited" 56,634 on a build that began at the session's first message.
    # Subtracting the session's own turn-1 prompt needs no magic number and is exact:
    # when the build IS the session, the two are the same figure and inherited is 0.
    baseline = scan(lines)[4] if start else entry
    inherited = max(0, entry - baseline)
    if inherited < 5_000:                       # noise, not conversation
        inherited = 0
    carried = inherited * W["cache_read_input_tokens"] * turns
    data = {"scope": "session" if whole else "since last /build-report",
            "turns": turns, "raw": dict(raw), "effective": round(tot),
            "subagent_effective": round(sub_tot), "context_per_turn": round(ctx),
            "entry_context": round(entry), "session_baseline": round(baseline),
            "inherited_context": round(inherited), "inherited_effective": round(carried),
            "usd": {k: round((tot + sub_tot) / 1e6 * v, 2) for k, v in PRICE.items()}}
    if as_json:
        print(json.dumps(data, indent=2)); return 0

    model = "sonnet"
    for i, a in enumerate(sys.argv):
        if a == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1].lower()
    usd = data["usd"].get(model, data["usd"]["sonnet"])

    # DEFAULT IS THE COMPACT FORM. This goes at the end of a handoff message to someone who
    # wants to know what the build cost, not to read a profile - so it is a few clean lines,
    # never a bar chart. `--full` keeps the breakdown for when the question is actually
    # "where did it go".
    if "--full" not in sys.argv:
        print(f"  **Build cost** · {turns} turns · {tot + sub_tot:,.0f} effective tokens "
              f"· ~${usd:,.2f} ({model.title()})")
        # Three different things to say, and which one is true is MEASURED, not guessed.
        # Never claim a fresh session would be cheaper without evidence that this build
        # inherited something - see the note in the module docstring.
        if inherited:
            print(f"  Context averaged {ctx:,.0f} tokens/turn, ~{inherited:,.0f} of it "
                  f"already loaded before the build began.")
            print(f"  That inherited context is re-read every turn: roughly "
                  f"{carried:,.0f} effective tokens, ~${carried / 1e6 * PRICE[model]:,.2f} "
                  f"of the figure above, which a fresh session would not pay.")
        elif ctx > 120_000:
            print(f"  Context averaged {ctx:,.0f} tokens/turn, but the build started at "
                  f"{entry:,.0f} and this directory's baseline is {baseline:,.0f} — so "
                  f"that growth is the")
            print("  build's OWN reading (skill, precedent, rendered pages), not "
                  "inherited conversation. A fresh session would cost the same.")
        else:
            print(f"  Context averaged {ctx:,.0f} tokens/turn.")
        return 0

    print(f"  scope            {data['scope']}")
    print(f"  turns            {turns}")
    print(f"  effective        {tot + sub_tot:,.0f} input-equivalent tokens")
    print(f"  context/turn     {ctx:,.0f}  <- cache reads scale with this")
    print(f"  entry context    {entry:,.0f}  <- loaded before turn 1 of the build")
    print(f"  session baseline {baseline:,.0f}  <- what any session here starts with")
    if inherited:
        print(f"  inherited        {inherited:,.0f} of conversation, re-read across "
              f"{turns} turns = {carried:,.0f} effective")
    else:
        print("  inherited        none - the build began at the session's first message")
    if subs:
        print(f"  subagents        {len(subs)}, {sub_tot:,.0f} effective")
    print(f"\n  cost   opus ${data['usd']['opus']:,.2f}   "
          f"sonnet ${data['usd']['sonnet']:,.2f}   haiku ${data['usd']['haiku']:,.2f}")
    print("\n  where it went")
    for k, v in sorted(bytool.items(), key=lambda kv: -kv[1])[:8]:
        bar = "#" * int(v / tot * 40)
        print(f"    {v/tot*100:5.1f}%  {bar:<40}  {k}")
    print("\n  raw (unweighted, for reference)")
    for k in raw:
        print(f"    {k:32} {raw[k]:>13,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
