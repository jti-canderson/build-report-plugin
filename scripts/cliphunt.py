#!/usr/bin/env python3
"""
Find fixture values that the rendered PDF TRUNCATED.

    cliphunt.py <pdf> <fixture.tsv> [more.tsv ...]

A cell wider than its column is cut mid-word - no ellipsis, no error, no warning. Until
now the only thing that caught it was a human looking at the raster and happening to know
what the value should have said. jti_style._fits_width guards column HEADERS, which are
known at generate time; row VALUES are not, so nothing guarded them.

It cannot be found in the PDF alone, because the cut-off text is simply not there. It CAN
be found by comparing the PDF against the fixture that produced it: the fixture says
"Juvenile Delinquent Proceeding" and the page says "Juvenile Delinquent", so the value was
truncated. That is what this does.

Exit 1 if anything looks truncated, so it can gate a build.

FALSE POSITIVES are possible and are reported as suspicions, not failures of fact: a rule
that deliberately abbreviates (the "+2 more" criteria summary) will show up here. Read the
list; do not blindly widen. What matters is that a silent cut is now LOUD.
"""
import re
import sys

try:
    import fitz
except ImportError:
    sys.exit("PyMuPDF not available: python3 -m pip install pymupdf")

NORM = re.compile(r"\s+")


def norm(s):
    return NORM.sub(" ", s).strip()


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    pdf, tsvs = sys.argv[1], sys.argv[2:]

    doc = fitz.open(pdf)
    text = norm(" ".join(p.get_text() for p in doc))

    values = set()
    for t in tsvs:
        lines = [l for l in open(t, encoding="utf8").read().splitlines() if l.strip()]
        for line in lines[1:]:
            for v in line.split("\t"):
                v = norm(v.replace("\\n", " "))
                # Short values cannot be told apart from coincidence, and a value that is
                # a prefix of another cell's text would false-positive constantly.
                if len(v) >= 8:
                    values.add(v)

    hits = []
    for v in sorted(values):
        if v in text:
            continue
        # Walk back to the longest prefix that IS on the page. A real truncation leaves a
        # long prefix; a value that is simply absent leaves almost nothing.
        best = ""
        for i in range(len(v), 3, -1):
            if v[:i] in text:
                best = v[:i]
                break
        if best and len(best) >= max(6, int(len(v) * 0.4)):
            hits.append((v, best))

    if not hits:
        print(f"  no truncated values  ({len(values)} checked against {doc.page_count} page(s))")
        return

    print(f"  TRUNCATED - {len(hits)} value(s) cut mid-word with no ellipsis:\n")
    for full, shown in hits:
        print(f"    fixture : {full!r}")
        print(f"    page    : {shown!r}")
        print(f"              {' ' * len(repr(shown))}^ cut here\n")
    print("  Widen the column in gen_jrxml.py, shorten the value in the rule, or - if the")
    print("  rule abbreviates on purpose - make the fixture carry the abbreviated form so")
    print("  this check keeps proving the real contract.")
    sys.exit(1)


if __name__ == "__main__":
    main()
