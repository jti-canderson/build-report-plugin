#!/usr/bin/env python3
"""facts.py - targeted lookup into model-facts.md, instead of reading all 868 lines.

    facts.py --entity Case --entity Receipt --field caseType --domain financial
    facts.py --template eseries_summary --category clipping
    facts.py --section 17            # one section in full, by its index number
    facts.py --index                 # every section, one line each, with its tags

WHY: every build was told to read the whole of model-facts.md before any model search -
~12k tokens that then sit in the conversation for the rest of the build. The one clean real
build measured (2026-09-17) spent 21% of its time in domain and field lookup. Most sections
are about entities that build never touched.

WHAT IT RETURNS: the sections that match, IN FULL and verbatim, then a one-line index of
every other section - so nothing becomes undiscoverable, and --section N opens any of them.
When nothing matches it says so and prints the index; it never pretends a miss is an answer.

THE FILE IS THE SOURCE. This is an index computed from model-facts.md on every call - there
is no second copy to drift - and the full document stays where it is. Open it whenever the
targeted result is not enough.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FACTS = os.path.join(HERE, "..", "skills", "jasper-reports", "references", "model-facts.md")

FINANCIAL = re.compile(r"\b(amount|balance|cents|receipt|payment|obligation|restitution|voucher|"
                       r"deposit|pay ?plan|payplan|financ\w*|dollar|money|allocat\w*|fee|invoice|"
                       r"assessment|disburse\w*)\b", re.I)
CATEGORIES = {
    "clipping":  r"\bclip\w*|truncat\w*|cliphunt|too wide|width",
    "null":      r"aconst_null|\bstub\w*|sentinel|\bnull\b|stripped|-1L|-1\.0",
    "prefix":    r"\bprefix\b|\bcf_|\bc_\w",
    "glyph":     r"WinAnsi|glyph|\btick\b|U\+[0-9A-F]{4}",
    "contract":  r"contract_check|\b_data\b|\bkeys?\b",
    "sort":      r"\bsort\b",
    "dates":     r"\bdate\w*\b",
    "lookup":    r"\blookup\w*|Label\b",
    "security":  r"\blogin\w*|security|\bUser\b|\brole\b",
    "sdk":       r"\bSDK\b|javap|bytecode|jar\b|sdk_fields",
}
TEMPLATES = {   # module -> the ways model-facts refers to it (the letters predate the names)
    "record_summary":  [r"Template A\b", r"record_summary", r"Record Summary"],
    "tabular_list":    [r"Template B\b", r"tabular_list", r"\bList\b"],
    "grouped_summary": [r"Template C\b", r"grouped_summary", r"Grouped Summary"],
    "statement":       [r"Template D\b", r"\bstatement\b", r"Statement"],
    "wide_table":      [r"Template E\b", r"wide_table", r"Wide Table"],
    "eseries_summary": [r"eSeries Screen", r"eseries_summary"],
}
ENVS = {
    "epqa":  r"EPQA|eProsecutor ?Baseline ?QA|BaselineQA",
    "okdac": r"OKDAC|okdac",
    "eh-team": r"eh-team|Eh Team",
    "local": r"\blocal\b",
}


def sections(text):
    """(index, level, heading, parent heading, first line, body) for every ## / ### section."""
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2).strip())
             for i, l in enumerate(lines) for m in [re.match(r"^(#{2,3}) (.+)$", l)] if m]
    out, parent = [], ""
    for k, (i, lvl, h) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        if lvl == 2:
            parent = h
        body = "\n".join(lines[i:end]).rstrip()
        out.append({"n": k + 1, "level": lvl, "heading": h, "parent": parent if lvl == 3 else "",
                    "line": i + 1, "end": end, "body": body})
    return out


def vocabulary(text):
    """Entity names as model-facts itself writes them: FQCNs, and CamelCase in backticks."""
    names = set(re.findall(r"com\.sustain\.\w+(?:\.\w+)*\.model\.([A-Z]\w+)", text))
    for tok in re.findall(r"`([^`]+)`", text):
        for w in re.findall(r"\b([A-Z][a-z]+(?:[A-Z][a-z0-9]+)*)\b", tok):
            names.add(w)
    return names


def tags(sec, vocab):
    b = sec["body"]
    t = {"entities": sorted(w for w in vocab if re.search(rf"\b{re.escape(w)}\b", b)),
         "financial": len(FINANCIAL.findall(b)) >= 2,
         "categories": sorted(c for c, rx in CATEGORIES.items() if re.search(rx, b)),
         "templates": sorted(m for m, pats in TEMPLATES.items() if any(re.search(p, b) for p in pats)),
         "envs": sorted(e for e, rx in ENVS.items() if re.search(rx, b))}
    return t


def hit_entity(e, sec, t):
    return any(x.lower() == e.lower() for x in t["entities"]) or \
        re.search(rf"\b{re.escape(e)}\b", sec["body"], re.I) is not None


def hit_field(f, sec):
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(f)}(?![A-Za-z0-9_])", sec["body"], re.I) is not None


def rarity(n_hits, n_secs):
    """How much a match on this term says. `Case` appears in most sections, so matching it
    narrows almost nothing; a field named in two sections is nearly an address. Weighting by
    rarity (an IDF) is what stops a Case report from 'matching' the whole file."""
    import math
    return 3.0 * math.log((n_secs + 1) / (n_hits + 1)) + 0.5


def score(sec, t, q, w):
    s, why = 0.0, []
    for e in q.entity:
        if hit_entity(e, sec, t):
            s += w[("e", e)]; why.append(f"entity {e}")
    for f in q.field:
        if hit_field(f, sec):
            s += w[("f", f)]; why.append(f"field {f}")
    for c in q.category:
        if c in t["categories"]:
            s += 2; why.append(f"category {c}")
    for m in q.template:
        if m in t["templates"]:
            s += 2; why.append(f"template {m}")
    if q.domain == "financial" and t["financial"]:
        s += 1; why.append("financial")
    if q.env and q.env in t["envs"]:
        s += 1; why.append(f"env {q.env}")
    return s, why


def one_line(sec, t):
    tg = []
    if t["financial"]: tg.append("financial")
    tg += t["categories"][:3] + t["templates"][:2] + t["envs"][:1]
    ents = ",".join(t["entities"][:4])
    return (f"  [{sec['n']:>2}] L{sec['line']:<4} {'  ' if sec['level'] == 3 else ''}"
            f"{sec['heading'][:70]}  {{{ents}}} {' '.join(tg)}")


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--entity", action="append", default=[])
    ap.add_argument("--field", action="append", default=[])
    ap.add_argument("--category", action="append", default=[], choices=sorted(CATEGORIES))
    ap.add_argument("--template", action="append", default=[], choices=sorted(TEMPLATES))
    ap.add_argument("--domain", choices=["financial", "general"])
    ap.add_argument("--env", choices=sorted(ENVS))
    ap.add_argument("--section", type=int, action="append", default=[])
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--file", default=FACTS)
    ap.add_argument("-h", "--help", action="store_true")
    q = ap.parse_args()
    text = open(q.file, encoding="utf8").read()
    secs = sections(text)
    vocab = vocabulary(text)
    T = {s["n"]: tags(s, vocab) for s in secs}
    asked = q.entity or q.field or q.category or q.template or q.domain or q.env
    if q.help or not (asked or q.section or q.index):
        print(__doc__); return 0

    if q.section:
        for n in q.section:
            s = next((x for x in secs if x["n"] == n), None)
            print(s["body"] if s else f"  no section {n} (1..{len(secs)})")
            print()
        return 0
    if q.index and not asked:
        print(f"model-facts.md: {len(secs)} sections, {text.count(chr(10))} lines "
              f"({os.path.relpath(q.file)})")
        for s in secs:
            print(one_line(s, T[s["n"]]))
        return 0

    w = {("e", e): rarity(sum(hit_entity(e, s, T[s["n"]]) for s in secs), len(secs)) for e in q.entity}
    w.update({("f", f): rarity(sum(hit_field(f, s) for s in secs), len(secs)) for f in q.field})
    ranked = []
    for s in secs:
        sc, why = score(s, T[s["n"]], q, w)
        if sc > 0:
            ranked.append((round(sc, 1), s, why))
    ranked.sort(key=lambda r: (-r[0], r[1]["n"]))
    # keep what is close to the best match - a long tail of weak hits is the whole file again
    top = ranked[0][0] if ranked else 0
    shown = [r for r in ranked if r[0] >= 0.5 * top][:q.limit]
    shown_lines = sum(s["end"] - s["line"] + 1 for _, s, _ in shown)
    total_lines = text.count("\n") + 1
    if not shown:
        print("  NO SECTION MATCHED - nothing in model-facts.md is established for this yet.")
        print("  That is a finding, not a pass: the model question is open. Index follows.\n")
    else:
        print(f"model-facts.md: {len(shown)} of {len(secs)} sections match "
              f"({shown_lines} of {total_lines} lines). Full file: {os.path.relpath(q.file)}\n")
        for sc, s, why in shown:
            ctx = f"   (under: {s['parent']})" if s["parent"] else ""
            print(f"----- [{s['n']}] score {sc}: {', '.join(why)}{ctx}")
            print(s["body"])
            print()
        if len(ranked) > len(shown):
            print(f"  ... {len(ranked) - len(shown)} more matched more weakly - they are in the "
                  f"index below; open any with --section N")
    rest = [s for s in secs if s["n"] not in {x["n"] for _, x, _ in shown}]
    print(f"\n----- index of the other {len(rest)} sections (open any with --section N)")
    for s in rest:
        print(one_line(s, T[s["n"]]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
