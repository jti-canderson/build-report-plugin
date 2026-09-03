---
description: Build an eSeries Jasper report from a JTI house template
argument-hint: [anything you already know - project, template letter, what the report should do, or a folder-view zip]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Skill, AskUserQuestion, Task
model: sonnet
---

# /build-report

Walk the user to a finished report. **Four questions, in this order.**

`$ARGUMENTS`

## Before asking anything

Read `$ARGUMENTS` and any attached file, and answer from it whatever you can.
**Never ask a question the user has already answered.** A message like
"OKDAC, template C, payments by agency for a date range" answers three of the four —
ask only the one that is left.

A `FORM-*.zip` or `FORM=*.xml` attachment answers question 4 on its own, and usually
question 3 as well (its panels tell you the shape). Parse it, do not ask about it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jasper-reports/scripts/formexport.py" <the zip>
```

## How to ask

**ONE question per message. Then STOP and wait for the answer.** Do not run ahead to the
next step in the same turn, and never put two questions in one message - it reads as one
question and the first gets answered while the second is silently dropped.

**Anything with a fixed set of answers uses `AskUserQuestion`, so the user clicks instead
of typing.** That means question 1 (project) and question 3 (template) ALWAYS. Only
question 4 is free text.

Short. Direct. One line. No preamble, no restating the question back, no explaining why
you are asking.

Good: `Which project?`
Bad: `Before we get started, I'd like to understand a bit more about which client this
report is intended for, since that affects where the files will live.`

Do not attach the example PDFs. Five files at once buries the question. Show one page
image only if the user asks to see a template.

---

## 1. Which project?

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" list
```

`AskUserQuestion`: the existing projects as options, plus **New project**. Wait for the
click. Then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" resolve "<name>" --create
```

Everything after this lives in that folder.

## 2. SDK / JAR

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" sdk-status "<project folder>"
```

The command always exits 0 - the first word is the status.

- **NONE / MISSING** → ask for it, **and say where to get it** — most people asked for a
  "JAR/SDK" have no idea the admin hands them one:

  > Send me the JAR/SDK for `<project>`, or say skip.
  > In eSeries: **System Setup → Metadata → Entities**, then **Download SDK** at the top right.

- **OK** → `AskUserQuestion`: *SDK on file: `<filename>` (registered `<date>`).* Options:
  **Still current** / **I'll send a newer one**.
- **STALE** → same, but lead with the age: *`<n>` days old.*

Give the same directions again whenever they pick **I'll send a newer one** — knowing the
path once does not mean remembering it a month later.

**Then stop.** Do not show the template menu until this is answered.

To save one the user provides:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/project.py" sdk-register "<project folder>" "<file>"
```

Do not block on this. If they say skip, note it and carry on — but say plainly in the
handoff that local verification ran against this machine's JasperReports, not the
client's.

## 3. Which template?

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/templates/catalog.py"
```

**Ask with `AskUserQuestion`** so the letters are clickable - one option per template,
labelled `A - Record Summary` and so on, with the one-line description underneath. Do not
print the text menu and do not attach the PDFs; the catalog output is for you, not them.

**Examples are already rendered** — if the user asks to see one, read the PNG from
`${CLAUDE_PLUGIN_ROOT}/templates/examples/<NAME>.png` and show it. Never regenerate a
sample to answer this question; it is slow and nothing about it is per-project.

| | Template | Example file |
|---|---|---|
| A | Record Summary | `JTI_Record_Summary` |
| B | List | `JTI_Tabular_List` |
| C | Grouped Summary | `JTI_Grouped_Summary` |
| D | Statement | `JTI_Statement` |
| E | Wide Table (landscape) | `JTI_Wide_Table` |

If a folder-view export was supplied, name the letter its shape implies and ask only for
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

Everything lands in `<project folder>/<Report Name>/`. The template library is at
`${CLAUDE_PLUGIN_ROOT}/templates` — import a generator rather than writing a `.jrxml` by
hand:

```python
import sys, pathlib
TPL = pathlib.Path("${CLAUDE_PLUGIN_ROOT}/templates")
sys.path.insert(0, str(TPL)); sys.path.insert(0, str(TPL / "templates"))
import tabular_list as T          # or record_summary, grouped_summary, statement, wide_table
```

`verification/run.sh` is COPIED from
`skills/jasper-reports/assets/run_template.sh` and its PER-REPORT block filled in - do not
write one from scratch.

Before reporting back, all three of these must pass:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/templates/contract_check.py" <rule>.groovy <report>.jrxml
./verification/run.sh render
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rule_zip.py" <rule>.groovy <report>.jrxml --code <Code> --name "<Human Name>"
```

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

Hand the zip to the user. **Never import it yourself** - importing is a write.

## Report back

Pages first, then a short list of what needs the user's decision. Keep it brief — the
detail belongs in `HANDOFF.md`, not in the message.

Always say what was **not** verified. A local render proves layout; it proves nothing
about whether a path resolves in the target environment.
