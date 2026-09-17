---
description: Build an eSeries Jasper report from a JTI house template
argument-hint: [anything you already know - project, template name, what the report should do, or a folder-view zip]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Skill, AskUserQuestion, Task, SendUserFile
model: sonnet
---

# /build-report

Walk the user to a finished report. **Four questions, in this order.**

`$ARGUMENTS`

## 0. Locate the plugin — FIRST, before anything else

`${CLAUDE_PLUGIN_ROOT}` is only set when this is installed as a real plugin. Installed as a
plain user command (a file in `~/.claude/commands/`) it expands to EMPTY, every path below
becomes `/scripts/project.py`, and every command fails. Resolve it once:

```bash
for p in "$CLAUDE_PLUGIN_ROOT" "$HOME/.claude/plugins/jti-reports" \
         "$HOME/JaspersoftWorkspace/MyReports/jti-reports-plugin"; do
  [ -n "$p" ] && [ -f "$p/scripts/project.py" ] && echo "PLUGIN $p" && break
done
```

Use the printed path **literally** everywhere this file writes `${CLAUDE_PLUGIN_ROOT}`.

**If nothing prints, STOP and ask the user where the plugin is.** Do NOT go looking for it.
A `find` over `$HOME` wanders into `~/Library/Application Support`, which makes macOS throw
up *"claude would like to access data from other apps"* — a scary, unexplained privacy
prompt, caused by a missing variable and nothing else. Searching also takes minutes and
usually fails anyway. The plugin is in one of the three places above or the user knows where
it is; there is no third option worth a filesystem crawl.

## Before asking anything

Read `$ARGUMENTS` and any attached file, and answer from it whatever you can.
**Never ask a question the user has already answered.** A message like
"OKDAC, a grouped summary, payments by agency for a date range" answers three of the four —
ask only the one that is left.

**An attached picture answers question 3** - a screenshot, a PDF or a report from another
system is a Custom answer already given. Read it, name the nearest template, confirm in one
line, and never show the menu.

**An attachment NEVER answers question 1, and WHERE THE FILE CAME FROM IS NOT A PROJECT.**
A file arrives from `~/Downloads`, the Desktop, or a Slack folder because that is where the
browser dropped it — it says nothing about which client the report is for. Deriving a
project from an attachment's path (and then, when that path is outside the root, creating a
`Downloads` folder *inside* it) invents a client out of a filesystem accident, and leaves a
junk folder the user has to notice and delete. Happened 09/09.

Question 1 is ALWAYS asked, with `AskUserQuestion`, against the real project list. The
export tells you the entity and the environment; the user tells you the project.

A `FORM-*.zip` or `FORM=*.xml` attachment answers question 4 on its own, and usually
question 3 as well (its panels tell you the shape). Parse it, do not ask about it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jasper-reports/scripts/formexport.py" <the zip>
```

## How to ask

**ONE question per message. Then STOP and wait for the answer.** Do not run ahead to the
next step in the same turn, and never put two questions in one message - it reads as one
question and the first gets answered while the second is silently dropped.

**That includes two `AskUserQuestion` questions in one call.** The call accepts four, and
they render as four prompts the user answers all at once - correct for four different
questions, wrong for one question split in half. A list longer than the four-option cap is
asked as a SEQUENCE, never as parallel prompts. See question 1.

**Anything with a fixed set of answers uses `AskUserQuestion`, so the user clicks instead
of typing.** That means question 1 (project) and question 3 (template) ALWAYS. Only
question 4 is free text.

Short. Direct. One line. No preamble, no restating the question back, no explaining why
you are asking.

Good: `Which project?`
Bad: `Before we get started, I'd like to understand a bit more about which client this
report is intended for, since that affects where the files will live.`

Never attach the example **PDFs** - five documents at once buries the question. The
labelled **PNGs** are the exception and they are REQUIRED at question 3: a name with no
picture is not a choice anyone can make. See step 3.

---

## 1. Which project?

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" list
```

`AskUserQuestion`. **Never skip this and never infer it** — not from an attachment's
folder, not from the environment named in an export, not from the report's subject. Those
identify the SOURCE; the project is where the work should LAND, and only the user knows that.

**The FOUR-option cap applies here too.** It is documented at question 3 for the templates
and it bites just as hard on a workspace with five projects plus **New project**. Handle it
the same way — and read the rule below before improvising, because the obvious improvisation
is the one that already went wrong.

- **Four or fewer** (projects + New project): one question, all of them.
- **More than four:** the three most likely, then `Something else`. Ask the second question
  ONLY if they pick it, in its own message, listing the rest plus **New project**.

Order the three by what the request already tells you — the client or environment named in
`$ARGUMENTS` or an attached export, otherwise the project holding the most reports. The
free-text **Other** box is always there, so someone whose project is not in the three can
simply type it.

### NEVER split one question across two questions in one call

`AskUserQuestion` takes up to four QUESTIONS, and it presents them all at once, each
expecting its own answer. That is for genuinely different questions. Splitting a single
list — "Which project?" and "Which project? (more options)" — produces two prompts the user
must both answer, so they pick one project in each and neither is wrong. You then have two
different answers to a question with one right answer, and you have to ask a third time.
Happened 09/17: the list came back `OKDAC Reports` and `Test Builds`.

A list too long for one question is a SEQUENCE — question, wait, then a follow-up only if
needed — never two parallel prompts.

The list prints the root it resolved and why. If a project the user expects is missing, the
ROOT is wrong — say so and stop; do not offer to create a replacement folder.

Then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" resolve "<name>" --create
```

Everything after this lives in that folder.

**The plugin works only inside the folder the session was started in.** `project.py`
resolves every path under the working directory and REFUSES anything that escapes it, so a
project is either that folder (listed as `(here)`) or a folder under it. If the user wants
to build somewhere else, that is a new session started in that folder - do not reach for it
from here, and do not work around a `REFUSED` by using absolute paths or shell commands.
The point of the scope is that pointing the plugin at a folder is the whole permission
grant; a tool that writes outside it is one you would have to supervise.

## 2. SDK / JAR

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" sdk-status "<project folder>"
```

The command always exits 0 - the first word is the status.

- **NONE / MISSING** → ask for it, **say what it is for, and say where to get it**. Someone
  asked for a "JAR/SDK" with no reason given has no way to judge whether it is worth the
  two minutes, and mostly says skip:

  > Send me the JAR/SDK for `<project>`, or say skip.
  > It is the list of every field and record type in *your* environment — it is what lets me
  > check a field really exists before the report ships, instead of guessing at its name.
  > In eSeries: **System Setup → Metadata → Entities**, then **Download SDK** at the top right.

- **OK** → `AskUserQuestion`: *SDK on file: `<filename>` (registered `<date>`).* Options:
  **Still current** / **I'll send a newer one**.
- **STALE** → same, but lead with the age: *`<n>` days old.*

Give the same directions again whenever they pick **I'll send a newer one** — knowing the
path once does not mean remembering it a month later.

**Then stop.** Do not show the template menu until this is answered.

### If they ask why it matters, or are about to skip

Say this much, in plain words — no jargon, and never more than a few lines:

**Without it, a wrong field name fails silently.** Groovy does not check field names, so
asking a record for a field it does not have returns nothing at all rather than an error.
The report compiles, deploys, runs, and prints a blank column. Nothing anywhere says it went
wrong. The SDK is the only thing that catches that BEFORE the report ships instead of after
someone notices the numbers are missing.

**It is per-environment.** Field names and record types differ between clients and even
between districts. OKDAC's SDK cannot answer a question about another client's system, so
"we already have one" only counts if it is *theirs*.

**A real example, worth one line if they push:** for the login report, the SDK is what
proved `LoginAudit` — the obviously right-sounding record — is an empty shell with no fields,
and that the "last login date" field is never actually saved. Both look correct in the docs.
A report built on either returns an empty page, and only the jar showed that in advance.

That said, **do not block on it.** If they skip, carry on and build the report — just say
plainly in the handoff that no field was verified against their environment, so a blank
column is a real possibility on the first run.

To save one the user provides:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" sdk-register "<project folder>" "<file>"
```

If they say skip, note it and carry on — but say plainly in the handoff that local
verification ran against this machine's JasperReports and not the client's, so the layout
is proven and the field names are not.

## 3. Which template?

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/templates/catalog.py"
```

**ALWAYS send the six labelled previews first, then ask.** Not on request - every time,
in the same turn, before the question. Send all six in ONE `SendUserFile` call with
`display: "render"`, in A-F order:

```
${CLAUDE_PLUGIN_ROOT}/templates/examples/labeled/JTI_Record_Summary.png
${CLAUDE_PLUGIN_ROOT}/templates/examples/labeled/JTI_ESeries_Summary.png
${CLAUDE_PLUGIN_ROOT}/templates/examples/labeled/JTI_Tabular_List.png
${CLAUDE_PLUGIN_ROOT}/templates/examples/labeled/JTI_Grouped_Summary.png
${CLAUDE_PLUGIN_ROOT}/templates/examples/labeled/JTI_Statement.png
${CLAUDE_PLUGIN_ROOT}/templates/examples/labeled/JTI_Wide_Table.png
```

Each carries its NAME in a navy band above the page, so the picture and the option label
match without the user holding a mapping in their head. **There are no letters** - the menu
is ordered by what the report sounds like, so a letter and its position disagreed and the
user had to cross-reference a shifting list. Never reintroduce them. **This is the one place six files
at once is right** - they are one comparison, not five documents, and asking someone to pick
between "Record Summary" and "eSeries Screen" as bare words is asking them to guess.

**Then ask with `AskUserQuestion`** so the letters are clickable. Do not print the text
menu; the catalog output is for you, not them.

**`AskUserQuestion` accepts at most FOUR options.** Six templates plus Custom is seven, so
they do not fit in one question and an attempt to list them all silently drops the tail -
that is how the last option went missing the first time this ran. Ask in two steps, and
only reach the second if they pick the fourth.

**Put the three that best fit the request first**, and say so plainly in the labels. The
options are NAMES, never letters.

*First question* - `Which template?`

| Option | Label |
|---|---|
| 1 | the best fit, e.g. `Record Summary` |
| 2 | second best, e.g. `eSeries Screen (looks like the application)` |
| 3 | third, e.g. `List` |
| 4 | `Something else` — *name the three not shown, or send a picture* |

*Second question, only after `Something else`* - `Which one?`

| Option | Label |
|---|---|
| 1-3 | the three templates not offered above, by name |
| 4 | `Custom - I'll send a picture` |

All six previews were already sent above, so both questions are asked against pictures the
user is already looking at. Order the FIRST question by what the report sounds like - if
question 4 is already answered and it reads like a grouped total, lead with `C`.

**A screenshot of an eSeries screen is the eSeries Screen template, not Custom.** Say so and confirm in one
line rather than opening the Custom branch - it already is that look, and starting from it is
faster and safer than composing a layout from primitives.

### Custom — they send a picture

`Send a picture of what you want it to look like.` Accept a screenshot, a PDF, a report from
another system, a photo of a printout, or a folder-view zip.

Then **read it and say what you are going to do before doing it**, in two lines:

> That's a grouped list with subtotals — closest to **C**. I'll keep the JTI masthead and
> fonts and match your columns and grouping. Sound right?

Three rules for what comes next:

1. **Start from the nearest template, never from a blank file.** Every template is a Python
   generator; a custom layout is that generator called with different columns, or in the rare
   case nothing fits, a new generator composed from `jti_style` primitives (`document()`,
   `text()`, `parse_cols()`). **Never hand-write a `.jrxml`** - the house style, the column
   maths and the overflow guards all live in that module, and a hand-built file loses them
   silently.
2. **Copy the STRUCTURE, keep the JTI STYLE.** Columns, grouping, totals and section order
   come from their picture. Navy, fonts, masthead and margins stay ours - a screenshot from
   another vendor's system would otherwise drag that vendor's look into a JTI report. If they
   explicitly want the picture's styling too, that is fine, but they have to say so.
3. **Say what you could not honour - but CHECK before you call anything impossible.**
   Read `jti_style.py` first. Almost everything that looks like a limit is not one:
   `rect(x, y, w, h, fill)` takes any hex colour and `text(..., color=)` any forecolor, so
   coloured banners, badges, status pills, tinted section headers and blue link-styled text
   are three lines each. Images embed as base64 the way `logo()` does. **Do not tell a user
   their colours become "plain text" - that is a false limit, and it reads as a refusal of
   the thing they actually asked for.**

   The real limits are narrow, and only two of them are absolute:
   - **Interactivity.** Hover, clicks, filter boxes, expand/collapse carets, tab strips,
     sortable headers. A PDF is paper. Action icons CAN be drawn if you have the glyph -
     they just will not do anything, so say "drawn but inert", not "dropped", and let the
     user choose.
   - **Charts.** No template produces one.

   Width is a trade-off, not a limit: more columns than fit portrait is what Wide Table (landscape)
   is for, and past that it is a font-size and column-priority conversation.

4. **"Make it look like the screenshot" is a legitimate and complete answer.** When the user
   says that - especially after being offered the JTI styling once - build it that way and
   stop re-offering house style. Matching a folder view closely usually means a NEW generator
   composed from `jti_style` primitives rather than an existing template called with
   different columns, because the section-header, column-header and header-block structure of
   an eSeries screen is not any of A-E parameterised. That is expected, it is supported, and
   it is not a reason to talk the user back toward a template.

**Never regenerate a sample to answer this question.** They are rendered and on disk; a
re-render is slow and nothing about it is per-project. If a template changes, re-render it
and re-run `templates/label_examples.py`, which restamps every name from the originals.

| Template | Labelled preview |
|---|---|
| Record Summary | `labeled/JTI_Record_Summary.png` |
| eSeries Screen | `labeled/JTI_ESeries_Summary.png` |
| List | `labeled/JTI_Tabular_List.png` |
| Grouped Summary | `labeled/JTI_Grouped_Summary.png` |
| Statement | `labeled/JTI_Statement.png` |
| Wide Table (landscape) | `labeled/JTI_Wide_Table.png` |

If a folder-view export was supplied, name the template its shape implies and ask only for
confirmation.

## 4. What should the report show?

Free text - this is the one question `AskUserQuestion` does not fit. Ask once, plainly:
`What should it show?`

Accept any of:
- a sentence
- a ticket
- a column list
- a screenshot
- **a zipped folder view** — which answers it completely; its panels, paths and column
  headings become the report

---

## Model routing — cheap by default, Opus only where it earns it

This command runs on **Sonnet** (frontmatter `model: sonnet`) — the driving is asking four
questions and running Python, which needs nothing more. The expensive intelligence is pushed
into subagents, each pinned to the smallest model that does its job. Verified against the
Claude Code docs 2026-09-02: command frontmatter sets the session model for this command;
subagents pin their own model independently; there is no way to switch the main model
mid-run, so routing is done by *choosing what to spawn*.

Spend the money only where it is needed:

| Work | Spawn as | Model |
|---|---|---|
| grep the corpus, dump `javap`, read a Data Dictionary cell | `Task` subagent | **haiku** |
| write the rule + jrxml for a shape already in the corpus | inline on Sonnet, or a `Task` | **sonnet** |
| **new-domain model discovery** (which entity, is it searchable, real traversal) | `Task` subagent | **opus**, effort high |
| **adversarial verify** of a traversal a wrong answer would hide | `Task` subagent | **opus**, effort high |

**The adaptive part is a decision, not a setting.** Before spawning ANY discovery agent,
read `${CLAUDE_PLUGIN_ROOT}/skills/jasper-reports/references/model-facts.md`. If the entity
and traversal are already written there, the domain is known — **skip discovery entirely**,
write the rule on Sonnet, and no Opus agent ever spawns. Opus is reached for only when the
model question is genuinely unanswered, and the answer is written back so it is free next
time. A report on a known shape (payments, past due, a folder-view export that hands you the
paths) should cost a Sonnet session and nothing more.

Do not launch a multi-agent fan-out for a question one `javap` or one corpus grep settles
inline. The fan-out is for a novel domain where a plausible-but-wrong path would survive a
single look — not for confirming what is already known.

## Then build

**Read `${CLAUDE_PLUGIN_ROOT}/skills/jasper-reports/references/model-facts.md` BEFORE any
model search.** It holds the answers that already cost real money to find — which entities
look right and are not, the real traversals, and the traps. Checking it is free; a fan-out
that re-derives what is already written there is the most expensive mistake in this
pipeline. Add to it whenever a model question takes more than a couple of minutes.

Follow the `jasper-reports` skill from step 1 of its sequence. It is bundled here, so
invoke it rather than working from memory:

```
Skill(jasper-reports)
```

Everything lands in `<project folder>/<Report Name>/`.

### Scaffold the boilerplate — do not type it

Write a short `spec.json`, then generate the three files that carry no decisions:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" --example    # the spec format
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" spec.json --out .
```

It writes `gen_jrxml.py`, `verification/fixture.py` and `verification/run.sh` — ~170 lines
expressing maybe 15 lines of actual choices. Writing them by hand is three or four turns and
several thousand of the slowest kind of token, to reach a file that was always going to be
the same shape.

**It will not overwrite an existing file without `--force`**, because a re-scaffold would
destroy exactly the two things worth keeping: the fixture rows and any hand-edit to the
generator.

Then author the parts it deliberately leaves alone:

1. **the `.groovy` rule** — every line of it is a decision
2. **real fixture rows**, replacing the `TODO`s. Make them AWKWARD: the label too long for
   its column, the row with a field missing, the hyphenated identifier. Tidy rows prove
   nothing — every layout defect this harness has caught came from an ugly row.

This is generation, not pruning. Never build a "template with everything" and delete from
it: the generators compute column geometry from relative widths, so a removed column leaves
a hole rather than a narrower table, and a stranded `<field>` empties a cell in silence.

### While iterating, render ONE variant

```bash
./verification/run.sh render full     # ~9s
./verification/run.sh render          # every variant, ~11s — before reporting back
```

Every variant is filled from ONE compile in ONE JVM, so the second one is nearly free now;
narrowing to `full` during a fix loop still saves a couple of seconds. **Render every
variant before you report back** — an unexamined page is worth nothing.

### Ask the model questions in batches, not one at a time

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdk_fields.py" Case caseType filingDate statuses ...
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/refs.py" model-facts criteria-api
python3 "$SKILL/scripts/entity_field.py" county payPlan balance
```

All three cost the same for twenty names as for one — javap dumps the whole class, `refs`
reads files off disk, `entity_field` text-extracts the PDFs once. Asking one name per call
turns twenty questions into twenty turns, each re-sending the whole conversation first.

`sdk_fields.py` walks the whole `extends` chain and reports the field owner and the getter
owner separately, because they differ constantly — `Case` declares `caseType` while
`getCaseType()` lives on `CaseComponent`. **Read its closing note before concluding
anything from a `stripped` body**; it does not mean the getter is dead.

Before reporting back, run the gates — **one command, from inside the report folder**:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/finish.sh" <rule>.groovy <report>.jrxml \
    --code <Code> --name "<Human Name>" --template <template module>
```

It runs contract_check, `verification/run.sh render` and `rule_zip.py` in that order and
stops at the first failure. Do not run them separately: it is three turns instead of one,
and the order matters — contract_check is instant, the render costs ~20s, so a contract
fault has to stop the run before the JVM starts.

Then **look at every rendered page** and show them.

### Every report ships three files. The zip is not optional.

`<Report Name>/` must end up holding the `.groovy`, the `.jrxml` **and** `RULE-<Code>.zip`.
The zip is how a person loads the rule in ONE action instead of retyping the script into
CodeMirror and adding every parameter row by hand - the longest and most error-prone part of
a deploy, and the part where a missed `data` / `java.util.List` / `REQUIRED` row silently
produces a blank page. It is also the only artifact that travels to another environment.

Do not hand-list the parameters. `rule_zip.py` derives them from the two files, so the zip
cannot drift from the report it ships with: inputs are the jrxml parameters the rule
actually reads as `_Name`, and the `data` output row is always emitted. It exits 1 on a
contract fault rather than writing a zip that disagrees with the layout - fix the rule or
the jrxml, never the zip.

**`RULE_REGISTRATION.txt` and `JRXML_CONTRACT.txt` are written for you** by the same pass —
they restate tables the tooling has already derived, so typing them by hand is both slow and
a way for them to drift from the zip. Each ends in a **NOTES block that is yours to fill and
that survives regeneration**; the generated half is mechanical only. Put the judgment there:
what an empty input means, which fields belong to which section, and above all **what is not
proven**. Fill them before the handoff — an unfilled `TODO` block shipping to a deployer is
worse than no file.

Hand the zip to the user. **Never import it yourself** - importing is a write.

## Report back

Pages first, then a short list of what needs the user's decision. Keep it brief — the
detail belongs in `HANDOFF.md`, not in the message.

Always say what was **not** verified. A local render proves layout; it proves nothing
about whether a path resolves in the target environment.

### Then say what it cost — every build, not on request

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/usage.py"
```

Three lines at the end of the handoff message: effective tokens, context per turn, and the
dollar figure for the model that actually ran. Nobody adopts a tool whose cost they cannot
see, and a report that quietly cost $28 is worse news arriving late than early.

**Report EFFECTIVE tokens, never the raw total.** The four kinds are not priced alike -
cache reads are a tenth of fresh input, output is five times it - so the raw number is
dominated by the cheapest thing in it and makes every long session look like a disaster.

**And read `context/turn` before drawing any conclusion.** Cache reads are charged on every
turn and scale with how much is already loaded, so a high figure is worth explaining rather
than leaving to stand.

**But do NOT explain it by recommending a fresh session unless the script says so.** High
context/turn has two causes and they call for opposite advice:

- **the build inherited a long conversation** — real, fixable, and a fresh session is the fix.
- **the build filled its own context** — the skill, `model-facts.md`, a precedent rule,
  rendered page images. Intrinsic to the work. A fresh session changes NOTHING.

`usage.py` now distinguishes these by measuring what was loaded at the build's first turn
against the session's own baseline, and prints whichever is true. **Report its wording; do
not add a gloss on top of it.** This paragraph used to say "recommend a fresh session"
outright — on 2026-09-09 that advice went into a handoff for a build that WAS the whole
session, starting from its first message, where it was simply false. If you want to say more
than the script does, name what actually filled the context: which references were read, how
many precedents, how many page images.
