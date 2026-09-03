# Verification — the contract

*Part of the `jasper-reports` skill. Read before claiming a change is safe.*

## Two kinds of proof, and the gap between them

You can run the rule and render the page locally. You cannot prove a traversal locally.
Keep those apart in your head and in your report-back, because conflating them is how a
report ships with a silently empty column.

| Proof | How | What it settles |
|---|---|---|
| **The rule executes** | `verification/run.sh` | no syntax error, no `MissingPropertyException`, the row map has the keys the `.jrxml` declares |
| **The page is sound** | `verification/run.sh render` | geometry, pagination, grouping, the logo, no cell collisions |
| **The paths are real** | only an eSeries run | whether `party.cf_preferredAddress` exists at all |

The local harness feeds the rule a **stub object graph**, so it answers every property the
rule asks for. A typo'd path returns a fixture value locally and an empty column in
production. The harness is worth running on every change anyway: it catches the whole
class of defect that used to require a deploy and a screenshot, in about ten seconds.

## The local loop

Three files per report, in `<Report Name>/verification/`. Everything generic lives in this
skill's `scripts/`.

| File | Per-report? | What it holds |
|---|---|---|
| `Fixture.groovy` | yes | a stub object graph, plain nested `Map`s, setting `ROOT_FIXTURE`. Maps not Expandos: a missing key answers `null`, exactly as the rule's guarded accessors expect |
| `Assertions.groovy` | yes | what *this* report should say. Gets `rows`, `ck`, `fields`, `fixture`, `run`, `rootClass` in its binding |
| `run.sh` | thin | points the skill scripts at this report's rule and jrxml |
| `scripts/rulecheck.groovy` | no | runs the rule, asserts the generic contract, then evaluates your assertions |
| `scripts/render.groovy` | no | compiles the jrxml, fills it from the rule's own output, writes a PDF |
| `scripts/pdfcheck.py` | no | reads that PDF's geometry and names the defects |
| `scripts/pdfraster.py` | no | writes `<stem>_p<N>.png` beside the PDF, and clears the tail of a longer previous run |

```bash
./verification/run.sh            # assertions only, ~10s
./verification/run.sh render     # + compile, fill, geometry-check and RASTER three variants
```

Render three variants every time, because all three are pages a user eventually sees:
the populated fixture, a root that resolves but holds nothing (every section must still
print "None recorded."), and an id that resolves to nothing.

The classpath is the thing that used to make this look impossible. It is on the box, in
the bundled JasperReports Server:

```
JRS=/Applications/jasperreports-server-9.0.0
$JRS/java/bin/java                                          # the JVM
$JRS/buildomatic/lib/groovy-3.0.13.jar                      # enough to run the rule
$JRS/apache-tomcat/webapps/jasperserver-pro/WEB-INF/lib/*   # + JasperReports, commons-codec,
                                                            #   groovy-dateutil
```

## Read the PDF before you look at it

A rendered page costs roughly 2k tokens to read as an image, and most of the questions you
have about it are mechanical. `scripts/pdfcheck.py` answers those from the PDF's own
geometry for almost nothing:

```bash
SK=jasper-reports
K=$(for p in . .. ../.. ../../..; do for b in System/Skills .claude/skills; do
      [ -d "$p/$b/$SK" ] && { echo "$p/$b/$SK"; exit; }; done; done
    [ -d "$HOME/.claude/skills/$SK" ] && echo "$HOME/.claude/skills/$SK")
python3 "$K/scripts/pdfcheck.py" sample_render_full.pdf
python3 "$K/scripts/pdfcheck.py" sample.pdf --layout   # every block + rule
```

It flags four things, all of them defects this house style actually produces:

- **`rule-through-text`** — a hairline drawn across a text line. The signature of a row
  separator emitted inside the row band instead of after the row's sub-lines, so it closes
  the wrong record and strikes through a memo or a Brady tag.
- **`tight-gutter`** — two same-row cells with under 6pt between them. JasperReports wraps
  rather than overflows, so a column one notch too narrow never *collides* — it just
  leaves no daylight, which no intersection test will catch. A healthy page of this style
  keeps >12pt.
- **`overlap`** — genuinely intersecting lines, discounting the normal stacking of a
  multi-line cell.
- **`off-page`** and **`literal-null`** — content past the media box, and the swallowed-NPE
  word.

**Rasterise only for what it cannot answer**: does the page look right, is the hierarchy
legible, is the whitespace balanced. One page, once, near the end — not a page per
iteration. `pdfcheck.py --selftest` proves the predicates still discriminate.

## Rasterise inside `run.sh`, never by hand

A report's `run.sh` must call `scripts/pdfraster.py` immediately after `pdfcheck.py`, for every
variant it renders. Wire it in when you write the harness — do not leave rasterising as
something a person remembers to do.

The PNGs are the only artifact a human ever looks at, and a hand-run step falls behind silently.
The Case Summary Report carried current PDFs beside PNGs three hours older, still showing two
columns blank after that exact defect had been fixed — a picture of the bug, in the report
folder, looking finished. Nothing flags it: the PDFs were right, the assertions passed, and the
stale image sat there dated only by its mtime.

So: **if it renders, it rasters.** And when you have changed anything a reader would see, look
at the page yourself before reporting back — geometry checks answer "do cells collide", never
"does this look right".

## What still catches you out

Everything below is unchanged by the local loop, because none of it is visible without
real data.

## Swallowed NPEs — the blank that isn't an error

JasperReports swallows NullPointerException during expression evaluation and yields null. A text field then renders the literal `null`; an image renders nothing at all. Neither logs anything. So on any render, treat these as failures to chase, not cosmetic issues:

| What you see | What it means |
|---|---|
| the literal `null` in output | the key never arrived in the row map — chase the rule, not the template |
| `null ENTRIES`, `Case null` | a possibly-absent field concatenated into visible text; guard the expression *and* fix the data |
| a blank image | the image expression threw — most often `$V{}` read from a band that renders before the variable is evaluated |
| a whole column blank | a property name that does not exist; Groovy is dynamic, so it compiled fine |

Never concatenate a field into visible text without a null guard, even when the rule seeds every key — the guard is what tells you the *rule* is stale rather than the value being legitimately empty.

**When a render comes back wrong, first ask which halves are deployed.** A V2 template reading V1 data looks exactly like a broken template: new fields render as `null` or blank, new sections do not appear. Before debugging the layout, confirm the rule was Compile & Saved and the `.jrxml` was Replaced — the two deploy separately and there is nothing in the UI that pairs them.


## How the pieces fit

- The **`.jrxml`** is authored in Jaspersoft Studio — by the user, not you. It declares parameters, fields, and layout.
- The **`.groovy`** rule is edited in any editor and builds the rows.
- **eSeries is the only link.** It runs the Groovy and hands the rows to the report as `_data`. The files have no filesystem relationship, so a `.jasper` older than its `.jrxml` is normal and never worth flagging as a defect.

Edit the source, prove the mapping, show the diff, and leave build and deploy to the user's process.

## The contract

**Fields ↔ map keys** — every `<field name="x">` must match a key the Groovy puts, spelled identically:

```groovy
resMap.put("amountAllocated", st.amount.toDouble())
```
```xml
<field name="amountAllocated" class="java.lang.Double"/>
```

**Parameters** — a JRXML `<parameter name="StartDate">` reaches Groovy as **`_StartDate`**: same name, underscore prefix (`PaymentType` → `_PaymentType`, `CollectingAgency` → `_CollectingAgency`).

**Types** — `java.lang.Double` needs `.toDouble()`; `java.lang.String` needs `.toString()`. A mismatch shows up at run time as a blank cell or a cast error, never at edit time.

## The check

Run both sides and state the set difference in both directions:

```bash
grep -oE '<field name="[^"]*" class="[^"]*"' R.jrxml | sed 's/<field name="//; s/" class="/ -> /; s/"//'
grep -oE '<parameter name="[^"]*"' R.jrxml | sed 's/<parameter name="//; s/"//'
grep -oE 'put\("[A-Za-z]+"' R.groovy | sed 's/put("//; s/"//' | sort -u
grep -ohE '_[A-Z][A-Za-z]+' R.groovy | sort -u
```

A JRXML field with no matching key prints empty. A key with no field is dead work. Report both explicitly — "all 16 JRXML fields have matching keys" is a real result; silence is not.

## Failure modes, in the order they're usually the cause

None of these raise an error, which is why they cost so much time:

- **Renamed or misspelled key** → that column is silently blank. Check the mapping first, always.
- **Conditional `put`** → the key is missing on some rows, so the field is null there. `if (op > 0) { resMap.put("overPayment", op.toDouble()) }` is legitimate, but an unguarded JRXML expression will print the literal word "null". Choose deliberately: always put the key with a 0/blank default, or guard in the layout.
- **Null parameter** → criteria built from a null `_Param` can empty the entire report. Treat "it came back blank" as a parameter question before a data question.
- **Type mismatch** → blank cell or cast failure at run time.
- **Wrong version file edited** → indistinguishable from the change doing nothing.

For criteria construction, `Where`/`Or` usage, `collect()` path expressions, RuleDef calls, and reconciling figures against a case screen, read **`references/criteria-api.md`** in this skill — those traversals are easy to get plausibly wrong.

## Resolving a field question definitively

When a column comes back empty, the question is almost always "is this the right property?" — and guessing from the metadata page is how the wrong answer gets shipped. Two tools settle it:

- **Velocity Test** (see `eseries-navigation`) — pick Entity + Id, evaluate candidates side by side and read the real values:

```
nameExact=[$!{document.nameExact}] originalFileName=[$!{document.originalFileName}] storageSizeLabel=[$!{document.storageSizeLabel}]
```

  This is what proved `Document.nameExact` is empty in practice while `originalFileName` holds the file name, and that `description` returns the literal `[NO DESCRIPTION]`.

- **The folder view config** for the screen the report mirrors (see `eseries-navigation`) — its item paths are the paths the UI actually uses, which is authoritative in a way the entity metadata is not.

Known traps on `Document`: `nameExact` empty, `originalFileName` real, `storageSizeLabel` pre-formatted, `docDef.name` is the document type, `description` is placeholder text.

## Version files

Report folders hold several rule versions (`Payments_Report_V3.groovy`, `Payments_Report_V4.groovy`, an `Outdated Versions/` folder). The highest number is not reliably the live one. Establish which file eSeries runs — ask if it isn't obvious — and name the file you edited in your report back.

## Precedent beats invention

The local report corpus has dozens of working reports (on this machine, under `~/JaspersoftWorkspace/MyReports/`). Before designing an approach, grep for one that already solves the same shape:

```bash
cd Projects && grep -rl 'pattern' --include='*.groovy' .
```

Matching existing convention matters more than elegance — a small team reads these far more often than it writes them.

## Reporting back

Separate what you changed from what you proved:

1. **Changed** — which file (name the version) and the diff.
2. **Mapping check** — both sides, and the set difference.
3. **Not verified** — name the two halves separately. What the local harness proved (the rule runs, the keys match, the page has no geometric defects against stub rows) and what only eSeries can prove (every path, real pagination, real values). Say it plainly instead of letting a green local run imply the change is safe.
4. **User's turn** — any `.jrxml` edit that belongs in Studio, the deploy, an input control to add.

## A fixture must answer the way the model answers

The fixture's job is to be *the model's shape*, not to be whatever makes the assertions
green. Those are different goals, and when they diverge the harness becomes a rubber stamp
that certifies a broken page.

Concretely, on the Person Summary Report: the fixture supplied `telephoneTypeLabel` for a
`Telephone`, and label-bearing Maps for `Address.state`, `Identification.identificationType`
and `PersonAKA.akaType`. **None of those four properties exist on that model.** Every
assertion passed — including one literally named *"telephoneTypeLabel is preferred over the
code"* — while the report those same rules would have rendered in production printed `Ok`,
`Dl (Ok)`, `Ssn` and `Dba`. The fixture was answering questions the environment answers
differently, so 55 green checks proved nothing about the columns they named.

The rule: **before adding a property to a fixture, look it up in the Data Dictionary.** If
the model does not have it, the fixture must not have it either. Where the model's answer is
genuinely unknown — does a lookup return a code or an object? — encode the *pessimistic*
shape, and keep one deliberate instance of the other shape so both branches stay exercised.

This is the failure the local harness is structurally prone to, because the fixture is
written by the same person as the rule, at the same time, with the same wrong assumption in
their head. An adversarial pass with the Data Dictionary open is what catches it.
