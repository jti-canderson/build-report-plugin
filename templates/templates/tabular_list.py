"""
Template: TABULAR LIST

The workhorse. A criteria search over a date range, one row per record, one flat
table that runs for as many pages as it needs. Payments Report, Past Due Financial
Obligations, Annual Report by Collecting Agency, Age Caseload.

ROW CONTRACT - `_data` is one flat List<Map>, every row carrying:
    c1..cN      the column values, left to right, as Strings
    rptTitle    the masthead line
    rptSubtitle the criteria echo, e.g. "01/01/2026 - 12/31/2026  ·  All agencies"
    rptSlug     the footer slug

Echo the criteria in `rptSubtitle` on every report. A total with no visible date
range is the single most common thing a client queries back.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jti_style as S  # noqa: E402

NAME = "JTI_Tabular_List"

# (label, weight, align[, field, class, pattern])
# `field` defaults to c1, c2, ... - fine for a demo, wrong for a real report. Give the
# rule's actual key: reordering a cN list silently changes what every later column means.
COLUMNS = [
    ("Date", 62, "Left"),
    ("Receipt #", 70, "Left"),
    ("Payer", 130, "Left"),
    ("Obligation Type", 140, "Left"),
    ("Agency", 90, "Left"),
    ("Amount", 80, "Right"),
]

CW = S.COL_W
ROW_H, HDR_H = 17, 18


def build(columns=None, name=None, params=(), title=None, subtitle=None, slug=None,
          extra_fields=()):
    """`title` / `subtitle` / `slug` are raw jrxml expressions.

    They default to $F{rptTitle} etc., which means the RULE must emit them on every
    row. A report whose rule already exists should instead pass $P{...} expressions
    built from the parameters it already receives - then the template drops onto the
    live rule with no change to the Groovy at all.
    """
    cols = S.parse_cols(columns or COLUMNS)
    name = name or NAME
    title = title or "$F{rptTitle}"
    subtitle = subtitle or "$F{rptSubtitle}"
    slug = slug or "$F{rptSlug}"
    ws = S.widths([c["weight"] for c in cols])
    xs = S.xs_of(ws)

    title = f"""<title>
<band height="74" splitType="Stretch">
{S.line(0, 0, CW, S.NAVY, 2.0)}
{S.logo(0, 10, 40, 48)}
{S.label(52, 14, 96, 10, "Journal Technologies   ·   ")}
{S.text(148, 14, CW - 148, 9, slug + ".toUpperCase()", size=6, bold=True, color=S.MUTED)}
{S.text(52, 26, CW - 52, 25, title, size=17, bold=True, color=S.NAVY)}
{S.text(52, 50, CW - 52, 12, subtitle, size=8, color=S.MUTED, stretch=False)}
</band>
</title>"""

    hdr = "\n".join(
        S.label(x, 4, w, 10, c["label"], pad=3, align=c["align"])
        for x, w, c in zip(xs, ws, cols))
    col_header = f"""<columnHeader>
<band height="{HDR_H}" splitType="Stretch">
{hdr}
{S.line(0, HDR_H - 2, CW, S.NAVY, 1.5)}
</band>
</columnHeader>"""

    # A cell wider than its column is truncated silently. Any column marked wrap=True
    # grows instead, and every other cell in the row grows with it so the zebra band
    # and the rule stay square.
    cells = "\n".join(
        S.text(x, 0, w, ROW_H, f"$F{{{c['field']}}}", size=8, color=S.INK, pad=3,
               align=c["align"], pattern=c["pattern"], valign="Top",
               stretch=c["wrap"], grow=True)
        for x, w, c in zip(xs, ws, cols))
    detail = f"""<detail>
<band height="{ROW_H}" splitType="Stretch">
{S.rect(0, 0, CW, ROW_H, S.FILL, when='$V{REPORT_COUNT} % 2 == 0', grow=True)}
{cells}
{S.line(0, ROW_H - 1, CW, S.RULE, at_bottom=True)}
</band>
</detail>"""

    body = f"""{title}
{col_header}
{detail}
{S.footer(CW, slug)}
<summary>
<band height="26" splitType="Stretch">
<printWhenExpression><![CDATA[$V{{REPORT_COUNT}} == 0]]></printWhenExpression>
{S.static(0, 6, CW, 14, "None recorded.", size=9, color=S.MUTED)}
</band>
</summary>"""
    # only declare the masthead fields when the masthead actually reads them
    auto = [f for f, e in (("rptTitle", title), ("rptSubtitle", subtitle),
                           ("rptSlug", slug)) if f"$F{{{f}}}" in e]
    fields = auto + list(extra_fields) + [(c["field"], c["cls"]) for c in cols]
    return S.document(name, body, fields=fields, params=params)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "out" / f"{NAME}.jrxml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    print(f"wrote {out.name}  ({len(COLUMNS)} columns, widths sum "
          f"{sum(S.widths([c[1] for c in COLUMNS]))} == {CW})")
