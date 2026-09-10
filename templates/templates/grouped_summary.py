"""
Template: GROUPED SUMMARY

Rows banded under a group heading, a subtotal per group, a grand total at the end.
Payments by Obligation Type, Restitution and DA Fees Collected, Annual Report by
Collecting Agency.

ROW CONTRACT - `_data` is one flat List<Map>, every row carrying:
    grp         the group key, e.g. "Tulsa County DA"   (drives grouping)
    c1..c4      the column values as Strings
    amt         the money value again, as a BARE NUMERIC STRING, no $ and no commas
    rptTitle / rptSubtitle / rptSlug   as in tabular_list

`amt` exists because Jasper cannot sum "$1,875.50". The rule emits the number twice:
once formatted for display (c3), once bare for arithmetic (amt). Get this wrong and
the subtotals silently read 0.00 while every row looks right.

The rule must emit rows already sorted by `grp` - Jasper groups consecutive rows.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jti_style as S  # noqa: E402

NAME = "JTI_Grouped_Summary"

COLUMNS = [
    ("Obligation Type", 200, "Left"),
    ("Count", 80, "Right"),
    ("Collected", 146, "Right"),
    ("Outstanding", 146, "Right"),
]
GROUP_LABEL = "Collecting Agency"

CW = S.COL_W
ROW_H, HDR_H = 17, 18
MONEY = "$#,##0.00"
# f-strings cannot hold a backslash, so the quoted expression lives here
ENTRIES = '$V{GrpCount} + ($V{GrpCount} == 1 ? " entry" : " entries")'


def build():
    ws = S.widths([w for _, w, _ in COLUMNS])
    xs = S.xs_of(ws)

    title = f"""<title>
<band height="74" splitType="Stretch">
{S.line(0, 0, CW, S.NAVY, 2.0)}
{S.logo(0, 10, 40, 48)}
{S.label(52, 14, 96, 10, "Journal Technologies   ·   ")}
{S.text(148, 14, CW - 148, 9, "$F{rptSlug}.toUpperCase()", size=6, bold=True, color=S.MUTED)}
{S.text(52, 26, CW - 52, 25, "$F{rptTitle}", size=17, bold=True, color=S.NAVY)}
{S.text(52, 50, CW - 52, 12, "$F{rptSubtitle}", size=8, color=S.MUTED)}
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

    group = f"""<group name="Grp" keepTogether="true">
<groupExpression><![CDATA[$F{{grp}}]]></groupExpression>
<groupHeader>
<band height="24" splitType="Stretch">
{S.label(0, 4, 120, 16, GROUP_LABEL)}
{S.text(0, 12, CW - 110, 15, "$F{grp}", size=10, bold=True, color=S.NAVY)}
{S.line(0, 23, CW, S.RULE_HI)}
</band>
</groupHeader>
<groupFooter>
<band height="26" splitType="Stretch">
{S.line(0, 0, CW, S.RULE_HI)}
{S.static(xs[0], 4, ws[0] + ws[1], 12, "Subtotal", size=8, bold=True, color=S.INK, pad=3)}
{S.text(xs[2], 4, ws[2], 12, "$V{GrpTotal}", size=8, bold=True, color=S.INK,
        align="Right", pad=3, pattern=MONEY)}
{S.text(xs[3], 4, ws[3], 12, ENTRIES, size=7, color=S.MUTED, align="Right", pad=3)}
</band>
</groupFooter>
</group>"""

    cells = "\n".join(
        S.text(x, 0, w, ROW_H, f"$F{{c{i}}}", size=8, color=S.INK, pad=3, align=a)
        for x, w, (_, _, a), i in zip(xs, ws, COLUMNS, range(1, len(COLUMNS) + 1)))
    detail = f"""<detail>
<band height="{ROW_H}" splitType="Stretch">
{cells}
{S.line(0, ROW_H - 1, CW, S.RULE)}
</band>
</detail>"""

    summary = f"""<summary>
<band height="40" splitType="Stretch">
{S.line(0, 2, CW, S.NAVY, 1.5)}
{S.static(xs[0], 8, ws[0] + ws[1], 15, "Grand Total", size=10, bold=True, color=S.NAVY, pad=3)}
{S.text(xs[2], 8, ws[2], 15, "$V{GrandTotal}", size=10, bold=True, color=S.NAVY,
        align="Right", pad=3, pattern=MONEY)}
{S.static(0, 24, CW, 14, "None recorded.", size=9, color=S.MUTED,
          when='$V{REPORT_COUNT} == 0')}
</band>
</summary>"""

    vars_ = f"""<variable name="GrpTotal" class="java.math.BigDecimal" resetType="Group" resetGroup="Grp" calculation="Sum">
<variableExpression><![CDATA[new java.math.BigDecimal($F{{amt}})]]></variableExpression>
</variable>
<variable name="GrpCount" class="java.lang.Integer" resetType="Group" resetGroup="Grp" calculation="Count">
<variableExpression><![CDATA[$F{{c1}}]]></variableExpression>
</variable>
<variable name="GrandTotal" class="java.math.BigDecimal" calculation="Sum">
<variableExpression><![CDATA[new java.math.BigDecimal($F{{amt}})]]></variableExpression>
</variable>"""

    body = f"""{vars_}
{group}
{title}
{col_header}
{detail}
{S.footer(CW, '$F{rptSlug}')}
{summary}"""
    fields = ["rptTitle", "rptSubtitle", "rptSlug", "grp", "amt"] + \
             [f"c{i}" for i in range(1, len(COLUMNS) + 1)]
    return S.document(NAME, body, fields=fields)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "out" / f"{NAME}.jrxml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    print(f"wrote {out.name}  ({len(COLUMNS)} columns, grouped on 'grp')")
