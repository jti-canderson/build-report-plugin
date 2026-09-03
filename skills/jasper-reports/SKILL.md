---
name: jasper-reports
description: >-
  Build, change, and verify eSeries (Sustain / Symphony) Jasper reports — the Groovy business
  rule that produces the data, the .jrxml that lays out the page, and the contract between
  them. Use this for any report
  work: "build a report that shows X", "here's the ticket for this report", "add a column",
  "why is this blank", "why does it print null", "the totals don't match the case screen",
  "rename that field", or a report stack trace. Also use it for a FILE handed over with no
  instructions at all — a .jrxml, a *BR*.groovy, or an eSeries config export zip such as
  FORM-local-2026-08-21.zip / FORM=<code>.xml — because an upload with no words is itself a
  request to build the report for it. Putting a finished report INTO an environment — the rule
  editor, Reports Admin, Import vs Replace — is the `report-deployment` skill; this one stops
  at the finished files. Self-contained for building: everything needed to produce a report is
  in this skill and its references, so it can be handed to someone working from exported
  config with no live system access.
  Reach for it even when the request sounds like a one-line change, because the expensive
  failures are silent — a wrong path or a missing key empties a column without erroring,
  and the local harness cannot catch that.
---

# Jasper reports (eSeries)

## The four pieces

A report is four artifacts, and they must agree:

| Artifact | What it is | Who authors it |
|---|---|---|
| Groovy **rule** | produces the rows, assigns `_data` | you |
| **`.jrxml`** | page layout; declares fields and parameters | Jaspersoft Studio, or you as a generated file |
| **Report registration** | ties the jrxml to the rule | Reports Admin |
| **Rule inputs/outputs** | the parameters, and the `data` output | the rule editor |

**eSeries is the only thing joining the rule to the jrxml.** It runs the Groovy and hands the
rows over as `_data`. The two files never reference each other. So a `.jasper` older than its
`.jrxml` is normal, not a defect.

## What a local run does and does not prove

You can check a report locally **if the machine has a JVM, Groovy, and the JasperReports jars** —
verify that before relying on it rather than assuming. Where a workspace tracks toolchain state, it
will say (`System/CURRENT-STATE.md`). Two commands:

- `scripts/rulecheck.groovy` runs the rule against a stub object graph.
- `scripts/render.groovy` compiles the `.jrxml` and fills it from that output.

This is cheap and it catches layout defects that otherwise appear only after a deploy.

**It cannot prove a traversal.** The stubs answer every property the rule asks for. So
`party.cf_preferredAddress` returns a fixture value locally and an empty column in production.
A green run is not "it works". Say both halves when you report back. See
`references/verification.md`.

## The references

Read the one you need. You rarely need more than one or two.

| File | Read it when |
|---|---|
| `references/model-facts.md` | **FIRST, always** — model questions already answered once: entities that look right and are not, real traversals, and the traps behind them. Reading it is free; re-deriving is not |
| `references/report-rules.md` | writing or debugging the Groovy: criteria, traversals, parameters, blank or duplicated rows |
| `references/jrxml-layout.md` | authoring or fixing the page: the logo, house style, column arithmetic, sections, page breaks |
| `references/criteria-api.md` | building search criteria |
| `references/verification.md` | before claiming any change is safe |
| `references/handoff.md` | writing the folder's `HANDOFF.md` and the client-facing Deployment Guide |
| `references/gotchas.md` | Groovy and domain-model traps |
| `references/adversarial-review.md` | the critic's brief: when it fires, what to hand it, the questions it asks |

## Where facts come from

Work from whatever is authoritative. In this order:

**1. Exported config, if you have it.** A **Data Dictionary export** (`.xlsx`, from System
Setup → Metadata → Entities) lists every entity, field, type, lookup code, relation and
widget for that environment. Read it with the `data-dictionary` skill. Ask for one if you
have none.

An exported **folder-view config** is the authoritative source for which paths the UI
actually uses. Prefer both over inference.

Never trust the read-only entity view page. It misreports types: `Date` for `timestamp`,
`String (Clob)` for `materialized_clob`.

**2. The existing corpus.** Wherever this site keeps its built reports, there are dozens of
working examples. Find one that solves the same shape and copy its conventions. Ask where the
corpus is if you do not already know — in a JTI AI workspace it is `Projects/<Client>/`; older
setups kept it at `~/JaspersoftWorkspace/MyReports/<Client> Reports/`:

```bash
cd <corpus-root> && grep -ril 'keyword' --include='*.groovy' --include='*.jrxml' . | head
```

**3. The live admin**, only if neither of the above exists. The entity metadata index gives
class names and relations. The folder view config gives real paths. The Velocity Test page
settles "is this the right field?" against real data.

Site-specific config is prefixed: a custom **entity** is `C_Something`, its custom **fields**
are `c_something`, and on a folder-view path a custom field reads `cf_something`. A path
segment with no prefix is a stock platform property.

Map every column in the request to a real field **before** writing code. With a screenshot,
do it column by column. A column you cannot source is a question worth asking.

## The report folder

**Everything for a report lives in one folder named after the report.** No loose files
beside it. The folder name is the report's human Name, with spaces. Create it before writing
the first file.

```
<Report Name>/
  <Report_Name>_V<n>.groovy   the rule source; bump the version only once one works
  RULE-<Report_Code>.zip      the rule as an importable export, if one was produced
                              (see the report-deployment skill)
  <Report_Name>.jrxml         the layout - generated, never hand-edited
  gen_jrxml.py                the generator that emits the .jrxml
  journal_mark.b64            logo asset, copied here so the folder stands alone
  RULE_REGISTRATION.txt       what to type into the empty rule form
  JRXML_CONTRACT.txt          fields, grouping, geometry, what is and is not verified
  verification/               Fixture.groovy, Assertions.groovy, run.sh
                              run.sh is COPIED from assets/run_template.sh - do not
                              write one from scratch; the template carries the raster
                              step and the walk-up skill lookup
  HANDOFF.md                  the living handoff context
  Deployment Guide- <Report Name> (<Report_Code>).docx
  Outdated Versions/          superseded rules, once there is more than one
```

File stems use `Title_Case_With_Underscores` and match the rule Code and the Reports Admin
code. One grep then finds every piece.

The folder is what gets handed on, promoted to another environment, or picked up in six
months. It must answer "what is this and how do I deploy it" with no conversation attached.
That is why the `.txt` files are not optional.

### How it reaches an environment — context, not your job

You are not deploying anything. But three facts about deployment change how you build, so
know them:

**The user registers the report themselves**, in two steps: the rule first, then the report
registration that points at it. The registration declares the parameters, so the names in
your `.jrxml` and the names in the rule must match exactly — that is the seam a deploy
exposes.

**The rule needs an output parameter `data` / `REQUIRED` / `java.util.List`.** Without it the
report renders nothing while everything reports success. You cannot add it; the user does.
What you can do is write `RULE_REGISTRATION.txt` so they cannot miss it.

**Nothing syncs between environments.** Rules, reports and ids are per-environment. So every
id you write down carries the environment with it, and a report built once still has to be
deployed everywhere it is wanted.

That is why `RULE_REGISTRATION.txt` is not optional: it is the whole deployment, written out,
for someone at a keyboard. For the screens themselves, and for generating an importable rule
zip, use the **`report-deployment`** skill.

### `HANDOFF.md`

**Every report folder carries one, and updating it is part of the change.** Not a step after
it.

It answers "what is this, where does it live, what is proven, what is left" for whoever picks
the report up next — including you, months later, with none of this conversation.

Write it the first time you touch a report. Update it in the same turn as the rule or the
jrxml, before you report back. A handoff that lags the artifacts is worse than none, because
it gets believed.

It carries, in order: the ticket and report code; the artifact table with per-environment ids
and their state; the local files; parameters and how they arrive; entities and paths,
including every wrong guess that was corrected; the rule's logic in numbered steps; the
output fields by section; anything hand-rolled and why it is fragile; the deploy steps; open
items and what is unproven; and a dated client-request log. Template in
`references/handoff.md`.

**Name the environment with every id.** Write "rule 10442 in <the environment you were on>",
never "rule 10442". Ids are per-environment primary keys. A bare id sends the next person
editing the wrong record on the wrong site.

The **`Deployment Guide- <Report Name> (<Report_Code>).docx`** is the corpus convention for
handing a report to a client or attaching it to a ticket. Generate it from `HANDOFF.md`
rather than writing it twice. Regenerate it when the handoff changes materially: a new field,
a new parameter, a corrected path, a gap closed.

## An upload *is* the request

A file arriving with no instructions means **build the report for it**. Do not ask what to do
with it.

Two shapes turn up. They hand you opposite halves of the job:

| Upload | What it gives you | So the work is |
|---|---|---|
| `Report.jrxml` | the contract — fields, parameters, groups, layout | write the rule that satisfies it |
| `FORM-<env>-<date>.zip` | the root entity and the real field paths behind a screen | design the report that mirrors that screen |

### Intake: settle the environment before deriving any path

Run this before writing a traversal, not after. **A field path is only true of one
environment.** Entities, custom fields and lookup lists differ per environment and never sync,
so a path copied from the corpus or from memory is a guess about the target — and a wrong guess
empties a column with no error.

**1. Which environment is this for?** A `FORM` export answers this itself: `srcActionUrl` names
the host it came from, so quote it back rather than asking. A `.jrxml` carries no environment
at all, so ask.

**2. Do I have a Data Dictionary for *that* environment?** Check what you have been given:
the filename is `DataDictionary-<environmentLabel>-<YYYY-MM-DD>.xlsx`.

- **A dictionary for the target environment** — use it, via the `data-dictionary` skill.
- **A dictionary for a different environment** — nearly as bad as none. It tells you what a
  *different* site has. Use it for shape and idiom, never to assert a field exists.
- **None** — ask for one, and say why: *"Please upload a Data Dictionary from that
  environment — System Setup → Metadata → Entities, then the Data Dictionary button. Without
  it I can name plausible paths but cannot confirm they exist there."*

**A `FORM` export from the target environment is a partial substitute** and often enough on its
own: every path in it is one that environment actually renders. It covers the entities on that
screen and nothing else, so it answers the report you were handed while telling you nothing
about the next one.

**Check the date.** An export predates any config change made since. If entities or fields have
been added in that environment recently, the dictionary does not have them and asking for a
fresh one costs the user one button.

**Do not block on this.** Read the contract out of the upload, list the fields, map what you
can, and raise the gap as one question at the point it blocks you — not as a preamble before
you have looked at the file.

### A `.jrxml`: the template is the contract

The template is authoritative. The rule conforms to its field and parameter names, never the
other way round.

Read the contract out of the file before writing any Groovy:

```bash
grep -oE '<(field|parameter) name="[^"]+" class="[^"]+"' Report.jrxml
grep -oE '\$F\{[A-Za-z0-9_]+\}' Report.jrxml | sort -u   # fields actually placed on the page
grep -oE '<group name="[^"]+"' Report.jrxml                # sections the rule must feed
```

The two greps rarely agree. A declared field never placed on the page is dead weight. A
`$F{...}` with no declaration is a broken template — flag it before building to it.

Every declared field needs a key in the rule's base map, or that column silently empties.

What the template cannot tell you — ask these, and only these (the environment and the
dictionary are already settled by the intake above):

1. Which entity is the report root?
2. The source path for any column whose name is ambiguous.
3. For any money column: which measure — assessed, paid, or allocated? They differ, and the
   difference is not cosmetic. See the `financials` skill.

### A config export zip: the screen is the spec

An eSeries export is a zip of `<ROOT>=<code>.xml` files. Each is a `ConfigExportRsp` wrapper
whose `srcContent` is HTML-entity-escaped JSON. Do not read it by eye. Run the parser.

It lives in this skill's `scripts/` directory. Your working directory is the user's project,
not the skill, so resolve the skill directory first — this one line works whether the skill sits in
a JTI AI workspace or a plain `~/.claude/skills/` install:

```bash
SK=jasper-reports
K=$(for p in . .. ../.. ../../..; do for b in System/Skills .claude/skills; do
      [ -d "$p/$b/$SK" ] && { echo "$p/$b/$SK"; exit; }; done; done
    [ -d "$HOME/.claude/skills/$SK" ] && echo "$HOME/.claude/skills/$SK")
S=$K/scripts/formexport.py
python3 "$S" ~/Downloads/FORM-local-2026-08-21.zip             # start here: panels, headers, paths
python3 "$S" ~/Downloads/FORM-local-2026-08-21.zip --json      # conditions, sorts, formats
```

**Two calls, not four.** The default view already contains the paths and the widget
templates. `--paths` and `--velocity` just re-print what you have read; they are narrowing
views for when the default is too noisy.

What the default omits is per-item metadata: `conditions`, `sort`, `customFormat`,
`conditionalFormats`, `dateFormat`, `columnStyles`. That is what `--json` is for, and you
will want it. Conditional formats are where "print a tick when the value is yes" lives.

The parser takes the zip or a single extracted `FORM=<code>.xml`. A multi-record export
prints each member in turn.

A `FORM` export is the **best path source that exists** — better than entity metadata,
because every path in it is one the screen actually renders. It gives you three things:

- **`rootEntity`** — the report root, decided for you.
- **The paths.** `cf_` marks a custom field, `[]` marks the collection being iterated. Copy
  them verbatim.
- **`columnHeaders` mapped onto the items carrying `newColumn`** — the labels the client
  already recognises. Reuse them as column headings and the report reads like the screen.

Two facts about the wrapper. `srcActionUrl` names the source environment, so quote it rather
than asking which environment it came from. `srcId` is that environment's primary key only —
never carry it anywhere else.

`formItems` is **flat**, ordered by `num`. A panel (type 2) owns every item after it until
the next panel. That is also why a widget or static item inherits `$object` from the item
before it.

### A `RULE` export is importable

So a rule can be handed over as a file instead of retyped. Generating one is the
**`report-deployment`** skill's job — it holds `rule_import.py` and the format detail.

### Asking for what is missing

**Always a numbered list. One question per line. Nothing else in it.**

```
1. Which entity is the report root - Case, or the packet itself?
2. "Agency" - is that case.location or the assignment's agency?
3. Which environment does this deploy to?
```

Numbered so the user can answer "1 is Case, 3 is QA" without quoting anything back.

Do not bury a question in a paragraph. Do not stack three into one bullet. Do not pad the
list with anything you could settle yourself from the Data Dictionary, the corpus, or the
folder view config — a question you could have answered costs the user more than it costs
you.

Ask at the point they block you. Do every part of the work that does not depend on the answer
first. A report finished except for two labelled unknowns beats three questions and no code.
State the assumption you proceeded under next to each question, so a silent user still gets
something that runs.

## The sequence

1. **Precedent** — find a comparable report and match its conventions. **Choose ONE, by
   shape, before you open any of it.** List the report folders, pick the one whose shape
   matches ("single record, panels off a folder view export" → the Case Summary Report),
   and read only that. Reading a second precedent because the first turned out to be the
   wrong model costs more than every other step combined: on the Person Summary Report it
   was ~1,300 lines of the right precedent read *after* most of the wrong one. If two look
   plausible, `head -20` each handoff and decide from that, not from the whole folder.
   Budget for a report of this shape is one skill + one precedent + targeted Data
   Dictionary queries — not the reference set. Load `criteria-api.md` only when you are
   actually writing criteria; a report that does one `get(id)` needs none of it.
2. **Model** — confirm entities, relations, and exact paths. A relation reads
   `field - fk - TargetEntity - cardinality - peerName`. The peer name is your traversal from
   the report root.
3. **Parameters** — a JRXML `<parameter name="StartDate">` reaches Groovy as **`_StartDate`**.
   Naming is inconsistent across the corpus (`_receiptId`, `_CaseID`, `_paymentStartDate`);
   match the report you are modelling on. Values arrive as **Strings** whatever the declared
   class.
4. **Row shape** — eSeries passes a single `_data` collection. A report with several visual
   tables ships as one flat `List<Map>` with a `section` discriminator. Seed every key in a
   base map, make every field a String, pre-format dates and sizes. See
   `references/report-rules.md`.
5. **Contract** — emit the field list the `.jrxml` must declare, then check both sides agree.
6. **Verify locally** — copy `assets/run_template.sh` to `Verification/run.sh` and fill in
   its PER-REPORT block; write `verification/Fixture.groovy` and `Assertions.groovy`; then
   `./verification/run.sh render`. Fix what it finds before anyone sees the report. Do this
   *before* the handoff, so the handoff states what was actually proved.

   **If it renders, it rasters — and then you look.** The template writes a PNG per page
   beside each PDF. Open them. A green geometry check answers "do cells collide", never
   "does this read right", and a raster that nobody looked at is worth nothing. Never leave
   rasterising as a manual step: when it was one, a report folder held page images still
   showing two blank columns three hours after that defect was fixed.
7. **Adversarial review** — hand the finished rule to one critic agent whose only job is to
   break it. One agent, not a fan-out. It asks four questions about the task before any about
   the data — did this do what was actually asked, is the problem *mechanically* fixed, where
   is this guessing, and what one question would settle the biggest guess fastest — then the
   data questions in `references/adversarial-review.md`. Answers must be data states, not
   opinions. Fold what it breaks into the fix, carry what it tried and *could not* break into
   **Verified**, and carry any unresolved guess into **Needs your input** as the question the
   critic phrased. It fires when a wrong answer would look as plausible as a right one — not
   merely when the logic is long; if you can compile, Execute or probe it instead, do that.
8. **Registration text** — write `RULE_REGISTRATION.txt`: Code, Name, Category `Reports`, a
   one-line Description, Transaction End `false`, Engine `SCRIPT`, every **input** row as
   *name / REQUIRED|OPTIONAL / class* (bare name, no underscore, matching the JRXML
   `<parameter>` exactly), and the **output** row `data` / `REQUIRED` / `java.util.List`.
   This is documentation for the person deploying, not something you action.
9. **Handoff** — write or update `HANDOFF.md` before you report back.
10. **Report back** — **show the rendered pages**, then a files table, then **Verified**
    (what you actually ran), **Not verified** (never empty — a local render proves layout,
    never traversals), and **Needs your input** (numbered list). Keep it short. Reasoning
    belongs in the `.groovy` header and the contract file, not the message.

    The pages come first because they are the only part the user can check themselves. Send
    the PDFs and show the page images whenever you have built or changed anything a reader
    would see — do not make them ask, and do not substitute "the harness is green" for a
    look at the page. For a one-line change with no visual consequence, say so and skip it.

## Hard rules

**You do not touch eSeries in this skill.** Building a report means producing files. If the
work turns into driving the admin — the rule editor, Reports Admin, running the report — that
is the `report-deployment` skill, and its staging rules apply: never press a commit control,
stage and hand over.

**Say what you did not verify.** A local render proves the layout against stub data:
geometry, pagination, grouping, and that the rule executes. It proves nothing about the
model, because the stubs answer every property the rule asks for. Real data, real traversals
and real pagination are unproven until eSeries runs it. Never let "I rendered it" stand in
for "it is right".

**Version files matter.** Report folders hold several rule versions
(`Payments_Report_V3.groovy`, `_V4.groovy`, an `Outdated Versions/` folder). The highest
number is not reliably live. Establish which file eSeries runs, and name the file you edited.

## Related skills, if installed

- `financials` — **read this before writing any report with an amount in it.** The financial
  model splits a payment down two branches, and a report that walks one under-reports with no
  error
- `report-deployment` — putting a finished report into an environment
- `velocity-widgets` — a button or link that launches a report from a folder view
- `eseries-navigation` — getting around the admin
- `folder-view-forms` and `adding-entities` — folder views and entity fields

A `FORM` export zip is shared ground. Read it **here** when the goal is a report; read it in
`folder-view-forms` when the goal is editing the form. None are required — this skill, its
references and its scripts stand alone.
