"""
Template: RECORD SUMMARY

One root record, a masthead, a metadata strip, stat tiles, then N sections each with
its own column grid and entry count. Person Summary, Case Summary, Party Summary.

ROW CONTRACT - what the Groovy rule must put in `_data`:

    one flat List<Map>, every row carrying:
      section     the section key, e.g. "ADDRESS"          (drives grouping)
      c1..c6      that section's column values, left to right, as Strings
    plus, on EVERY row (they are read from the first row of each group and in
    the title band, so they must be present throughout):
      recTitle    the masthead line, e.g. "Dr. Jordan Quinn Rivera Jr."
      recKicker   the eyebrow, e.g. "PERSON SUMMARY REPORT"
      recSlug     the footer slug, e.g. "Person 42"
      m1v..m4v    the four metadata values
      t1v..t3v    the three stat-tile numbers

Sections are ordered by the SECTIONS list below, so the rule must emit rows in
that same order - Jasper groups consecutive rows, it does not sort for you.

Unused columns and tiles: emit "" (never null) - see gotchas in HANDOFF.md.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jti_style as S  # noqa: E402

NAME = "JTI_Record_Summary"

# (section key, heading, [(column label, relative weight[, align, field]), ...])
# Give each column an explicit FIELD name wherever the rule has one. Falling back to
# the shared c1..c6 means reordering a section's columns silently changes what every
# later column in that section means - invisible on the page.
SECTIONS = [
    ("NAME", "Name", [("First Name", 30), ("Last Name", 30), ("Middle Name", 25), ("Status", 20)]),
    ("ADDRESS", "Address", [("Address Type", 18), ("Address", 34), ("City", 16), ("State", 10), ("Zip", 11), ("Status", 13)]),
    ("TELEPHONE", "Telephone", [("Telephone Type", 30), ("Telephone Number", 40), ("Status", 30)]),
    ("CONTACT", "Contact", [("Contact Type", 30), ("Contact", 45), ("Status", 25)]),
    ("IDENTIFICATION", "Identification", [("Identification Type", 40), ("Identification Number", 60)]),
    ("AKA", "AKA", [("AKA Type", 22), ("First / Business Name", 34), ("Middle Name", 20), ("Last Name", 24)]),
    ("STATUS", "Person Special Statuses", [("Status", 20), ("Date", 16), ("Memo", 64)]),
]

META = ["Person ID", "Person Type", "Status", "Printed"]
TILES = ["Addresses", "Telephones", "Contacts"]

CW = S.COL_W
ROW_H, HDR_H, SEC_H, TILE_H = 24, 16, 30, 42
GUTTER = 5      # clear air between a row's last line and its separator
TOP_PAD = 4     # and above its first line, so a row does not start flush against the
                # PREVIOUS row's separator - the two land on the same y otherwise


def _masthead(META, TILES):
    """Accent rule, the J, eyebrow, title, metadata strip, stat tiles."""
    o = [S.line(0, 0, CW, S.NAVY, 2.0), S.logo(0, 10, 40, 48)]
    o.append(S.label(52, 14, CW - 52, 10, "Journal Technologies   ·   ", color=S.MUTED))
    o.append(S.text(52 + 96, 14, CW - 148, 12, "$F{recKicker}.toUpperCase()",
                    size=6, bold=True, color=S.MUTED))
    o.append(S.text(52, 26, CW - 52, 28, "$F{recTitle}",
                    size=19, bold=True, color=S.NAVY))
    y = 62
    o.append(S.line(0, y, CW, S.RULE))
    mw = S.widths([1] * len(META))
    for x, w, lbl, i in zip(S.xs_of(mw), mw, META, range(1, len(META) + 1)):
        o.append(S.label(x, y + 8, w, 12, lbl))
        o.append(S.text(x, y + 18, w, 12, f"$F{{m{i}v}}", size=8, color=S.INK))
    y += 36
    o.append(S.line(0, y, CW, S.RULE))
    # stat tiles
    ty = y + 8
    tw = S.widths([1] * len(TILES))
    gap = 10
    for x, w, lbl, i in zip(S.xs_of([v + gap for v in tw]), tw, TILES, range(1, len(TILES) + 1)):
        o.append(S.rect(x, ty, w - gap, TILE_H, S.FILL))
        o.append(S.text(x + 12, ty + 6, w - 24, 22, f"$F{{t{i}v}}",
                        size=15, bold=True, color=S.NAVY))
        o.append(S.label(x + 12, ty + 26, w - 24, 9, lbl))
    return f"""<title>
<band height="{ty + TILE_H + 10}" splitType="Stretch">
{chr(10).join(o)}
</band>
</title>"""


def _cols(sec):
    return S.parse_cols([(c[0], c[1], (c[2] if len(c) > 2 else "Left"),
                          (c[3] if len(c) > 3 else None)) for c in sec[2]])


def _section_header(SECTIONS):
    """One band. Each section's heading + its own column grid, in overlapping
    frames gated on $F{section}, so the grid can differ per section."""
    o = []
    for sec in SECTIONS:
        key, heading = sec[0], sec[1]
        cols = _cols(sec)
        when = f'$F{{section}}.equals("{key}")'
        inner = [
            S.static(0, 4, CW - 90, 15, heading.upper(), size=10, bold=True, color=S.NAVY),
            # entry count, resolved at the end of the group
            S.text(CW - 90, 6, 90, 12,
                   '$V{SectionCount} + ($V{SectionCount} == 1 ? " ENTRY" : " ENTRIES")',
                   size=6, bold=True, color=S.MUTED, align="Right",
                   eval_time="Group", eval_group="Section"),
            S.line(0, 20, CW, S.NAVY, 1.5),
        ]
        ws = S.widths([c["weight"] for c in cols])
        for x, w, c in zip(S.xs_of(ws), ws, cols):
            inner.append(S.label(x, 24, w, 10, c["label"], pad=2))
        inner.append(S.line(0, 36, CW, S.RULE_HI))
        o.append(S.frame(0, 0, CW, SEC_H + 8, "\n".join(inner), when=when))
    return f"""<groupHeader>
<band height="{SEC_H + 12}" splitType="Stretch">
{chr(10).join(o)}
</band>
</groupHeader>"""


def _detail(SECTIONS):
    """No frames. A <frame> does NOT pass a stretching child's height up to the band,
    so a wrapped cell overflows it and the separator gets drawn through the next row.
    Every section's cells therefore sit directly in the band, each gated on
    $F{section}; only one section's cells print, and the band grows to the tallest
    of them."""
    o = []
    for sec in SECTIONS:
        key = sec[0]
        cols = _cols(sec)
        when = f'$F{{section}}.equals("{key}")'
        ws = S.widths([c["weight"] for c in cols])
        for x, w, c in zip(S.xs_of(ws), ws, cols):
            o.append(S.text(x, TOP_PAD, w, ROW_H - GUTTER - TOP_PAD,
                            f"$F{{{c['field']}}}", size=8,
                            color=S.INK, pad=2, valign="Top", stretch=True,
                            align=c["align"], grow=True, when=when))
    return f"""<detail>
<band height="{ROW_H}" splitType="Stretch">
{chr(10).join(o)}
{S.line(0, ROW_H - 1, CW, S.RULE, at_bottom=True)}
</band>
</detail>"""


def build(sections=None, meta=None, tiles=None, name=None, params=()):
    """`params` are the report's own inputs, e.g. the id it is launched with.

    A single-record report ALWAYS has one. It is never printed on the page, but the
    report registration binds parameters by name against the jrxml, so an input the
    rule reads and the jrxml does not declare fails at run time, not at build time.
    """
    SECTIONS_ = sections or SECTIONS
    META_ = meta or META
    TILES_ = tiles or TILES
    name = name or NAME
    seen = []
    for sec in SECTIONS_:
        for c in _cols(sec):
            if c["field"] not in seen:
                seen.append(c["field"])
    fields = (["section", "recTitle", "recKicker", "recSlug"] + seen
              + [f"m{i}v" for i in range(1, len(META_) + 1)]
              + [f"t{i}v" for i in range(1, len(TILES_) + 1)])
    body = f"""<variable name="SectionCount" class="java.lang.Integer" resetType="Group" resetGroup="Section" calculation="Count">
<variableExpression><![CDATA[$F{{section}}]]></variableExpression>
</variable>
<group name="Section" isStartNewColumn="false" keepTogether="true">
<groupExpression><![CDATA[$F{{section}}]]></groupExpression>
{_section_header(SECTIONS_)}
<groupFooter><band height="14" splitType="Stretch"/></groupFooter>
</group>
{_masthead(META_, TILES_)}
{_detail(SECTIONS_)}
{S.footer(CW, '$F{recSlug}')}
<summary>
<band height="26" splitType="Stretch">
<printWhenExpression><![CDATA[$V{{REPORT_COUNT}} == 0]]></printWhenExpression>
{S.static(0, 6, CW, 14, "None recorded.", size=9, color=S.MUTED)}
</band>
</summary>"""
    return S.document(name, body, fields=fields, params=params)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "out" / f"{NAME}.jrxml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    print(f"wrote {out.name}  ({len(SECTIONS)} sections)")
