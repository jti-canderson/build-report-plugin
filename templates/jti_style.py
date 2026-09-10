"""
JTI house style for eSeries Jasper reports - shared tokens and jrxml element helpers.

Every template in templates/ builds on this, so the look is defined once. Change a
token here and every template follows.

Nothing in here is invented. The tokens are the OKDAC corpus majority, standardised:
navy #1C3971 (28 uses, the only real accent), SansSerif (113 uses vs 51 Times New
Roman), #F5F5F5 fills (28 uses), and the J lifted verbatim from
'Payments by Obligation Type.jrxml'.
"""
import pathlib
import uuid

HERE = pathlib.Path(__file__).parent

# ------------------------------------------------------------------- palette
NAVY = "#1C3971"    # headings, rules, the accent bar
INK = "#1A1D21"     # body text
MUTED = "#7A828C"   # small-caps labels, footer
RULE = "#D8DCE2"    # hairlines between rows
RULE_HI = "#B9C0CA"  # slightly stronger hairline under column headers
FILL = "#F4F6F8"    # stat tiles, zebra
WHITE = "#FFFFFF"

FONT = "SansSerif"

# ------------------------------------------------------------------ geometry
# Letter portrait. The corpus has no formal standard - every Check is Letter and
# the A4 reports inherited A4 from Jaspersoft's stock blank rather than a choice.
PAGE_W, PAGE_H = 612, 792
MARGIN = 20
COL_W = PAGE_W - 2 * MARGIN          # 572 usable

# Landscape, same paper. The corpus landscape reports are A4-landscape (VOCA,
# 842x595) and one custom 820x500, but both inherited that from a Jaspersoft blank
# rather than a decision - so the library keeps one paper size and just turns it.
LAND_W, LAND_H = PAGE_H, PAGE_W      # 792 x 612
LAND_COL_W = LAND_W - 2 * MARGIN     # 752 usable

LOGO_W, LOGO_H = 40, 48


def uid():
    return str(uuid.uuid4())


def logo_b64():
    return (HERE / "journal_mark.b64").read_text().strip()


def widths(weights, total=None):
    """Scale relative weights to exactly `total`, last absorbing the rounding.

    This is why a generated template cannot silently overflow the page - the
    single most common defect in the hand-built corpus.
    """
    total = COL_W if total is None else total
    s = sum(weights)
    out = [int(round(w * total / s)) for w in weights]
    out[-1] += total - sum(out)
    return out


def parse_cols(columns):
    """Normalise a COLUMNS entry to a dict.

    Accepts, in increasing specificity:
        (label, weight, align)
        (label, weight, align, field)
        (label, weight, align, field, cls)
        (label, weight, align, field, cls, pattern, wrap)

    `field` defaults to c1, c2, ... A real rule emits NAMED keys - `pastDue`, not
    `c4` - so a real report should always give the field. Positional cN is for a
    template demo only: with cN, reordering the column list silently changes what
    every later column means, which is a defect you cannot see on the page.
    """
    out = []
    for i, c in enumerate(columns, start=1):
        c = list(c) + [None] * (7 - len(c))
        out.append(dict(label=c[0], weight=c[1], align=c[2] or "Left",
                        field=c[3] or f"c{i}",
                        cls=c[4] or "java.lang.String", pattern=c[5],
                        wrap=bool(c[6])))
    return out


def xs_of(ws, x0=0):
    out, run = [], x0
    for w in ws:
        out.append(run)
        run += w
    return out


# ------------------------------------------------------------------ elements
def text(x, y, w, h, expr, *, style=None, align="Left", valign="Middle",
         size=None, bold=False, color=None, font=FONT, pattern=None,
         pad=0, when=None, blank=True, eval_time=None, eval_group=None,
         markup=None, stretch=False, grow=False):
    """A <textField>. `expr` is a raw jrxml expression."""
    _fits(h, size, expr)
    a = [f'isBlankWhenNull="{"true" if blank else "false"}"']
    if pattern:
        a.append(f'pattern="{pattern}"')
    if eval_time:
        a.append(f'evaluationTime="{eval_time}"')
    if eval_group:
        a.append(f'evaluationGroup="{eval_group}"')
    if markup:
        a.append(f'markup="{markup}"')
    if stretch:
        a.append('textAdjust="StretchHeight"')
    return f"""<textField {" ".join(a)}>
{_re(x, y, w, h, style=style, when=when, forecolor=color,
     stretch_type="RelativeToTallestObject" if (grow or stretch) else None)}
{_box(pad)}<textElement textAlignment="{align}" verticalAlignment="{valign}">
{_font(size, bold, font)}</textElement>
<textFieldExpression><![CDATA[{expr}]]></textFieldExpression>
</textField>"""


def static(x, y, w, h, label, *, style=None, align="Left", valign="Middle",
           size=None, bold=False, color=None, font=FONT, pad=0, when=None):
    _fits(h, size, label)
    _winansi(label)
    return f"""<staticText>
{_re(x, y, w, h, style=style, when=when, forecolor=color)}
{_box(pad)}<textElement textAlignment="{align}" verticalAlignment="{valign}">
{_font(size, bold, font)}</textElement>
<text><![CDATA[{label}]]></text>
</staticText>"""


def rect(x, y, w, h, fill, *, when=None, radius=0, grow=False):
    r = f' radius="{radius}"' if radius else ""
    return f"""<rectangle{r}>
{_re(x, y, w, h, when=when, mode="Opaque", backcolor=fill,
     stretch_type="RelativeToBandHeight" if grow else None)}
<graphicElement><pen lineWidth="0.0" lineColor="{fill}"/></graphicElement>
</rectangle>"""


def tri_down(x, y, w, h, color, *, when=None):
    """A downward triangle, DRAWN as stacked rectangles.

    Every caret/arrow/triangle character is outside WinAnsi and vanishes from the PDF
    (see _winansi), so a UI-style caret has to be drawn. At 6-8pt the stair-stepping is
    not visible; what IS visible is the empty gap you get from typing one.
    """
    rows = max(2, int(h))
    o = []
    for i in range(rows):
        # jrxml coordinates are INTEGERS - a float x or width fails the parse with
        # NumberFormatException, not a validation warning.
        rw = int(round(w * (rows - i) / float(rows)))
        if rw < 1:
            break
        o.append(rect(int(x + (w - rw) // 2), int(y + i), rw, 1, color, when=when))
    return "\n".join(o)


def line(x, y, w, color=RULE, weight=0.5, *, when=None, at_bottom=False):
    return f"""<line>
{_re(x, y, w, 1, when=when,
     position_type="FixRelativeToBottom" if at_bottom else None)}
<graphicElement><pen lineWidth="{weight}" lineColor="{color}"/></graphicElement>
</line>"""


def logo(x, y, w=LOGO_W, h=LOGO_H):
    return f"""<image scaleImage="RetainShape" hAlign="Left" vAlign="Middle">
<reportElement x="{x}" y="{y}" width="{w}" height="{h}" uuid="{uid()}"/>
<imageExpression><![CDATA[new ByteArrayInputStream(Base64.decodeBase64($P{{journalLogo}}.getBytes()))]]></imageExpression>
</image>"""


def frame(x, y, w, h, body, *, when=None, grow=False):
    """A positioning container. Sections with different column grids are each
    wrapped in a frame gated by printWhenExpression, all at the same y and height,
    so exactly one prints and they may overlap freely."""
    return f"""<frame>
{_re(x, y, w, h, when=when,
     stretch_type="RelativeToTallestObject" if grow else None)}
{body}
</frame>"""


def label(x, y, w, h, txt, **kw):
    """A small-caps field label - the grey uppercase micro-type."""
    kw.setdefault("size", 6)
    kw.setdefault("bold", True)
    kw.setdefault("color", MUTED)
    _fits_width(w, kw["size"], txt.upper(), kw.get("pad", 0))
    return static(x, y, w, h, txt.upper(), **kw)


# ------------------------------------------------------------------ internals
# A line box shorter than this x the font size prints NOTHING.
#
# Was 1.2, which is what a LOCAL render tolerates - and that is the trap, because the
# threshold is a property of the JasperReports build and fonts doing the rendering, not of
# the .jrxml. Measured against a real server run (Case Summary Report on
# eh-team-config-symphony.logan-symphony.com, 09/03/2026, page read directly):
#
#     ratio 1.67 (column headers)  rendered        ratio 1.33 (meta + tile labels)  BLANK
#     ratio 1.50 (meta values)     rendered        ratio 1.20 (tile numbers)        BLANK
#     ratio 1.37 (record title)    rendered
#
# So the server's real cutoff sits between 1.33 and 1.37 while the local one sits below 1.20.
# Every static label in the masthead cleared the old guard, passed the local geometry check,
# and then printed blank in production - the report lost its entire metadata label row and
# both lines of every stat tile, with no error anywhere. 1.45 puts the guard on the far side
# of the observed cutoff with margin; raise it, do not lower it.
MIN_LEAD = 1.45
CAP_EM = 0.62    # approx width of one UPPERCASE bold SansSerif char, in ems


def _winansi(txt):
    """A character outside WinAnsi is DROPPED SILENTLY at PDF export - no error, no
    placeholder, an empty cell. Refuse to generate one.

    Established 2026-09-04, and the reason this guard exists rather than a note: the
    LOCAL RASTER DOES NOT SHOW IT. render_check.groovy rasterises with
    JasperPrintManager.printPageToImage, which draws through AWT and renders ANY glyph
    the JVM font has. The PDF is exported through WinAnsi and drops it. So a glyph can
    be plainly visible in the PNG a human is shown and absent from the document that
    ships. Verified by extracting text from the PDF itself: U+25BC, U+25BE, U+2304 and
    U+2207 all appear in the raster and are simply GONE in the PDF, alongside the
    emoji (U+1F53D, U+1F4C1, U+1F4CD) that at least fail visibly in both.

    Safe: U+2022 bullet, U+2013 en dash, U+2014 em dash, U+00B7 middle dot.
    Not safe: every arrow, triangle, caret, check, funnel and emoji. DRAW those - see
    templates/eseries_summary.py, where the folder and the carets are rectangles.
    """
    try:
        txt.encode("windows-1252")
    except UnicodeEncodeError as e:
        bad = txt[e.start:e.end]
        raise ValueError(
            f"{bad!r} (U+{ord(bad[0]):04X}) is outside WinAnsi and is DROPPED SILENTLY "
            f"at PDF export - it will be visible in the local PNG and absent from the "
            f"PDF: {txt!r}. Draw the shape instead of typing it.")


def _fits_width(w, size, txt, pad):
    """A cell wider than its column is TRUNCATED silently - no error, no ellipsis.
    Row values are unknowable at generate time, but the COLUMN HEADER is not, and a
    clipped header is always wrong. Refuse to generate one."""
    need = len(txt.rstrip()) * CAP_EM * (size or 8) + 2 * pad
    if need > w:
        raise ValueError(
            f"column {w}pt is too narrow for its header {txt!r} at {size}pt "
            f"(needs ~{need:.0f}pt); it would print clipped")


def _fits(h, size, what):
    """JasperReports silently prints an EMPTY element when a single line of text
    is taller than its box - no error, no warning, just a gap on the page. Refuse
    to generate one."""
    if size and h < size * MIN_LEAD:
        raise ValueError(
            f"element height {h} is too small for {size}pt text (needs "
            f">= {size * MIN_LEAD:.0f}); it would print blank: {what!r}")


def _re(x, y, w, h, *, style=None, when=None, mode=None, backcolor=None,
        forecolor=None, stretch_type=None, position_type=None):
    """Emit a <reportElement>, self-closing unless it carries a printWhenExpression."""
    a = []
    if style:
        a.append(f'style="{style}"')
    if mode:
        a.append(f'mode="{mode}"')
    if backcolor:
        a.append(f'backcolor="{backcolor}"')
    if forecolor:
        a.append(f'forecolor="{forecolor}"')
    if stretch_type:
        a.append(f'stretchType="{stretch_type}"')
    if position_type:
        a.append(f'positionType="{position_type}"')
    a += [f'x="{x}"', f'y="{y}"', f'width="{w}"', f'height="{h}"', f'uuid="{uid()}"']
    head = f'<reportElement {" ".join(a)}'
    if when is None:
        return head + "/>"
    return (head + ">\n<printWhenExpression><![CDATA[" + when +
            "]]></printWhenExpression>\n</reportElement>")


def _box(pad):
    return f'<box leftPadding="{pad}" rightPadding="{pad}"/>\n' if pad else ""


def _font(size, bold, font):
    """Colour is NOT a font attribute in the 6.21 schema - it belongs on
    <reportElement forecolor=...>. Putting it here fails the compile."""
    a = [f'fontName="{font}"']
    if size:
        a.append(f'size="{size}"')
    if bold:
        a.append('isBold="true"')
    return f'<font {" ".join(a)}/>' + chr(10)

# ------------------------------------------------------------------ document
def document(name, body, *, fields=(), params=(), styles="", page_w=PAGE_W,
             page_h=PAGE_H, margin=MARGIN, when_no_data="AllSectionsNoDetail"):
    """Wrap bands in a <jasperReport>.

    `journalLogo` is a PARAMETER, never a variable: a variable is not yet
    evaluated when the title band renders, so the mark comes out blank with no
    error. That is almost certainly why every corpus report puts the J in the
    page footer - late enough that a variable happens to work.
    """
    col_w = page_w - 2 * margin
    # A parameter with a default supplies itself (the logo, a house constant). A
    # parameter WITHOUT one is a launch input the caller must pass - keep the
    # distinction, because harnesses and eSeries both read it that way.
    p = "\n".join(
        (f'<parameter name="{n}" class="{c}"/>' if d is None else
         f'<parameter name="{n}" class="{c}">'
         f'<defaultValueExpression><![CDATA[{d}]]></defaultValueExpression></parameter>')
        for n, c, d in params)
    # fields may be "name" or ("name", "java.math.BigDecimal")
    f = "\n".join(
        f'<field name="{n}" class="java.lang.String"/>' if isinstance(n, str)
        else f'<field name="{n[0]}" class="{n[1]}"/>' for n in fields)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- JTI house style. Generated - do not hand-edit; change the generator. -->
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd"
 name="{name}" pageWidth="{page_w}" pageHeight="{page_h}" columnWidth="{col_w}"
 leftMargin="{margin}" rightMargin="{margin}" topMargin="{margin}" bottomMargin="{margin}"
 whenNoDataType="{when_no_data}" uuid="{uid()}">
<import value="org.apache.commons.codec.binary.Base64"/>
{styles}
<parameter name="journalLogo" class="java.lang.String" isForPrompting="false">
<defaultValueExpression><![CDATA["{logo_b64()}"]]></defaultValueExpression>
</parameter>
{p}
<queryString><![CDATA[]]></queryString>
{f}
{body}
</jasperReport>
"""


def footer(col_w, left_expr, *, height=30):
    """The house page footer: hairline, left slug, centred pagination, right stamp."""
    return f"""<pageFooter>
<band height="{height}" splitType="Stretch">
{line(0, 2, col_w, RULE)}
{text(0, 9, 180, 10, left_expr, size=6, color=MUTED, bold=True)}
{text(col_w // 2 - 60, 9, 90, 10, '"Page " + $V{PAGE_NUMBER} + " of "', size=6, color=MUTED, align="Right")}
{text(col_w // 2 + 30, 9, 30, 10, 'String.valueOf($V{PAGE_NUMBER})', size=6, color=MUTED, align="Left", eval_time="Report", pad=3)}
{text(col_w - 180, 9, 180, 10, '"Generated " + new java.text.SimpleDateFormat("MM/dd/yyyy").format(new java.util.Date())', size=6, color=MUTED, align="Right")}
</band>
</pageFooter>"""
