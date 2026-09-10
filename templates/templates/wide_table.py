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


def build():
    ws = S.widths([w for _, w, _ in COLUMNS], total=CW)
    xs = S.xs_of(ws)

    title = f"""<title>
<band height="62" splitType="Stretch">
{S.line(0, 0, CW, S.NAVY, 2.0)}
{S.logo(0, 8, 34, 40)}
{S.label(44, 12, 96, 10, "Journal Technologies   ·   ")}
{S.text(140, 12, 300, 9, "$F{rptSlug}.toUpperCase()", size=6, bold=True, color=S.MUTED)}
{S.text(44, 22, CW - 300, 24, "$F{rptTitle}", size=16, bold=True, color=S.NAVY)}
{S.text(CW - 292, 26, 292, 12, "$F{rptSubtitle}", size=8, color=S.MUTED, align="Right")}
</band>
</title>"""

    hdr = "\n".join(S.label(x, 4, w, 10, lbl, pad=3, align=a)
                    for x, w, (lbl, _, a) in zip(xs, ws, COLUMNS))
    col_header = f"""<columnHeader>
<band height="{HDR_H}" splitType="Stretch">
{hdr}
{S.line(0, HDR_H - 2, CW, S.NAVY, 1.5)}
</band>
</columnHeader>"""

    cells = "\n".join(
        S.text(x, 0, w, ROW_H, f"$F{{c{i}}}", size=7, color=S.INK, pad=3, align=a)
        for x, w, (_, _, a), i in zip(xs, ws, COLUMNS, range(1, len(COLUMNS) + 1)))
    detail = f"""<detail>
<band height="{ROW_H}" splitType="Stretch">
{S.rect(0, 0, CW, ROW_H, S.FILL, when='$V{REPORT_COUNT} % 2 == 0')}
{cells}
{S.line(0, ROW_H - 1, CW, S.RULE)}
</band>
</detail>"""

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

    vars_ = """<variable name="GrandTotal" class="java.math.BigDecimal" calculation="Sum">
<variableExpression><![CDATA[new java.math.BigDecimal($F{amt})]]></variableExpression>
</variable>"""

    body = f"""{vars_}
{title}
{col_header}
{detail}
{S.footer(CW, '$F{rptSlug}')}
{summary}"""
    fields = ["rptTitle", "rptSubtitle", "rptSlug", "amt"] + \
             [f"c{i}" for i in range(1, len(COLUMNS) + 1)]
    return S.document(NAME, body, fields=fields,
                      page_w=S.LAND_W, page_h=S.LAND_H)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "out" / f"{NAME}.jrxml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    ws = S.widths([w for _, w, _ in COLUMNS], total=CW)
    print(f"wrote {out.name}  (landscape {S.LAND_W}x{S.LAND_H}, "
          f"{len(COLUMNS)} columns, widths sum {sum(ws)} == {CW})")
