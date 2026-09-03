# Gotchas

Things that cost real time on these reports. Read the section you need.

- [Toolchain](#toolchain)
- [JasperReports API shapes](#jasperreports-api-shapes)
- [Template layout](#template-layout)
- [Groovy business rules](#groovy-business-rules)
- [Domain model landmines](#domain-model-landmines)

---

## Toolchain

**Nothing is on PATH.** `groovy` is not installed; `/usr/bin/java` is Apple's stub. Use the
JDK inside the JasperReports Server install. `env.sh` locates it.

**Use the webapp lib directory for the classpath**, not `buildomatic/lib`. Only the webapp
directory has JasperReports plus every transitive dependency together.

**`pdftoppm` is usually absent**, so an exported PDF cannot be previewed inline. Rasterise
to PNG instead.

**Scratch directories get cleaned mid-session.** Helper scripts written to a temp dir can
vanish between commands. That is the main reason these scripts live in the skill.

**JasperReports prints a wall of log4j/SLF4J warnings** on every invocation. Filter it, or
real output scrolls away.

**Rendered fonts differ from the server's** — headless fallback, not a template change.
Do not chase it.

**Force headless mode on the bundled JVM.** On the arm64 Mac used for this workspace, the
JasperReports Server bundle carries an x86_64 Java 8 runtime. Rule execution succeeds under
translation, but Jasper compilation can abort the process with `Abort trap: 6` immediately
after `rule produced ... rows`, before it emits a Java exception. Add
`-Djava.awt.headless=true` before `-cp`; the same JRXML then compiles and fills normally.
The skill's `assets/run_template.sh` includes this flag as of 2026-09-01.

---

## JasperReports API shapes

**`JRGraphics2DExporter` needs setters, not property assignment.** There is no
`reportExportConfiguration` property; Groovy's property syntax throws
`MissingPropertyException`.

```groovy
e.setExporterInput(new SimpleExporterInput(jp))
def cfg = new SimpleGraphics2DReportConfiguration()
cfg.pageIndex = 0; cfg.zoomRatio = zoom
e.setConfiguration(cfg)
def out = new SimpleGraphics2DExporterOutput(); out.setGraphics2D(g)
e.setExporterOutput(out)
```

**`JasperCompileManager.compileReport(String)` returns in memory** and writes no `.jasper`.
Safe to run in a live working directory.

**Reports frequently produce more pages than expected** because of tall summary bands.
Check `jp.pages.size()` before asking for a page index.

**Field values are cast, not converted.** JasperReports casts each map value straight to the
field's declared class. A field declared `java.lang.Double` fed a `BigDecimal` — which is
what JSON `95.0` parses to — throws `ClassCastException` during fill, and it surfaces as a
`JRExpressionEvalException` naming whichever expression touched the field first, not the
field itself. That error message sends you looking at the expression, which is fine. The
render script coerces mock rows to the declared types to avoid this; if you build a data
source by hand, coerce yourself.

The same rule applies to Groovy interpolation: a `GStringImpl` is not a
`java.lang.String`. Groovy's `v instanceof String` can report it as String-compatible, so a
local contract check written that way passes; Jasper then fails at fill with
`Cannot cast org.codehaus.groovy.runtime.GStringImpl to java.lang.String`. End interpolated
field assignments with `.toString()`, and check `v.getClass() == String` when every JRXML
field is declared `java.lang.String`. The shared `rulecheck.groovy` uses the exact-class
check as of 2026-09-01.

---

## Template layout

**`printWhenExpression` on an element hides it but keeps its space.** Gate elements and
you get a blank strip where they were. To make a row genuinely collapse, put it in its own
**band** with a band-level `printWhenExpression` — a suppressed band contributes no height.

**`groupHeader` and `groupFooter` accept multiple bands.** This is the clean way to have
two alternative layouts: one band per variant, each with its own printWhen. `title` accepts
only one, so content that must collapse cannot live there — move it into a group header
band instead.

**JasperReports cannot resize an element conditionally.** For a box that must be two
different heights, use paired elements with complementary printWhen expressions, or two
bands.

**A group with no `groupExpression` is a single group for the whole report**, so its header
renders from the *first record only*. Any field that varies per row will show one arbitrary
value there. If the header must represent all rows, have the rule roll the values up into a
dedicated field.

**`<line>` defaults to lineWidth 1.0** while box pens are commonly 0.75. A footer drawn
with `<line>` elements will read heavier than a table drawn with cell borders.

**A general `<pen>` inside a `<box>` sets all four sides.** Overriding `leftPen` and
`bottomPen` still leaves a top border you may not want. Set the side explicitly to `0.0`.

**Adjacent cells double-strike shared boundaries.** Row N's `bottomPen` and row N+1's
`topPen` both draw the line between them. Pick one owner per boundary.

**Empty string fields render as literal text.** Expressions like
`$F{x} != null ? $F{x} : "BLANK"` print the word BLANK when the rule omits the key. Seen on
real customer receipts. Check what your mock rows omit.

**Right-aligned text with no `rightPadding` collides with the box border.** 5px matches the
convention in these templates.

**A character outside WinAnsi is dropped silently by PDF export.** Unless a `<font>` carries
`pdfEncoding="Identity-H"` and `isPdfEmbedded="true"`, JasperReports exports Helvetica in
WinAnsi and any glyph that encoding lacks simply does not appear: no error, no placeholder
box, no entry in the PDF text layer. The cell is blank and everything upstream still looks
right — the row map holds the correct value, so the rule's own assertions pass. The Case
Summary Report printed two permanently blank columns this way (a U+2713 tick for a yes/no
column), and it was found only by reading the rendered page.

Safe, because WinAnsi has them: `·` U+00B7, `–` U+2013, `—` U+2014, `•` U+2022, `…` U+2026,
curly quotes, `£` `€` `©` `®` `°` and all of Latin-1. Not safe: check marks (U+2713/U+2714),
crosses (U+2717), arrows, box-drawing, most other dingbats.

Prefer a word to a symbol on paper — `Yes` says what a tick means and cannot drop. Embedding
a font is the other fix, but it makes the report depend on that font being present on the
render server, and **no report in this corpus embeds one**, so it is unproven ground.

`rulecheck.groovy` now asserts this: *every character survives PDF export (WinAnsi)*. It
asks the real `windows-1252` encoder, names the offending field and codepoint, and runs in
the fast path — you do not need a render to catch it.

---

## Groovy business rules

**`logger` must be a binding variable in test harnesses.** Rules call `logger.debug` inside
`def` methods; a local `def logger` is not visible there.

```groovy
logger = [debug: { }]          // works
// def logger = [debug: { }]   // MissingPropertyException
```

**`map.get()` collides with `Map.get(Object)`.** Storing a closure under the key `get` and
calling `entry.get()` does not do what you want. Name the key something else.

**`case` is a reserved word.** Access such a property as `obj."case"`, and expect
`MissingPropertyException` when it does not exist — wrap speculative traversals.

**Safe navigation guards the receiver, not the result.** `r?.amountCents / 100` still throws
when `amountCents` is null, because `null.div(100)` is the failing call. This exact line
took a production report down. Prefer `r?.amountCents?.div(100)`, or guard the whole
expression.

**A debug line can kill a report.** The null-division above lived inside `logger.debug`.
Anything added purely for diagnostics should be wrapped so it cannot abort the run.

**Prefer filtering at the source over defending downstream.** The PCMS `collect()` path
expression with a predicate removes bad members before anything else sees them:

```groovy
receipt.collect("trustTransactions.trust[restitution != null].restitution")
```

But note it returns an **empty list** where a plain GPath returns **null**, so a
`x != null` test that used to be false becomes true. Check what that flips before swapping
one for the other.

**Speculative traversal pattern.** When you do not know the real path, try candidates in
order and log which one answered, so one Test run tells you the truth instead of a guess:

```groovy
def candidates = [
    [label: "trust.payment.case", fn: { safeGet(tt, "trust.payment")?."case" }],
    [label: "trust.restitution.case", fn: { safeGet(tt, "trust.restitution")?."case" }],
]
for (c in candidates) {
    def v = null
    try { v = c.fn() } catch (Exception e) { logger.debug "${c.label} threw ${e.class.simpleName}" }
    if (v != null) { logger.debug "resolved via ${c.label}"; break }
}
```

---

## Domain model landmines

**Indexing parallel collections is not the same as reading one object.** This pattern looks
fine and is not:

```groovy
caseNumber  = cases[0]?.caseNumber
courtNumber = cases?.cf_courtNum[0]
district    = cases?.locationLabel[0]
defName     = cases.defendant[0]?.fml
```

Those are four independent `[0]` lookups against four different derived collections. If any
case lacks a defendant, the lists shift relative to each other and you get a hybrid record
matching nothing real.

**Collection ordering is undefined.** `rt.cases` has no sort, so "the first case" can differ
between runs and environments. Any output derived from `[0]` on a multi-element collection
is non-deterministic. Derive per-row values from the row's own object instead.

**A receipt can aggregate several parties.** A disbursement check is funded by payments from
multiple defendants across multiple cases. Receipt-level scalars stamped onto every row will
be wrong for all but one of them.

**Check sibling reports before inventing a field.** The same figure usually already exists
somewhere. `checkOverPaymentAmountCents` on the monetary instrument was already in use in
the Payments Report; matching it kept two reports from disagreeing. Grep the report folders
before designing a new derivation.

**Match the sibling report's semantics too, not just its field.** The Payments Report
excludes voided receipts from its overpayment total and dedupes by instrument id. Copying
the field without the exclusions would have produced a figure that contradicted it.

**`User.currentUser` is whoever opens the report**, not whoever performed the transaction.
Initials and signature lines derived from it are stamped at render time, so the same
document says different things to different people. Worth flagging when it appears.

**A `<field>Label` sibling exists on some lookup fields and not others, and there is no rule
to it.** The idiom `o."${prop}Label"` is real and worth preferring — a real label beats
prettifying a code, which turns `DL` into `Dl`. But it is not uniformly available. On
`FV-PersonSummary` (The Eh Team Config, 2026-09-01) only **five of twelve** lookup fields the
screen renders carried one: `Person.namePrefix`, `Person.nameSuffix`, `Person.personType`,
`Address.addressType`, `PersonSpecialStatus.specialStatusType`. The seven that did not
included `Person.status` — while `statusLabel` exists on `Case`, `Bail` and `ADR` — and
`Identification.issuerState`, while `issuerStateLabel` exists on `PersonSpecialStatus`. The
heuristic looks sound precisely where it fails.

So **check the Data Dictionary field by field before relying on the sibling**, and write the
code-prettifying fallback as if it were the main path, because usually it is. In particular
**do not title-case an acronym**: `OK`→`Ok`, `DL`→`Dl`, `SSN`→`Ssn`, `DBA`→`Dba` all reached
a rendered page. Keeping underscore-separated tokens of three characters or fewer in upper
case fixes every real code seen so far without breaking `CELL`→`Cell` or `WORK`→`Work`.

**"Total" is not "safe" — a classifier that always picks a branch can still lose data.** A
form export names a condition and hashes it but never carries its body, so reconstructing
one is routine. Making the reconstruction *total* (every record lands in exactly one bucket)
is the right instinct, and it is not sufficient. On the Person Summary Report the Name and
Business panels were the two halves of one condition; a business misclassified as a person
printed a complete-looking two-page report with `—` as its title and "None recorded." where
the organisation name belonged, because `organizationName` was only ever written into the
branch that was not chosen. Totality guaranteed a panel; it guaranteed nothing about whether
that panel could carry the record's name.

The fix is to let **the data veto the classification**: pick the branch by the condition,
then, if that branch has nothing to show and the other one does, use the other one. A wrong
guess then costs a wrong heading — visible and reportable — instead of a silent hole.

**Read a lookup the same way everywhere in one rule.** The same defect had a second half: the
classifier tested `str(safe(p,'personType'))` while every other cell in the report went
through the label helper. If lookup properties hand back objects rather than codes,
`toString()` is a class name, every match fails, and *every* business classifies as a person
— while the header strip beside it still prints "Business", because that cell used the
helper. One raw read among twelve wrapped ones is the one to audit.

**Match whole tokens, never substrings, when testing a code.** `code.contains('ORG')` makes
`MORGAN` and `BORGIA` organisations. Split on non-alphanumerics and compare whole tokens.
