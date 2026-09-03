#!/usr/bin/env python3
"""Scaffold for an OKDAC/eSeries report .jrxml.

Copy this next to the report, rename it, and fill in FIELDS, the grids and
the bands. It runs as-is and emits a valid one-section report.

Design notes (the house style - see references/jrxml-layout.md):

  One visual system, applied everywhere. Navy accent, a four-step grey ramp, SansSerif
  at five sizes. No second accent colour, no borders around anything that a hairline
  can separate instead.

  Whitespace over rules. 36pt margins (not 20), 523pt of content, generous band
  heights. The research on report design is unanimous that cramped beats ugly as the
  most common failure, and the first render was cramped.

  Hierarchy by size and colour, not by weight alone. Eyebrow 7pt uppercase muted ->
  document title 19pt ink -> section 10pt uppercase accent -> column head 6.5pt
  uppercase muted -> body 8.5pt -> secondary 7pt muted.

  Editorial, not spreadsheet. Sentence conditions render as one prose line each
  ("Community Service - $250.00 - 15 Days - Active") rather than a five-column grid.
  A page of nested tables is the thing that makes these reports look like a database
  dump.

Geometry is declared as (x, width) grids and asserted, so a future edit cannot
reintroduce an overlap. Content width is 523.
"""
import uuid, xml.dom.minidom, sys, os

# ---- brand mark --------------------------------------------------------------------
# The Journal Technologies "J", carried inline as base64 so the .jrxml is self-contained
# and the server needs no network access or file share to render it. This is the corpus
# convention: existing OKDAC reports embed the same PNG and decode it with
# commons-codec Base64. Master copy lives in the jasper-reports skill's assets/.
LOGO_W, LOGO_H = 32, 48          # 2:3, the mark's natural aspect - do not distort
def _load_logo():
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(here, "journal_mark.b64"),
              os.path.expanduser("~/.claude/skills/jasper-reports/assets/journal_mark.b64")):
        if os.path.exists(c):
            return open(c).read().strip()
    raise SystemExit("journal_mark.b64 not found next to this script or in the skill assets")
LOGO_B64 = _load_logo()

W = 523
GAP = 4

def check(name, cells):
    end = 0
    for i, (x, w) in enumerate(cells):
        assert w > 0, f"{name}: cell {i} width {w}"
        assert x >= end, f"{name}: cell {i} starts at {x}, previous ended at {end}"
        if i:
            assert x - end >= GAP, f"{name}: cell {i} gap {x-end} < {GAP}"
        end = x + w
    assert end <= W, f"{name}: row ends at {end} > {W}"
    return cells

# ---- grids -------------------------------------------------------------------------
# Declare every column row here and let check() assert it. Replace with your own.
G_META = check("META", [(0, 127), (131, 127), (262, 127), (393, 127)])
G_CHIP = check("CHIP", [(0, 166), (178, 166), (356, 166)])
G_ROW  = check("ROW",  [(0, 30), (36, 215), (257, 66), (329, 54), (389, 134)])
G_FOOT = check("FOOT", [(0, 180), (186, 150), (343, 180)])

# ---- palette -----------------------------------------------------------------------
ACCENT   = "#153E75"   # navy: authoritative, reads as a legal document
INK      = "#111827"   # headings
BODY     = "#1F2937"   # body text
MUTED    = "#6B7280"   # labels, secondary lines
HAIRLINE = "#E5E7EB"   # row separators
RULE     = "#C7D2DE"   # section rules
CHIPBG   = "#F4F6F9"   # summary chip fill

INDENT = 30            # secondary lines hang under the first text column

def U():
    return str(uuid.uuid4())

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def tf(x, y, w, h, expr, *, bold=False, size=8.5, align=None, color=BODY,
       italic=False, when=None, valign=None, spacing=None):
    """A text field. Labels are text fields holding a literal expression - the corpus
    contains no <staticText>, and keeping to that means one element type to reason
    about when a band stretches."""
    f = [f'size="{size}"']
    if bold:
        f.append('isBold="true"')
    if italic:
        f.append('isItalic="true"')
    te_attr = []
    if align:
        te_attr.append(f'textAlignment="{align}"')
    if valign:
        te_attr.append(f'verticalAlignment="{valign}"')
    if spacing:
        te_attr.append(f'lineSpacing="{spacing}"')
    te = f'<textElement {" ".join(te_attr)}><font {" ".join(f)}/></textElement>'
    inner = f"<printWhenExpression><![CDATA[{when}]]></printWhenExpression>" if when else ""
    return (f'<textField isStretchWithOverflow="true" isBlankWhenNull="true">'
            f'<reportElement x="{x}" y="{y}" width="{w}" height="{h}" forecolor="{color}" '
            f'uuid="{U()}">{inner}</reportElement>{te}'
            f'<textFieldExpression><![CDATA[{expr}]]></textFieldExpression></textField>')

def rule(y, color=HAIRLINE, x=0, w=W, when=None):
    inner = f"<printWhenExpression><![CDATA[{when}]]></printWhenExpression>" if when else ""
    return (f'<line><reportElement x="{x}" y="{y}" width="{w}" height="1" '
            f'forecolor="{color}" uuid="{U()}">{inner}</reportElement>'
            f'<graphicElement><pen lineWidth="0.5" lineColor="{color}"/></graphicElement>'
            f'</line>')

def block(x, y, w, h, color, when=None):
    """A filled rectangle - the top accent bar, the party tick, the chip grounds."""
    inner = f"<printWhenExpression><![CDATA[{when}]]></printWhenExpression>" if when else ""
    return (f'<rectangle><reportElement mode="Opaque" x="{x}" y="{y}" width="{w}" '
            f'height="{h}" forecolor="{color}" backcolor="{color}" uuid="{U()}">{inner}'
            f'</reportElement><graphicElement><pen lineWidth="0.0"/></graphicElement>'
            f'</rectangle>')

def notblank(f):
    return f'$F{{{f}}} != null && !$F{{{f}}}.isEmpty()'

def is_section(*names):
    return " || ".join(f'"{n}".equals($F{{section}})' for n in names)

def band(height, content, when=None):
    pw = f"<printWhenExpression><![CDATA[{when}]]></printWhenExpression>" if when else ""
    return f'<band height="{height}" splitType="Stretch">{pw}{content}</band>'

# ---- fields ------------------------------------------------------------------------
# Must match the keys the Groovy rule seeds in its `base` map, exactly.
FIELDS = [
    "section", "panel", "party", "caseNumber", "caseTitle", "county", "today",
    "defendant", "panelCount",
    "colA", "colB", "colC", "colD", "colE",
]

# ---- title band --------------------------------------------------------------------
TX = LOGO_W + 14

t = [block(0, 0, W, 3, ACCENT)]
t.append('<image scaleImage="RetainShape">'
         f'<reportElement x="0" y="10" width="{LOGO_W}" height="{LOGO_H}" uuid="{U()}"/>'
         '<imageExpression><![CDATA[new java.io.ByteArrayInputStream('
         f'Base64.decodeBase64("{LOGO_B64}".getBytes()))]]></imageExpression></image>')
t.append(tf(TX, 14, W - TX, 10, '"JOURNAL TECHNOLOGIES   \u00b7   REPORT NAME"',
            size=7, bold=True, color=MUTED))
t.append(tf(TX, 27, W - TX, 26, '$F{caseTitle}', size=19, bold=True, color=INK))
t.append(rule(62, RULE))
for (x, w), lbl, val in zip(G_META, ["CASE NUMBER", "DEFENDANT", "COUNTY", "PRINTED"],
                            ['$F{caseNumber}', '$F{defendant}', '$F{county}', '$F{today}']):
    t.append(tf(x, 72, w, 9, f'"{lbl}"', size=6.5, bold=True, color=MUTED))
    t.append(tf(x, 83, w, 12, val, size=9, color=INK))
TITLE = band(112, "".join(t))

# ---- panel group header ------------------------------------------------------------
def headings(panel, cols):
    parts = [f'<frame><reportElement x="0" y="34" width="{W}" height="12" uuid="{U()}">'
             f'<printWhenExpression><![CDATA["{panel}".equals($F{{panel}})]]>'
             f'</printWhenExpression></reportElement>']
    for (x, w), text, align in cols:
        parts.append(tf(x, 0, w, 10, f'"{esc(text)}"', bold=True, size=6.5,
                        align=align, color=MUTED))
    return "".join(parts) + "</frame>"

ph = [
    tf(0, 14, 380, 13, '$F{panel}.toUpperCase()', bold=True, size=10, color=ACCENT),
    tf(390, 15, W - 390, 11,
       '$F{panelCount} == null ? "" : $F{panelCount} + '
       '("1".equals($F{panelCount}) ? " ENTRY" : " ENTRIES")',
       bold=True, size=6.5, align="Right", color=MUTED),
    rule(30, ACCENT),
    headings("Section One", list(zip(G_ROW, ["A", "B", "C", "D", "E"], ["Left"] * 5))),
    rule(48, HAIRLINE),
]
PANEL_HEADER = band(54, "".join(ph), when=notblank("panel"))

PARTY_HEADER = band(22, "".join([
    block(0, 6, 2, 11, ACCENT),
    tf(8, 4, W - 8, 13, '$F{party}', bold=True, size=9, color=INK),
]), when=notblank("party"))

# ---- detail bands ------------------------------------------------------------------
def row(grid, exprs, *, h=16, sect, bolds=None, aligns=None):
    """One table row of stretching cells, and NOTHING else.

    Do not append the row separator here, however tempting. A row band that draws its own
    bottom hairline puts that line above the row's own sub-lines, so it reads as closing
    the wrong record, and when a cell stretches - a three-line address, a list of names -
    the line is drawn straight through the text. Close rows with closer() instead, after
    the sub-lines. See references/verification.md and scripts/pdfcheck.py, which detects
    exactly this defect."""
    bolds = bolds or [False] * len(exprs)
    aligns = aligns or [None] * len(exprs)
    els = [tf(x, 2, w, 12, e, size=8.5, bold=b, align=a)
           for (x, w), e, b, a in zip(grid, exprs, bolds, aligns)]
    return band(h, "".join(els), when=is_section(*sect) if isinstance(sect, (list, tuple))
                else is_section(sect))

def closer(*sects):
    """The hairline that ends a row. Its own band, so it always lands below whatever the
    row and its sub-lines actually printed, however far they stretched."""
    return band(5, rule(4, HAIRLINE), when=is_section(*sects))

def subline(label_text, expr, sects, field, *, italic=False):
    """An indented secondary line, printed only when it has something to say. Goes
    BETWEEN the row and its closer()."""
    if isinstance(sects, str):
        sects = [sects]
    return band(11, "".join([
        tf(INDENT, 0, 62, 10, f'"{esc(label_text)}"', size=6.5, bold=True, color=MUTED),
        tf(INDENT + 66, 0, W - INDENT - 66, 10, expr, size=7, color=MUTED, italic=italic),
    ]), when=f'({is_section(*sects)}) && {notblank(field)}')

# Order matters: row, then its sub-lines, then its closer.
bands = [row(G_ROW, ['$F{colA}', '$F{colB}', '$F{colC}', '$F{colD}', '$F{colE}'],
             sect="ROW")]
# bands.append(subline("MEMO", '$F{memo}', "ROW", "memo", italic=True))
bands.append(closer("ROW"))
# A section with no rows still prints, and says so.
bands.append(band(20, tf(0, 3, W, 12, '"None recorded."', size=8, italic=True,
                         color=MUTED), when=is_section("NONE")))
DETAIL = "".join(bands)

# ---- page footer -------------------------------------------------------------------
(fx1, fw1), (fx2, fw2), (fx3, fw3) = G_FOOT
FOOTER = band(30, "".join([
    rule(6, HAIRLINE),
    tf(fx1, 13, fw1, 10, '"Case " + $F{caseNumber}', size=6.5, color=MUTED),
    ('<textField evaluationTime="Master">'
     f'<reportElement x="{fx2}" y="13" width="{fw2}" height="10" forecolor="{MUTED}" '
     f'uuid="{U()}"/><textElement textAlignment="Center"><font size="7"/></textElement>'
     '<textFieldExpression><![CDATA["Page " + $V{MASTER_CURRENT_PAGE} + " of " + '
     '$V{MASTER_TOTAL_PAGES}]]></textFieldExpression></textField>'),
    tf(fx3, 13, fw3, 10, '"Generated " + $F{today}', size=6.5, align="Right", color=MUTED),
]))

# ---- assemble ----------------------------------------------------------------------
# Schema order is strict: import, parameter, field, variable, group, title, detail, ...
field_xml = "".join(f'<field name="{f}" class="java.lang.String"/>' for f in FIELDS)

doc = f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- Generated by this script - edit the script, not this file. -->
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd" name="REPORT_NAME" pageWidth="595" pageHeight="842" columnWidth="{W}" leftMargin="36" rightMargin="36" topMargin="36" bottomMargin="36" uuid="{U()}">
<import value="org.apache.commons.codec.binary.Base64"/>
<parameter name="caseId" class="java.lang.Long"/>
{field_xml}
<group name="Panel" isStartNewPage="false" isReprintHeaderOnEachPage="true" keepTogether="true" minHeightToStartNewPage="90">
<groupExpression><![CDATA[$F{{panel}}]]></groupExpression>
<groupHeader>{PANEL_HEADER}</groupHeader>
<groupFooter><band height="16" splitType="Stretch"/></groupFooter>
</group>
<group name="Party" isStartNewPage="false" keepTogether="true">
<groupExpression><![CDATA[$F{{panel}} + "|" + $F{{party}}]]></groupExpression>
<groupHeader>{PARTY_HEADER}</groupHeader>
<groupFooter><band height="8" splitType="Stretch"/></groupFooter>
</group>
<title>{TITLE}</title>
<detail>{DETAIL}</detail>
<pageFooter>{FOOTER}</pageFooter>
</jasperReport>
'''

out = sys.argv[1] if len(sys.argv) > 1 else "report.jrxml"
pretty = xml.dom.minidom.parseString(doc.encode("utf-8")).toprettyxml(indent="\t")
open(out, "w").write("\n".join(l for l in pretty.split("\n") if l.strip()))

# ---- contract self-check -----------------------------------------------------------
import re
assert not [f for f in FIELDS if f'$F{{{f}}}' not in doc], "declared but unused"
assert not set(re.findall(r'\$F\{(\w+)\}', doc)) - set(FIELDS), "used but undeclared"
xml.dom.minidom.parse(out)
print(f"wrote {out}: {len(FIELDS)} fields, all declared and all used; parses clean")
