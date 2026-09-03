# JRXML layout — the page

*Part of the `jasper-reports` skill. Read when authoring or fixing the .jrxml: house style, column geometry, sections, page breaks.*

# JRXML layout

Layout bugs are cheap to find *if* you render locally (`verification/run.sh render`, then `scripts/pdfcheck.py`) and expensive if you do not — the fallback is a user running the report and reading a screenshot back to you. Two things still matter more than usual: matching the existing house style exactly, and doing the column arithmetic explicitly instead of eyeballing coordinates. `pdfcheck.py` catches a collision after the fact; an asserted grid stops you shipping one.

## The logo — every report carries it

Put the Journal Technologies mark in the **top-left of the title band** of every report. Not optional, unless a different logo is specified by the user, and not only on client-facing ones: a report that reaches a DA's office without it looks like a draft.

The mark ships with this skill:

```
assets/journal_mark.png     176x264 PNG, transparent, the "J" with the wordmark cropped off
assets/journal_mark.b64     the same file base64-encoded, ready to paste into a variable
```

**Embed it, never link it.** Base64 in the `.jrxml`, decoded to a stream by commons-codec. That keeps the file self-contained: no file share, no network call from the render server, nothing to break when a report is imported into another environment.

**Put the base64 in the `imageExpression` itself, not in a `$V{}` variable.** This is the trap. The corpus embeds it as `<variable name="journalLogo">` and that works *there* only because both those reports put the logo in the `pageFooter`. A report variable holds its initial value — null — until the first detail row is processed, and the **title band renders before that**. So `$V{journalLogo}` in a title band is null, `null.getBytes()` throws, JasperReports swallows the NPE during expression evaluation, and you get a blank space where the logo should be. No error, no warning, nothing in the log. Copying the corpus pattern into a title band costs a render cycle to discover.

A `<parameter>` with a default value would also be in scope everywhere, but Reports Admin auto-detects parameters from the JRXML and would surface it as an input control. A literal has neither problem:

```xml
<import value="org.apache.commons.codec.binary.Base64"/>
…
<image scaleImage="RetainShape">
  <reportElement x="0" y="10" width="32" height="48" uuid="…"/>
  <imageExpression><![CDATA[new java.io.ByteArrayInputStream(
    Base64.decodeBase64("iVBORw0KGgoAAAANS…".getBytes()))]]></imageExpression>
</image>
```

The `<import>` must sit before the first `<parameter>` — the JasperReports schema is strict about element order, and a misplaced one fails at import with a message that does not name the real problem. The base64 alphabet cannot contain `]]>`, so the literal is safe inside CDATA, and at roughly 10KB it is far inside the 64KB limit on a Java string constant.

Keep `<image>` otherwise bare. `hAlign` and `vAlign` are deprecated on `JRImage` and removed in JasperReports 7; `scaleImage` is valid across versions.

Sizing and placement:

- The mark is **2:3** (portrait). `32x48` is the house size; scale both numbers together and keep `scaleImage="RetainShape"`. A squashed logo is the most visible possible defect on page one.
- Hang the header text off the mark rather than the page edge — text `x` = logo width + 14. Do not let a title start at `x=0` beside a logo.
- Set the company name in **type**, not in the image: an eyebrow line reading `JOURNAL TECHNOLOGIES · <REPORT NAME>` at 7pt bold uppercase. The full lockup in the corpus (429x644, mark over "Journal" over "Technologies") is unusable at header scale — scaled to fit a header, "Technologies" lands around 3pt and turns to mush. That is why the shipped asset is the mark alone.

If a user specifies a different image, the ratio may change.

If a generator script builds the `.jrxml`, have it read `assets/journal_mark.b64` at generate time rather than pasting 10KB of base64 into the source:

```python
CAND = [os.path.join(a, b, "jasper-reports")
        for a in (".", "..", "../..", "../../..")
        for b in ("System/Skills", ".claude/skills")]
CAND.append(os.path.expanduser("~/.claude/skills/jasper-reports"))
SKILL = next(p for p in CAND if os.path.isdir(p))
LOGO_B64 = open(os.path.join(SKILL, "assets/journal_mark.b64")).read().strip()
```

## House style

This is the current standard, approved on the Case Charges Report. Older reports in the corpus do not follow it — see "Legacy corpus style" below before you assume a neighbouring file is a model.

```
pageWidth="595" pageHeight="842" columnWidth="523"
leftMargin="36" rightMargin="36" topMargin="36" bottomMargin="36"
```

A4 portrait, **523pt of content**. The wide margins are deliberate: the most common failure in these reports is cramped, not ugly.

**Palette** — one accent, one grey ramp. Never add a second accent.

```
ACCENT   #153E75   navy; section headings, chip numbers, rules, the party tick
INK      #111827   document title
BODY     #1F2937   body text
MUTED    #6B7280   labels, column heads, secondary lines
HAIRLINE #E5E7EB   row separators
RULE     #C7D2DE   the rule under the header
CHIPBG   #F4F6F9   summary chip fill
```

**Type** — SansSerif throughout, five steps. Hierarchy comes from size and colour, not weight alone. Do not introduce a serif: font availability on the render server is not something you can test from here.

```
eyebrow      7    bold  caps  MUTED     "JOURNAL TECHNOLOGIES · <REPORT NAME>"
title       19    bold        INK       the record's own name
section     10    bold  caps  ACCENT    panel heading
column head  6.5  bold  caps  MUTED
body         8.5              BODY
secondary    7                MUTED     sub-lines under a row
```

**Page anatomy**, top to bottom:

1. A 3pt accent bar across the full width at `y=0`.
2. The logo at `x=0, y=10, 32x48` (see above), header text at `x=46`.
3. Eyebrow, then the title at 19pt.
4. A `RULE` hairline, then a **metadata strip**: four label-over-value pairs at `(0,127) (131,127) (262,127) (393,127)`, label 6.5 caps muted above value 9 ink.
5. **Summary chips** — three `CHIPBG` blocks at `(0,166) (178,166) (356,166)`, 44 tall, each a 17pt accent number over a 6.5pt caps muted label. Chips are for counts a reader scans for first, not for every number in the report.
6. Per section: heading in accent caps, entry count right-aligned in 6.5 caps muted, an accent rule, column heads, a hairline.
7. Rows at 17pt with a `HAIRLINE` separator under each. **No vertical rules and no boxes** — a hairline is enough.
8. Footer: hairline, then `Case <n>` left, `Page X of Y` centred, `Generated <date>` right.

**Editorial, not spreadsheet.** Where a nested table would appear — conditions under a sentence, say — render one prose line per item instead, joined with `·` and blanks dropped:

```
Community Service   ·   250.00   ·   15 Days   ·   Active   ·   04/17/2025
```

A page of nested tables is what makes a report read as a database dump. This is the single most effective change available to you.

**State absence explicitly.** A section with no rows must still print, with `None recorded.` under its heading. A section that silently vanishes reads as a broken report, and on a legal document the absence is often the point.

Two conventions worth keeping from the older reports:

- **No `<style>` blocks** — styling is inline on each element.
- **No `<staticText>`** — labels are `textField`s holding a literal expression (`"Effective:"`), which is why a corpus grep for `staticText` returns nothing. One element type to reason about when a band stretches.
- `isStretchWithOverflow="true"` and `isBlankWhenNull="true"` on every text field, and a `uuid` on every element.

### Legacy corpus style

Reports written before this standard use 20pt margins, 554pt content, a centred 16pt title, accent `#054CFF`, and no logo. Do not copy them for new work, and do not restyle one just because you opened it — but do match the surrounding file when making a small change to an existing report.

## Generate the file, do not hand-write it

Anything with more than a couple of sections should be produced by a Python generator that emits the XML, with the column grids declared as data and asserted:

```python
def check(name, cells):          # cells: [(x, width), ...]
    end = 0
    for i, (x, w) in enumerate(cells):
        assert x >= end and (i == 0 or x - end >= 4), f"{name}: cell {i} overlaps"
        end = x + w
    assert end <= W, f"{name}: row ends at {end} > {W}"
    return cells

G_CHARGE = check("CHARGE", [(0, 30), (36, 215), (257, 66), (329, 54), (389, 134)])
```

`assets/jrxml_scaffold.py` is a working starting point: the palette, the type scale, the `tf` / `rule` / `block` / `band` helpers, the header with the logo, the footer, and the contract self-check. Copy it next to the report and fill in the grids and bands.

The generator should end by proving the contract on itself — every declared field used somewhere in the layout, every `$F{}` in the layout declared, and the file parses:

```python
assert not [f for f in FIELDS if f'$F{{{f}}}' not in doc]
assert not set(re.findall(r'\$F\{(\w+)\}', doc)) - set(FIELDS)
xml.dom.minidom.parse(out)
```

Keep the generator in the report folder and say in the contract file that the `.jrxml` is generated — otherwise someone hand-edits the XML and the next regeneration silently reverts them.

## Column arithmetic — the overlap bug

The most common layout defect is a value running under the next label, which renders as fused text like `Charity FordType:` or `DIGITAL_ZIPStatus:`. It happens when a value's `x + width` crosses the next element's `x`.

**Compute the grid, write it down, and check every row against it.** A label/value grid that fits 554 with real gaps:

| | x | width | ends |
|---|---|---|---|
| label (left) | 0 | 90 | 90 |
| value (left) | 94 | 176 | 270 |
| label (right) | 288 | 122 | 410 |
| value (right) | 414 | 140 | 554 |

Two columns of label+value beats three: values like a full name or a lookup label need room, and a 50–75pt value cell will always eventually collide. Where two fields are conceptually one — a date range — join them in the expression instead of spending two cells:

```
$F{effectiveFrom} + ($F{effectiveTo} == null || $F{effectiveTo}.isEmpty() ? "" : "  -  " + $F{effectiveTo})
```

Assert the geometry in whatever script generates the file, so a future edit cannot silently reintroduce an overlap.

## One flat dataset, several visual sections

eSeries hands the report a single `_data` collection, so a report with several tables ships as one flat row list with a `section` discriminator (see `report-builder`). Render it like this:

- **A group per record** (`groupExpression` on the record's name) whose header carries that record's summary block.
- **A second group** on `record + "|" + section` whose header carries the column headings for that section, each set wrapped in a `<frame>` with a `printWhenExpression` so only the relevant one prints:

```xml
<frame>
  <reportElement x="0" y="4" width="554" height="34" uuid="…">
    <printWhenExpression><![CDATA["FILE".equals($F{section})]]></printWhenExpression>
  </reportElement>
  …headings…
</frame>
```

- **One detail band per section**, each gated by the same `printWhenExpression`, so a FILE row and a TRACKING row can have completely different column layouts.

Use the same technique for anything optional — a memo line that only prints when the memo is non-empty avoids a permanent blank gap under every record.

## Page breaks

- **`keepTogether="true"` on every group that has a header**, not just the innermost one. A panel group without it prints its heading and column heads at the foot of a page and its rows on the next — an orphan that reads as a rendering bug. This happened on the Case Charges Report: the inner Party group had `keepTogether` and the outer Panel group did not, so "Sentencing Per Person" appeared twice, empty at the bottom of page 1 and populated on page 2.
- **`minHeightToStartNewPage`** on the same group is the targeted control: the vertical space that must remain for the group to start here at all. `90` is a reasonable floor for a heading plus column heads plus a row or two. Use it with `keepTogether`, not instead of it.
- `isReprintHeaderOnEachPage="true"` labels the continuation when a group genuinely spans pages. The three together are what you want: keep it whole if it fits, refuse to start it in a sliver, label it if it must break.
- Put long, unpredictable values (a browser user-agent string, statute prose) on their own full-width line at `size="7"` rather than squeezing them into a column.

## Blank cells read as bugs

An empty cell looks identical whether the data is legitimately absent or the field name is wrong. Two habits fix this, and both belong in the Groovy rather than the layout:

- Give absent-but-expected values an explicit marker — `"Expired"`, `"—"`, `"None"` — so a reader can tell "nothing to show" from "something broke".
- Never rely on a field whose emptiness you haven't confirmed against real data. `nameExact` on `Document` is populated in the schema and empty in practice; `originalFileName` is the real file name. Resolve questions like that with the **Velocity Test** page (`/ecms/admin/velocity`: pick Entity + Id, evaluate `$!{document.originalFileName}`) before shipping a layout built on the wrong field.

## Editing an existing jrxml — scope every insert to its band

A jrxml is several bands that all look alike in the file, so a structural edit anchored on a *pattern* rather than a *location* lands in the wrong one. This is a real failure, not a hypothetical: adding a "Disclosed Email:" row to a report's summary block by inserting before "the first `<line>` with `width="554"`" put it in the **Section** group instead of the **Packet** group. It rendered under the file-column headings, and it rendered *blank* — because file rows legitimately carry an empty value for a packet-level field. Two bugs, one cause, and neither was visible without running the report.

So when inserting into an existing jrxml:

**Slice the group block first, then edit inside it.**

```python
def bounds(name, s):
    a = s.index('<group name="%s"' % name)
    return a, s.index('</group>', a)

pa, pb = bounds('Packet', s)
block  = s[pa:pb]          # edit only this
s = s[:pa] + block + s[pb:]
```

Append before the block's own closing `</band>` (`block.rindex('\t\t\t</band>')`) rather than searching for a sibling element that may not exist there — the Packet group in this report has **no separator line at all**, which is exactly why the pattern search fell through to the next band.

**Then assert the placement, because the file will parse either way.** A quick check that maps every element to its owning group catches this in seconds:

```python
groups = {m.group(1): (m.start(), s.index('</group>', m.start()))
          for m in re.finditer(r'<group name="([^"]+)"', s)}
def where(i):
    for n,(a,b) in groups.items():
        if a < i < b: return n
    return 'detail/title'
```

Confirm three things before handing the file over: the new element reports the **intended group**, the band's `y` values form the sequence you expect (a summary block reading `4, 26, 44, 62, 80, 98` is right; a lone `98` inside a 40-high band is not), and no **existing** element moved — an insert that shifts a neighbouring rule's `y` is a regression you introduced.

**Match the field's level to the band's level.** A packet-level field belongs in the record group's header; a row-level field belongs in the detail band. Putting a group-level field in a per-row band renders blank on every row, which reads like a data bug and sends you hunting in the Groovy.

## Before handing it over

- Re-verify the field contract: every `<field>` declared matches a key the rule puts, and every declared field is actually used somewhere in the layout.
- Confirm the file parses (`xml.dom.minidom.parse`) — a malformed JRXML fails at import with a much less obvious message.
- Confirm the report wont have overlapping text, or any readability issues.
- State plainly that the geometry is unproven until it runs, and name what you would look at first in the output: overlaps, orphaned headers, blank columns.
