#!/usr/bin/env python3
"""
The template picker. Show this FIRST, before building anything.

    python3 catalog.py            # the menu
    python3 catalog.py list       # one template in detail, by name
    python3 catalog.py --preview  # regenerate every sample PDF to look at

Written for someone who does not read Groovy. Pick by what the page looks like, not
by what the rule does.
"""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent

CATALOG = [
    ("record_summary", "Record Summary",
     "Everything about ONE person or case, broken into sections.",
     "Person Summary, Case Summary",
     "A header with the name, a few counts in boxes, then a section per topic - "
     "Address, Telephone, Identification - each with its own columns and a count."),
    ("eseries_summary", "eSeries Screen",
     "A print copy of an eSeries folder view - it looks like the application.",
     "Case Summary, any folder view someone screenshots",
     "Flag banners, the case title block with its two columns of details, then a "
     "grey bar per panel with that panel's own column grid. Reach for this when "
     "someone hands you a SCREENSHOT of an eSeries screen and wants the report to "
     "look like that - which is a complete answer, not a fallback. Interactivity "
     "(hover, the Filter box, collapsing a panel, clicking a tab) cannot come "
     "across; every visual thing can."),
    ("tabular_list", "List",
     "A straight list. One row per record, runs over as many pages as it needs.",
     "Payments Report, Past Due Financial Obligations, Age Caseload",
     "Title, the criteria you searched on, then one table. The workhorse - reach "
     "for this unless something below fits better."),
    ("grouped_summary", "Grouped Summary",
     "A list split into groups, each with a subtotal, and a grand total at the end.",
     "Collections by Agency, Payments by Obligation Type",
     "Same as a List, but banded - 'Tulsa County DA' then its rows then its "
     "subtotal, and so on. Use it whenever someone asks 'broken down by'."),
    ("statement", "Statement",
     "A document you hand or send to somebody, not a data dump.",
     "Receipt, Voucher Payee Statement, Depository Ticket",
     "From and To blocks, a document number and date, the amount in large type, "
     "the line items, and a signature line."),
    ("wide_table", "Wide Table (landscape)",
     "A List turned sideways for up to nine columns.",
     "VOCA, full payment detail",
     "Only when the columns genuinely will not fit upright - landscape does not "
     "print well in a stack with everything else."),
]


def menu():
    print("\n  Which one should this report look like?\n")
    for _, title, one_liner, egs, _ in CATALOG:
        print(f"  {title}")
        print(f"      {one_liner}")
        print(f"      like: {egs}\n")
    print("  Reply with a name. `python3 catalog.py list` for more on one of them.")
    ex = HERE / "examples"
    if ex.exists():
        print(f"  Rendered examples are already on disk: {ex}\n")
    else:
        print("  `python3 catalog.py --preview` writes a sample PDF of each to out/.\n")


def detail(key):
    for mod, title, one_liner, egs, more in CATALOG:
        if mod == key or title.lower().startswith(key.lower()):
            print(f"\n  {title}   (templates/{mod}.py)\n")
            print(f"      {one_liner}\n      {more}\n")
            print(f"      Reports like this: {egs}")
            s = sample(mod)
            print(f"      Sample page:       {s}")
            print(f"      Sample PDF:        {s.with_suffix('.pdf')}\n")
            return 0
    print(f"no template '{key}' - run without arguments for the menu")
    return 1


def _name(mod):
    src = (HERE / "templates" / f"{mod}.py").read_text()
    return src.split('NAME = "')[1].split('"')[0]


def sample(mod):
    """Where the already-rendered example lives.

    Prefer examples/ - shipped pre-rendered, so picking a template never waits on a
    render. Fall back to out/ when working in the source library.
    """
    n = _name(mod)
    for cand in (HERE / "examples" / f"{n}.png", HERE / "out" / f"{n}_sample_p1.png"):
        if cand.exists():
            return cand
    return HERE / "examples" / f"{n}.png"


def preview():
    for mod, title, *_ in CATALOG:
        print(f"  {title} ...")
        subprocess.run(["./render.sh", f"templates/{mod}.py"], cwd=HERE,
                       capture_output=True)
    print(f"\n  sample pages in {HERE / 'out'}\n")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else None
    if a == "--preview":
        preview()
    elif a:
        sys.exit(detail(a))
    else:
        menu()
