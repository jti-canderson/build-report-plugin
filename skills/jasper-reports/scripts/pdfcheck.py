#!/usr/bin/env python3
"""pdfcheck.py — inspect a rendered report PDF as text, before rasterising it.

    python3 pdfcheck.py sample.pdf              defects only
    python3 pdfcheck.py sample.pdf --layout     also dump every block and rule, per page
    python3 pdfcheck.py sample.pdf --page 2     one page

Reading a rendered page as an image costs ~2k tokens per page and you often only wanted
to know whether two cells collided. This answers the mechanical questions - overlaps,
struck-through text, clipping, stray "null" - from the PDF's own geometry, for almost
nothing. **Rasterise only for the questions it cannot answer**: does the page look right,
is the hierarchy legible, is the whitespace balanced.

Needs PyMuPDF (`import fitz`), which the Jaspersoft workstation already has.
"""
import sys, collections

# Below this, two same-row cells have no readable daylight between them. See the
# tight-gutter check for how the number was arrived at.
MIN_GUTTER = 6.0

try:
    import fitz
except ImportError:
    sys.exit("PyMuPDF not available: python3 -m pip install pymupdf")


def lines(page):
    """Text LINES with tight bounding boxes.

    Not get_text("blocks") - a block is a paragraph-ish grouping that happily spans
    several table cells, so block rectangles overlap constantly and every check built on
    them cries wolf. A line's bbox hugs its own glyphs, which is what column collision
    actually means.
    """
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                out.append((fitz.Rect(line["bbox"]), text))
    return sorted(out, key=lambda t: (round(t[0].y0, 1), t[0].x0))


def rules(page, min_width=40):
    """Horizontal hairlines. Report separators, section rules, the accent bar."""
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width >= min_width and r.height <= 3:
            out.append(r)
    return sorted(out, key=lambda r: r.y0)


def check_page(page, n, verbose):
    findings = []
    bs, rs = lines(page), rules(page)

    if not bs:
        findings.append(("empty-page", f"page {n} has no text"))

    # A hairline whose y sits inside a text block, overlapping it horizontally, is drawn
    # THROUGH that text. This is the classic separator-in-the-wrong-band defect: it looks
    # fine until a cell stretches or a sub-line prints below the row.
    for r in rs:
        for rect, text in bs:
            y_hit = r.y0 < rect.y1 and r.y1 > rect.y0
            x_hit = r.x0 < rect.x1 - 2 and r.x1 > rect.x0 + 2
            if y_hit and x_hit:
                findings.append(("rule-through-text",
                                 f"p{n} y={r.y0:.0f} crosses {text[:44]!r}"))

    # Two lines fighting for the same space. The discriminator is the Y overlap: lines
    # STACKED inside one cell (a three-line address, a chip's number over its label)
    # share their x range and touch by a point or two of leading, which is normal
    # typography. A real collision is two lines on the SAME row whose columns run into
    # each other - so require the y ranges to overlap by more than half the shorter
    # line's height before calling it.
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            a, b = bs[i][0], bs[j][0]
            ov = a & b
            if ov.width <= 1.5 or ov.height <= 0:
                continue
            if ov.height < 0.5 * min(a.height, b.height):
                continue        # stacked, not colliding
            findings.append(("overlap",
                             f"p{n} {bs[i][1][:26]!r} x {bs[j][1][:26]!r}"))

    # Columns that do not collide but leave no gutter. JasperReports wraps rather than
    # overflows, so a column too narrow for its content never produces an overlap - it
    # produces two cells with no daylight between them, which is a legibility defect the
    # geometry alone will not call. Measured: a healthy page of this house style keeps
    # >12pt between same-row cells; a column one notch too narrow drops to ~4pt.
    for i in range(len(bs)):
        for j in range(len(bs)):
            if i == j:
                continue
            a, b = bs[i][0], bs[j][0]
            y_ov = min(a.y1, b.y1) - max(a.y0, b.y0)
            if y_ov <= 0.5 * min(a.height, b.height):
                continue                      # not the same row
            if not (b.x0 >= a.x1):
                continue                      # b is not to the right of a
            gap = b.x0 - a.x1
            if gap < MIN_GUTTER:
                findings.append(("tight-gutter",
                                 f"p{n} {gap:.1f}pt between {bs[i][1][:24]!r} "
                                 f"and {bs[j][1][:24]!r}"))

    # Anything past the media box is clipped in the viewer and cut off on paper.
    for rect, text in bs:
        if rect.x1 > page.rect.x1 + 0.5 or rect.x0 < page.rect.x0 - 0.5:
            findings.append(("off-page", f"p{n} {text[:44]!r} x1={rect.x1:.0f}"))

    # JasperReports swallows the NPE and prints the word. Never cosmetic.
    for rect, text in bs:
        for token in ("null", "NaN"):
            if token in text.split() or text.strip() == token:
                findings.append(("literal-null", f"p{n} {text[:44]!r}"))
                break

    if verbose:
        print(f"\n--- page {n}  ({len(bs)} blocks, {len(rs)} rules) ---")
        for r in rs:
            print(f"  rule   y={r.y0:7.1f}  x={r.x0:6.1f}..{r.x1:6.1f}")
        for rect, text in bs:
            flat = " / ".join(text.split("\n"))[:88]
            print(f"  text   y={rect.y0:7.1f}  x={rect.x0:6.1f}..{rect.x1:6.1f}  {flat}")
    return findings


def main():
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    path = argv[0]
    verbose = "--layout" in argv
    only = None
    if "--page" in argv:
        only = int(argv[argv.index("--page") + 1])

    doc = fitz.open(path)
    print(f"{path}: {doc.page_count} page(s), {doc[0].rect.width:.0f}x{doc[0].rect.height:.0f}pt")

    all_findings = []
    for i, page in enumerate(doc, 1):
        if only and i != only:
            continue
        all_findings += check_page(page, i, verbose)

    print("")
    if not all_findings:
        print("no geometric defects: no rules through text, no overlapping or "
              "gutterless cells, nothing off-page, no literal null")
        return 0
    grouped = collections.OrderedDict()
    for kind, msg in all_findings:
        grouped.setdefault(kind, []).append(msg)
    for kind, msgs in grouped.items():
        print(f"{kind}  ({len(msgs)})")
        for m in msgs[:12]:
            print(f"   {m}")
        if len(msgs) > 12:
            print(f"   ... and {len(msgs) - 12} more")
    return 1


def _selftest():
    """The overlap predicate is the whole value of this script; keep it honest."""
    def collides(a, b):
        ov = a & b
        return (ov.width > 1.5 and ov.height > 0
                and ov.height >= 0.5 * min(a.height, b.height))
    stacked_a, stacked_b = fitz.Rect(50, 100, 200, 110), fitz.Rect(50, 109, 200, 119)
    assert not collides(stacked_a, stacked_b), "stacked lines must not be flagged"
    same_row = fitz.Rect(50, 100, 210, 110), fitz.Rect(205, 100, 350, 110)
    assert collides(*same_row), "colliding columns must be flagged"
    apart = fitz.Rect(50, 100, 190, 110), fitz.Rect(200, 100, 350, 110)
    assert not collides(*apart), "adjacent columns must not be flagged"

    def gutter(a, b):
        y_ov = min(a.y1, b.y1) - max(a.y0, b.y0)
        return (y_ov > 0.5 * min(a.height, b.height) and b.x0 >= a.x1
                and b.x0 - a.x1 < MIN_GUTTER)
    assert gutter(fitz.Rect(50, 100, 196, 110), fitz.Rect(200, 100, 350, 110)), \
        "a 4pt gutter must be flagged"
    assert not gutter(fitz.Rect(50, 100, 188, 110), fitz.Rect(200, 100, 350, 110)), \
        "a 12pt gutter must not be flagged"

    def strike(rule_r, text_r):
        return (rule_r.y0 < text_r.y1 and rule_r.y1 > text_r.y0
                and rule_r.x0 < text_r.x1 - 2 and rule_r.x1 > text_r.x0 + 2)
    assert strike(fitz.Rect(36, 104, 559, 104.5), fitz.Rect(50, 100, 200, 110)), \
        "a rule inside the text box must be flagged"
    assert not strike(fitz.Rect(36, 112, 559, 112.5), fitz.Rect(50, 100, 200, 110)), \
        "a rule below the text box must not be flagged"
    print("selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else main())
