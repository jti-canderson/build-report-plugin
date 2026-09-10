"""
Template: ESERIES SUMMARY  (the folder-view look)

A print copy of an eSeries folder view - the Case Summary screen and its relatives.
Flag banners, the two-column header block, then grey section bands each with their own
column grid. Use it when someone hands you a SCREENSHOT of an eSeries screen and wants
the report to look like that, which is a normal and complete answer.

HOW IT DIFFERS FROM A (Record Summary): A is the JTI house document - masthead, stat
tiles, navy headings. This one deliberately imitates the application. Same underlying
row contract, different clothes. Pick A when it should look like a JTI report; pick this
when it should look like the screen it came from.

WHAT IT CANNOT CARRY OVER, because a PDF is paper: hover, the Filter box, the
expand/collapse carets actually collapsing, clicking a tab, sorting a header. The
carets, funnels and folder ARE drawn - they just do nothing. Everything visual
reproduces: colours, banners, badges, link-blue text, the grey bands.

ICONS ARE DRAWN, NEVER TYPED. Tested against the PDF itself 2026-09-04: every caret,
triangle, funnel and emoji (U+25BC, U+25BE, U+2304, U+2207, U+1F53D, U+1F4C1, U+1F4CD) is
DROPPED SILENTLY at PDF export. Only U+2022, U+2013 and plain ASCII survive. Worse, the
local raster SHOWS the dropped ones - it draws through AWT while the PDF goes through
WinAnsi - so a typed caret looks perfect in verification and is missing in the document
that ships. The folder, the collapse carets and the column funnels are therefore all
rectangles. jti_style refuses a non-WinAnsi literal at generate time; do not work around
it by putting the character in a $F{} expression instead.

ROW CONTRACT - what the Groovy rule must put in `_data`:

    one flat List<Map>, every row carrying:
      section     the section key, e.g. "PERSONNEL"        (drives grouping)
      <field>     that section's column values, as Strings
    plus, on EVERY row (they are read in the title band, which renders once from the
    first row, so a null here blanks the header for the whole report):
      recTitle    "Felony Citation ~ 26-132"
      recSubtitle "Mick Foley"
      recStatus   "Open"
      recSlug     the footer slug
      bn1..bnN    banner text. EMPTY STRING HIDES THAT BANNER - that is the switch.
      <header>    one field per HEADER_COLS entry

Sections are ordered by SECTIONS, so the rule must emit rows in that order - Jasper
groups consecutive rows and does not sort. A section with no rows never prints, header
and all, which is what the screen does when a panel is empty.

SUB-ROWS - build(subrows=True), OPT-IN and off by default
    An eSeries TREE panel (Pay Plans, Transactions) and a grid whose row carries a
    detail block too wide for the column set both need the same thing: a row that is
    NOT the column grid, but one indented full-width line underneath the row above it.

    Passing subrows=True adds two fields to the contract and a second detail layout:
      rowKind   "row" for a normal gridded row, "sub" for an indented full-width line.
                REQUIRED ON EVERY ROW once subrows is on - a null here prints neither
                layout and the row silently vanishes.
      subText   the full-width line's text. Read only when rowKind is "sub".
      subDepth  "1" or "2" - indent level, so a tree can show two generations.
                Optional; anything not "2" is treated as depth 1.

    It is OFF by default and adds no fields when off, so a report already built on this
    template is unaffected. Do not turn it on for a flat grid - a rule that then forgets
    to stamp rowKind loses every row with no error anywhere.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jti_style as S  # noqa: E402

NAME = "JTI_ESeries_Summary"

# --------------------------------------------------------------- screen palette
# Sampled from the application, not from the house palette, because imitating the
# screen IS the point of this template. The house tokens still drive the footer.
BAND = "#EFF1F3"     # the grey section bar
BANDLINE = "#DCE0E5"
LINK = "#1F5FAF"     # the blue of every clickable label on the screen
HDRLBL = "#1F5FAF"   # header block labels are the same blue
SEP = "#E4E7EB"      # row separators, lighter than the house RULE

CW = S.COL_W
BANNER_H, BANNER_GAP = 17, 5
HDR_LINE = 13        # a line in the header block
SEC_BAND_H = 18      # the grey bar
COLHDR_H = 16
ROW_H = 22
GUTTER, TOP_PAD = 5, 4
RIGHT_GUTTER = 8      # see _rw(): keeps a right-aligned column off its neighbour
SUB_H = 16            # an indented full-width line
SUB_INDENT = 18       # depth 1; depth 2 doubles it

# (text field, fill, text colour). Empty field value hides the banner.
BANNERS = [
    ("bn1", "#4B37B8", "#FFFFFF"),
    ("bn2", "#FFE500", "#1A1D21"),
]

# Two columns of label/value pairs, right of the case title.
# (x, label column width, [(label, field), ...])
HEADER_COLS = [
    (238, 56, [("Received", "hReceived"), ("Next", "hNext"),
               ("Attorney", "hAttorney"), ("Defense", "hDefense")]),
    (368, 84, [("Jurisdiction", "hJurisdiction"), ("Vertical Unit", "hVerticalUnit"),
               ("Related Details", "hRelated"), ("Crime Category", "hCrimeCategory"),
               ("Location", "hLocation")]),
]

# (section key, heading, [(column label, relative weight[, align, field]), ...])
SECTIONS = [
    ("DEFENDANT", "Defendant", [
        ("Type", 20, "Left", "dType"), ("Person", 22, "Left", "dPerson"),
        ("Contact Information", 38, "Left", "dContact"),
        ("Appearance", 20, "Left", "dAppearance")]),
    ("ASSETS", "Assets", [
        ("Date", 14, "Left", "aDate"), ("Type", 14, "Left", "aType"),
        ("Asset Name", 20, "Left", "aName"), ("Asset Number", 18, "Left", "aNumber"),
        ("Description", 18, "Left", "aDescription"), ("Memo", 16, "Left", "aMemo")]),
    ("PERSONNEL", "Justice Personnel", [
        ("Role", 22, "Left", "pRole"), ("Person", 24, "Left", "pPerson"),
        ("Status", 16, "Left", "pStatus"), ("Assigned", 19, "Left", "pAssigned"),
        ("Removed", 19, "Left", "pRemoved")]),
    ("CASENUMBERS", "Case Numbers", [
        ("Type", 20, "Left", "nType"), ("Number", 20, "Left", "nNumber"),
        ("Agency", 34, "Left", "nAgency"), ("Active", 13, "Left", "nActive"),
        ("Lead", 13, "Left", "nLead")]),
    ("STATUSHISTORY", "Status History", [
        ("Status", 30, "Left", "sStatus"), ("Begin Date", 25, "Left", "sBegin"),
        ("End Date", 25, "Left", "sEnd"), ("Note", 20, "Left", "sNote")]),
    ("REVIEW", "Case Review", [
        ("Type", 26, "Left", "rType"), ("Content", 40, "Left", "rContent"),
        ("Status", 17, "Left", "rStatus"), ("Status Date", 17, "Left", "rDate")]),
]


def _rw(w, align):
    """Usable width for a cell, given its alignment.

    A Right-aligned value sits hard against its column's right edge, and the next
    column's Left-aligned value starts 2pt into its own - so the two end up ~4pt
    apart and read as one run of text ("$4,882.50 Active", "$2,000.00 04/15/2026").
    Narrowing a right-aligned box by a gutter pushes its text left into real space
    without touching any column's share of the width, so the grid still adds to 100%.
    """
    return w - RIGHT_GUTTER if align == "Right" else w


def _cols(sec):
    return S.parse_cols([(c[0], c[1], (c[2] if len(c) > 2 else "Left"),
                          (c[3] if len(c) > 3 else None)) for c in sec[2]])


def _folder(x, y):
    """The folder glyph, DRAWN. U+1F4C1 is dropped silently at PDF export."""
    return [S.rect(x, y + 2, 6, 3, "#E8B84B"),          # the tab
            S.rect(x, y + 4, 14, 9, "#F2C75C")]         # the body


def _banners():
    o, x = [], 0
    for field, fill, fg in BANNERS:
        w = 150
        when = f'$F{{{field}}} != null && !$F{{{field}}}.isEmpty()'
        o.append(S.rect(x, 0, w, BANNER_H, fill, when=when))
        o.append(S.text(x, 1, w, BANNER_H - 2, f"$F{{{field}}}", size=8, bold=True,
                        color=fg, align="Center", when=when))
        x += w + BANNER_GAP
    return o


def _title():
    y0 = BANNER_H + 8
    o = _banners()
    o += _folder(0, y0 + 1)
    o.append(S.text(18, y0 - 4, 230, 22, "$F{recTitle}", size=14, bold=True, color=S.INK))
    o.append(S.text(18, y0 + 18, 230, 16, "$F{recSubtitle}", size=10, color=S.INK))
    o.append(S.text(18, y0 + 33, 230, 12, "$F{recStatus}", size=8, bold=True, color=LINK))
    for i, (x, lw, pairs) in enumerate(HEADER_COLS):
        # A value's box ends where the NEXT column begins. Sizing it to CW - x - lw
        # instead lets column one's value run underneath column two, and the overlap
        # only shows when a value happens to be long.
        right = HEADER_COLS[i + 1][0] if i + 1 < len(HEADER_COLS) else CW
        vw = right - x - lw - 4
        yy = y0 - 2
        for lbl, field in pairs:
            # S.label() uppercases - that is the JTI micro-type. The screen uses plain
            # sentence case in link blue, so this is a static, not a label.
            o.append(S.static(x, yy, lw, HDR_LINE, lbl, size=7, color=HDRLBL))
            o.append(S.text(x + lw, yy, vw, HDR_LINE, f"$F{{{field}}}",
                            size=7, color=S.INK))
            yy += HDR_LINE
    # Derive the band height from the TALLEST header column, never a constant. A
    # column gaining a fifth pair silently pushes its last line past the band, and
    # JasperReports fails the whole compile on it rather than clipping.
    deepest = max(len(pairs) for _, _, pairs in HEADER_COLS)
    h = max(y0 + 52, y0 - 2 + HDR_LINE * deepest + 10)
    o.append(S.line(0, h - 6, CW, S.RULE))
    return f"""<title>
<band height="{h}" splitType="Stretch">
{chr(10).join(o)}
</band>
</title>"""


def _section_header():
    """Grey bar + that section's column grid, per section, gated on $F{section}."""
    o = []
    for sec in SECTIONS:
        key, heading = sec[0], sec[1]
        when = f'$F{{section}}.equals("{key}")'
        inner = [S.rect(0, 0, CW, SEC_BAND_H, BAND),
                 S.line(0, SEC_BAND_H, CW, BANDLINE),
                 # the collapse caret - DRAWN. Every caret character is outside
                 # WinAnsi and is dropped silently from the PDF while still showing in
                 # the local PNG, so typing one ships an invisible icon.
                 S.tri_down(5, 7, 7, 4, "#8A9099"),
                 S.static(16, 1, CW - 20, SEC_BAND_H - 2, heading, size=9, bold=True,
                          color=S.INK)]
        cols = _cols(sec)
        ws = S.widths([c["weight"] for c in cols])
        yy = SEC_BAND_H + 3
        for i, (x, w, c) in enumerate(zip(S.xs_of(ws), ws, cols)):
            # the funnel sits on the first column only, as it does on the screen
            if i == 0:
                inner.append(S.tri_down(x + 2, yy + 4, 7, 4, LINK))
            # The heading takes its COLUMN'S alignment, not Left. A right-aligned
            # money column under a left-aligned heading puts the heading at one end
            # of the column and every value at the other, which reads as though the
            # heading belongs to the column beside it. The funnel indent applies to
            # the first column only and would fight a right-aligned label, so the
            # first column stays Left regardless.
            hal = "Left" if i == 0 else c["align"]
            inner.append(S.static(x + (11 if i == 0 else 0), yy,
                                  _rw(w, hal) - (11 if i == 0 else 0), COLHDR_H - 4,
                                  c["label"], size=8, bold=True, color=S.INK, pad=2,
                                  align=hal))
        inner.append(S.line(0, yy + COLHDR_H - 2, CW, S.RULE_HI))
        o.append(S.frame(0, 0, CW, SEC_BAND_H + COLHDR_H + 4, "\n".join(inner), when=when))
    return f"""<groupHeader>
<band height="{SEC_BAND_H + COLHDR_H + 6}" splitType="Stretch">
{chr(10).join(o)}
</band>
</groupHeader>"""


def _detail(subrows=False):
    """No frames - a <frame> does not pass a stretching child's height up to the band,
    so a wrapped cell overflows it and the separator is drawn through the next row."""
    o = []
    # With subrows on, the gridded layout must ALSO test rowKind, or a "sub" row prints
    # both layouts on top of each other. The test is on the row field, not on a
    # variable, because a band sees only the row currently being rendered.
    grid_gate = '$F{rowKind}.equals("row") && ' if subrows else ''
    for sec in SECTIONS:
        key = sec[0]
        cols = _cols(sec)
        when = f'{grid_gate}$F{{section}}.equals("{key}")'
        ws = S.widths([c["weight"] for c in cols])
        for i, (x, w, c) in enumerate(zip(S.xs_of(ws), ws, cols)):
            o.append(S.text(x, TOP_PAD, _rw(w, c["align"]),
                            ROW_H - GUTTER - TOP_PAD,
                            f"$F{{{c['field']}}}", size=8,
                            # first column is the row's link on the screen
                            color=LINK if i == 0 else S.INK,
                            pad=2, valign="Top", stretch=True, align=c["align"],
                            grow=True, when=when))
    if subrows:
        # One indented, full-width, wrapping line. Two depths, gated separately rather
        # than computed, because a printWhenExpression cannot set geometry - only
        # decide whether a box prints.
        deep = '$F{subDepth}.equals("2")'
        for depth, indent in ((1, SUB_INDENT), (2, SUB_INDENT * 2)):
            test = deep if depth == 2 else '!' + deep
            gate = '$F{rowKind}.equals("sub") && ' + test
            o.append(S.text(indent, TOP_PAD, CW - indent, SUB_H - TOP_PAD,
                            "$F{subText}", size=7, color=S.MUTED, pad=2,
                            valign="Top", stretch=True, grow=True, when=gate))
    # The row separator belongs to a GRIDDED row only. Drawn under a sub-row it cuts
    # between a parent and its own child, which reads as two unrelated records.
    sep = S.line(0, ROW_H - 1, CW, SEP, at_bottom=True,
                 when='$F{rowKind}.equals("row")') if subrows else \
          S.line(0, ROW_H - 1, CW, SEP, at_bottom=True)
    return f"""<detail>
<band height="{ROW_H}" splitType="Stretch">
{chr(10).join(o)}
{sep}
</band>
</detail>"""


def build(sections=None, banners=None, header_cols=None, name=None, params=(),
          meta=None, tiles=None, subrows=False):
    """`meta` and `tiles` are accepted and ignored, so this template is a drop-in for
    the others in scaffold.py and the catalog. This layout has no metadata strip and no
    stat tiles - the header block does that job."""
    global SECTIONS, BANNERS, HEADER_COLS
    SECTIONS = sections or SECTIONS
    BANNERS = banners or BANNERS
    HEADER_COLS = header_cols or HEADER_COLS
    name = name or NAME

    seen = []
    for sec in SECTIONS:
        for c in _cols(sec):
            if c["field"] not in seen:
                seen.append(c["field"])
    fields = (["section", "recTitle", "recSubtitle", "recStatus", "recSlug"]
              + (["rowKind", "subText", "subDepth"] if subrows else [])
              + [b[0] for b in BANNERS]
              + [f for _, _, pairs in HEADER_COLS for _, f in pairs]
              + seen)

    body = f"""<group name="Section" isStartNewColumn="false" keepTogether="true">
<groupExpression><![CDATA[$F{{section}}]]></groupExpression>
{_section_header()}
<groupFooter><band height="10" splitType="Stretch"/></groupFooter>
</group>
{_title()}
{_detail(subrows)}
{S.footer(CW, '$F{recSlug}')}
<summary>
<band height="26" splitType="Stretch">
<printWhenExpression><![CDATA[$V{{REPORT_COUNT}} == 0]]></printWhenExpression>
{S.static(0, 6, CW, 14, "No records.", size=9, color=S.MUTED)}
</band>
</summary>"""
    return S.document(name, body, fields=fields, params=params)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "out" / f"{NAME}.jrxml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    print(f"wrote {out.name}  ({len(SECTIONS)} sections)")
