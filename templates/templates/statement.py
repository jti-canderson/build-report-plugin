"""
Template: STATEMENT / DOCUMENT

A single-page document addressed to somebody: from/to blocks, a document number and
date, line items, a total, a method line. Receipt, Voucher Payee Statement, Official
Depository Ticket.

Unlike the list templates this one is a piece of correspondence. It reads as a
document, not a data dump, so the masthead is quieter and the totals are loud.

ROW CONTRACT - `_data` is one flat List<Map>, one row per line item, EVERY row also
carrying the document-level values (they are read in the title band, which sees only
the first row):
    c1..c4      line item: date, description, note, amount
    docNo, docDate
    toName, toAddr, fromName, fromAddr      \\n inside an address is honoured
    totalLabel, totalValue, methodLabel, methodValue
    rptTitle, rptSlug
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jti_style as S  # noqa: E402

NAME = "JTI_Statement"

COLUMNS = [
    ("Date", 80, "Left"),
    ("Description", 210, "Left"),
    ("Reference", 180, "Left"),
    ("Amount", 102, "Right"),
]

CW = S.COL_W
ROW_H, HDR_H = 18, 18


def build():
    ws = S.widths([w for _, w, _ in COLUMNS])
    xs = S.xs_of(ws)
    half = CW // 2 - 10

    title = f"""<title>
<band height="196" splitType="Stretch">
{S.line(0, 0, CW, S.NAVY, 2.0)}
{S.logo(0, 12, 40, 48)}
{S.text(52, 20, 260, 22, "$F{rptTitle}", size=18, bold=True, color=S.NAVY)}
{S.label(CW - 200, 18, 90, 8, "Document No.", align="Right")}
{S.text(CW - 200, 28, 90, 12, "$F{docNo}", size=9, color=S.INK, align="Right")}
{S.label(CW - 100, 18, 100, 8, "Date", align="Right")}
{S.text(CW - 100, 28, 100, 12, "$F{docDate}", size=9, color=S.INK, align="Right")}
{S.line(0, 68, CW, S.RULE)}
{S.label(0, 78, half, 8, "From")}
{S.text(0, 90, half, 12, "$F{fromName}", size=9, bold=True, color=S.INK)}
{S.text(0, 104, half, 26, "$F{fromAddr}", size=8, color=S.MUTED, valign="Top", stretch=True)}
{S.label(CW - half, 78, half, 8, "To")}
{S.text(CW - half, 90, half, 12, "$F{toName}", size=9, bold=True, color=S.INK)}
{S.text(CW - half, 104, half, 26, "$F{toAddr}", size=8, color=S.MUTED, valign="Top", stretch=True)}
{S.line(0, 140, CW, S.RULE)}
{S.rect(0, 150, CW, 40, S.FILL)}
{S.text(14, 160, 180, 8, "$F{totalLabel}.toUpperCase()", size=6, bold=True, color=S.MUTED)}
{S.text(14, 168, 180, 20, "$F{totalValue}", size=14, bold=True, color=S.NAVY)}
{S.text(CW - 214, 160, 200, 8, "$F{methodLabel}.toUpperCase()", size=6, bold=True, color=S.MUTED, align="Right")}
{S.text(CW - 214, 170, 200, 14, "$F{methodValue}", size=10, color=S.INK, align="Right")}
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
        S.text(x, 0, w, ROW_H, f"$F{{c{i}}}", size=8, color=S.INK, pad=3, align=a)
        for x, w, (_, _, a), i in zip(xs, ws, COLUMNS, range(1, len(COLUMNS) + 1)))
    detail = f"""<detail>
<band height="{ROW_H}" splitType="Stretch">
{cells}
{S.line(0, ROW_H - 1, CW, S.RULE)}
</band>
</detail>"""

    summary = f"""<summary>
<band height="70" splitType="Stretch">
{S.static(0, 8, CW, 12, "None recorded.", size=9, color=S.MUTED,
          when='$V{REPORT_COUNT} == 0')}
{S.line(CW - 240, 46, 220, S.RULE_HI)}
{S.label(CW - 240, 50, 220, 8, "Authorised Signature")}
</band>
</summary>"""

    body = f"""{title}
{col_header}
{detail}
{S.footer(CW, '$F{rptSlug}')}
{summary}"""
    fields = ["rptTitle", "rptSlug", "docNo", "docDate", "toName", "toAddr",
              "fromName", "fromAddr", "totalLabel", "totalValue", "methodLabel",
              "methodValue"] + [f"c{i}" for i in range(1, len(COLUMNS) + 1)]
    return S.document(NAME, body, fields=fields)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "out" / f"{NAME}.jrxml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    print(f"wrote {out.name}  ({len(COLUMNS)} line-item columns)")
