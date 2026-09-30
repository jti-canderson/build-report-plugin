"""
Template: WIDE TABLE  (landscape)

Letter turned sideways - 792x612, 752 usable. For the grids that simply do not fit
portrait: eight or nine narrow columns, usually a financial breakdown read across.
VOCA, Payments by Obligation Type, and any "give me everything about each payment"
request.

Portrait first. Landscape costs a reader something - it will not print in a stack
with the rest of a packet, and it reads badly on a phone. Reach for it only once the
column arithmetic genuinely will not close at 572. A column list that fits portrait
belongs in `tabular_list`.

ROW CONTRACT - `_data` is one flat List<Map>, every row carrying:
    c1..cN      the column values, left to right, as Strings
    amt         the money column again, BARE NUMERIC, no $ and no commas
                (drives the grand total; emit "0" on rows that carry no money)
    rptTitle    the masthead line
    rptSubtitle the criteria echo, e.g. "01/01/2026 - 12/31/2026  ·  All agencies"
    rptSlug     the footer slug

The masthead is shorter than the portrait templates' - landscape has 180 fewer points
of height to spend and the table is what the reader came for.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jti_style as S  # noqa: E402

NAME = "JTI_Wide_Table"

# (column label, relative weight, alignment)
COLUMNS = [
    ("Date", 66, "Left"),
    ("Receipt #", 62, "Left"),
    ("Case #", 84, "Left"),
    ("Payer", 108, "Left"),
    ("Obligation Type", 140, "Left"),
    ("Agency", 90, "Left"),
    ("Assessed", 68, "Right"),
    ("Collected", 68, "Right"),
    ("Balance", 66, "Right"),
]

CW = S.LAND_COL_W          # 752
ROW_H, HDR_H = 16, 18
# NINE columns, not eleven. At 752pt and 7pt text a column holds roughly 15
# characters; past nine columns realistic values ("Victim Compensation Assessment")
# truncate silently, and widening one column just moves which one clips. If a tenth
# column is genuinely needed, drop the font to 6pt and re-check the raster - do not
# simply add it. jti_style._fits_width() catches a clipped HEADER at generate time;
# row VALUES are unknowable until the fixture renders, so look at every page.
MONEY = "$#,##0.00"


def build(columns=None, name=None, params=(), title=None, subtitle=None, slug=None,
          extra_fields=(), total=None):
    """With no arguments: the sample (nine columns, `amt` grand total), unchanged.

    For a real report, the same keywords as `tabular_list.build()`: `columns` as
    (label, weight, align, field[, cls, pattern, wrap]); `title` / `subtitle` / `slug` as
    raw jrxml expressions (default $F{rptTitle} etc.); `params` declared as given. A grand
    total is printed only when `total` names the rule's BARE NUMERIC money field - a list
    with no money column has nothing to total.
    """
    sample = columns is None
    cols = S.parse_cols(columns or COLUMNS)
    name = name or NAME
    if sample:
        total = "amt"
    title = title or "$F{rptTitle}"
    subtitle = subtitle or "$F{rptSubtitle}"
    slug = slug or "$F{rptSlug}"
    ws = S.widths([c["weight"] for c in cols], total=CW)
    xs = S.xs_of(ws)

    title = f"""<title>
<band height="62" splitType="Stretch">
{S.line(0, 0, CW, S.NAVY, 2.0)}
{S.logo(0, 8, 34, 40)}
{S.label(44, 12, 96, 10, "Journal Technologies   ·   ")}
{S.text(140, 12, 300, 9, slug + ".toUpperCase()", size=6, bold=True, color=S.MUTED)}
{S.text(44, 22, CW - 300, 24, title, size=16, bold=True, color=S.NAVY)}
{S.text(CW - 292, 26, 292, 12, subtitle, size=8, color=S.MUTED, align="Right")}
</band>
</title>"""

    hdr = "\n".join(S.label(x, 4, w, 10, c["label"], pad=3, align=c["align"])
                    for x, w, c in zip(xs, ws, cols))
    col_header = f"""<columnHeader>
<band height="{HDR_H}" splitType="Stretch">
{hdr}
{S.line(0, HDR_H - 2, CW, S.NAVY, 1.5)}
</band>
</columnHeader>"""

    def cell(x, w, c):
        extra = {"pattern": c["pattern"]} if c["pattern"] else {}
        if c["wrap"]:
            extra.update(valign="Top", stretch=True, grow=True)
        return S.text(x, 0, w, ROW_H, f"$F{{{c['field']}}}", size=7, color=S.INK, pad=3,
                      align=c["align"], **extra)
    wrap = any(c["wrap"] for c in cols)
    cells = "\n".join(cell(x, w, c) for x, w, c in zip(xs, ws, cols))
    band = (S.rect(0, 0, CW, ROW_H, S.FILL, when='$V{REPORT_COUNT} % 2 == 0', grow=True)
            if wrap else S.rect(0, 0, CW, ROW_H, S.FILL, when='$V{REPORT_COUNT} % 2 == 0'))
    rule = S.line(0, ROW_H - 1, CW, S.RULE, at_bottom=True) if wrap else S.line(0, ROW_H - 1, CW, S.RULE)
    detail = f"""<detail>
<band height="{ROW_H}" splitType="Stretch">
{band}
{cells}
{rule}
</band>
</detail>"""

    if total:
        # The grand total is an order of magnitude larger than any row value, so it
        # gets the last TWO columns. Sized to the row column it silently clips.
        tx, tw = xs[-2], ws[-2] + ws[-1]
        summary = f"""<summary>
<band height="38" splitType="Stretch">
{S.line(0, 2, CW, S.NAVY, 1.5)}
{S.static(0, 8, 200, 15, "Grand Total", size=10, bold=True, color=S.NAVY, pad=3)}
{S.text(tx, 8, tw, 14, "$V{GrandTotal}", size=9, bold=True, color=S.NAVY,
        align="Right", pad=3, pattern=MONEY)}
{S.static(0, 24, CW, 14, "None recorded.", size=9, color=S.MUTED,
          when='$V{REPORT_COUNT} == 0')}
</band>
</summary>"""
        vars_ = f"""<variable name="GrandTotal" class="java.math.BigDecimal" calculation="Sum">
<variableExpression><![CDATA[new java.math.BigDecimal($F{{{total}}})]]></variableExpression>
</variable>
"""
    else:
        summary = f"""<summary>
<band height="26" splitType="Stretch">
<printWhenExpression><![CDATA[$V{{REPORT_COUNT}} == 0]]></printWhenExpression>
{S.static(0, 6, CW, 14, "None recorded.", size=9, color=S.MUTED)}
</band>
</summary>"""
        vars_ = ""

    body = f"""{vars_}{title}
{col_header}
{detail}
{S.footer(CW, slug)}
{summary}"""
    if sample:
        fields = ["rptTitle", "rptSubtitle", "rptSlug", "amt"] + [c["field"] for c in cols]
    else:
        auto = [f for f, e in (("rptTitle", title), ("rptSubtitle", subtitle),
                               ("rptSlug", slug)) if f"$F{{{f}}}" in e]
        fields = auto + list(extra_fields) + ([total] if total else []) + \
                 [(c["field"], c["cls"]) for c in cols]
    return S.document(name, body, fields=fields, params=params,
                      page_w=S.LAND_W, page_h=S.LAND_H)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "out" / f"{NAME}.jrxml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    ws = S.widths([w for _, w, _ in COLUMNS], total=CW)
    print(f"wrote {out.name}  (landscape {S.LAND_W}x{S.LAND_H}, "
          f"{len(COLUMNS)} columns, widths sum {sum(ws)} == {CW})")
