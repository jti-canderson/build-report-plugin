# Build procedure (used by `/build-report`)

How to turn a builder submission into a finished, verified report. `/build-report`
(`commands/build-report.md`) is the driver: it runs the browser page, claims each job, and
reports every stage through `jobs.py`. This file is the build know-how it points at.

**Read it in the browser flow's terms:**

- `$P` is the plugin folder `/build-report` resolved and printed as `PLUGIN <path>`. Use it
  literally; never assume a checkout or a home-directory path.
- **The user is on the page, not in the chat.** Wherever this file says to ask or confirm,
  ask with `jobs.py ask` (the page shows the question and waits), and only when a wrong guess
  would materially change the report. Everything else is a decision you record with
  `jobs.py log`.
- **The page delivers the files.** It shows the rendered pages and offers the verified
  downloads once `jobs.py complete` succeeds; there is no chat hand-off and no `SendUserFile`.
- **The gates run through `jobs.py run --gates`**, as `/build-report` says, not by calling
  `finish.sh` bare - that is how the page learns each result, and `complete` is refused
  without a recorded pass.

### SWITCHES — check them once, at the start

```bash
python3 "$P/scripts/build_mode.py"
```

It prints four independent settings and where each came from. Each changes ONE thing:

| Setting | Default | Other value | What the other value changes |
|---|---|---|---|
| `interaction` (`JTI_INTERACTION`) | `confirm` | `unattended` | the two pauses below |
| `lookup` (`JTI_LOOKUP`) | `full` | `targeted` | `facts.py` / `precedents.py` instead of reading whole |
| `verifier` (`JTI_VERIFIER`) | `legacy` | `fast` | `finish.sh` runs the gates in one JVM — nothing for you to do |
| `build_plan` (`JTI_BUILD_PLAN`) | `off` | `opt-in` | the one-command build plan (see "Build plan" below) |

Follow **only** the setting that is printed. `JTI_REPORT_BUILD_MODE=fast` is a deprecated alias
for `unattended` + `targeted` + `fast`; it does **not** turn on the build plan, and the script
says so. Everything below that says "unattended", "targeted" or "build plan" applies only when
that one setting says so; otherwise this file applies as written.

### INTERACTION on the page

The browser build always runs the way `unattended` describes, whatever `interaction` prints,
because the page is where the user answers: nothing waits on the chat.

1. **The SDK is decided in code.** `python3 "$P/scripts/project.py" sdk-decide "<project
   folder>"`. Exit **0** prints one `SDK ...` line - a current, readable SDK: log it and do not
   ask. Exit **11** prints `REQUIRED ...` (none on file, file gone, unreadable): the SDK is
   required - ask on the page with a `file` question that has no Skip (see `/build-report`),
   with the where-to-get-it directions, and do not build until `sdk-decide` exits 0. Exit
   **10** prints `ASK ...` (stale): ask the same way, but the user may keep the old one.
2. **Derived columns are recorded, not confirmed.** A brief-only spec (below) has its
   columns derived and written back into `spec.json`, with the derivation recorded under
   `"derived"` and logged to the page:

   ```json
   "derived": {"from": "intent",
               "columns": ["Case Number <- caseNumber", "Type <- caseType"],
               "assumptions": ["one row per case", "date range filters filingDate"],
               "sdk": "the sdk-decide line"
   ```

**Ask only when getting it wrong would materially change the report, or create a real
correctness risk** - and say which one it is. In practice that means:

- the brief fits two root entities or traversals that return **different rows**, and the SDK,
  `model-facts.md` and the corpus can't settle it (e.g. "payments": receipts vs pay-plan
  installments);
- a money figure whose definition is genuinely open (paid, balance, collected - see the
  financials skill);
- `sdk-decide` exits 11 (required) or 10 (stale).

Anything else - a column order, a heading, a width, a default sort - is a call you make and
record as an assumption. **Every gate, the three deliverables, looking at every rendered
page, and the honest *not verified* list are never skipped.**

### A spec with a brief but no columns — derive them, don't send it back

A spec can carry `"template"` and an `"intent"` brief with **`"sections": []`**. That is
someone who picked a template, wrote what the report should show in plain words, and left the
columns for you — exactly what the builder submits when nobody picks fields. It
is not an error and it is not a half-finished form to reject. `scaffold.py` refuses it on
purpose (it will not invent columns), and the refusal names this branch.

**Derive the sections from the brief, the same way you would from a spoken description.** Read `intent`, map it to real field paths using the SDK and `model-facts.md` and the
corpus — this is where the SDK earns its place, because there are no user-typed paths to
anchor on, so a blank column is likelier than usual and the handoff must say against which
environment (if any) the fields were checked. Then write the sections back into the spec so
the folder is self-describing and a re-run does not re-derive them:

```bash
python3 - "<the spec.json>" <<'EOF'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
s['sections'] = [
    {"key": "ROWS", "title": "Cases",
     "cols": [["Case Number", 20, "Left", "caseNumber"],
              ["Type", 20, "Left", "caseType"]]},   # the columns YOU derived from intent
]
json.dump(s, open(p, 'w'), indent=2)
EOF
```

Record the columns and your assumptions under `"derived"` in the spec and log them (see INTERACTION above). Then scaffold and build as normal. **The gates are unchanged**; deriving the
columns is the only added step.

### `look_like` — the spec says "match this picture"

A spec with `"template": ""` and `"look_like": "reference/<file>"` is someone who did not
want any of the six. **Read the picture before anything else** — it is sitting in the report
folder next to the spec — then log in ONE line which template you are starting from and
carry on. Do not ask for a template; they already answered, with a picture.

```
Read <the report folder>/reference/<file>
```

Everything in **Custom layouts and `look_like` pictures** below applies, unchanged: start
from the nearest template's generator (never a blank `.jrxml`), copy the STRUCTURE, keep
the JTI style unless `intent` asks for the picture's styling too, and say plainly what you
could not honour — checking `jti_style.py` first, because colours, banners and badges are
three lines each and are NOT limits. `scaffold.py` refuses this spec until a template is
named, which is deliberate: something has to look at the picture first.

Write the template you chose back into the spec, so the folder is self-describing and a
re-run does not re-derive it:

```bash
python3 - "<the spec.json>" <<'EOF'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
s['template'] = '<the module you chose>'
json.dump(s, open(p, 'w'), indent=2)
EOF
```

### Custom layouts and `look_like` pictures

A `look_like` picture (above) is the builder's Custom answer. The rules for building from it:

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

## Model routing — cheap by default, Opus only where it earns it

This command runs on **Sonnet** (frontmatter `model: sonnet`) — the driving is claiming jobs,
reporting stages and running Python, which needs nothing more. The expensive intelligence is pushed
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
read `$P/skills/jasper-reports/references/model-facts.md`. If the entity
and traversal are already written there, the domain is known — **skip discovery entirely**,
write the rule on Sonnet, and no Opus agent ever spawns. Opus is reached for only when the
model question is genuinely unanswered, and the answer is written back so it is free next
time. A report on a known shape (payments, past due, a folder-view export that hands you the
paths) should cost a Sonnet session and nothing more.

Do not launch a multi-agent fan-out for a question one `javap` or one corpus grep settles
inline. The fan-out is for a novel domain where a plausible-but-wrong path would survive a
single look — not for confirming what is already known.

## Then build

**Read `$P/skills/jasper-reports/references/model-facts.md` BEFORE any
model search.** It holds the answers that already cost real money to find — which entities
look right and are not, the real traversals, and the traps. Checking it is free; a fan-out
that re-derives what is already written there is the most expensive mistake in this
pipeline. Add to it whenever a model question takes more than a couple of minutes.

**`lookup: targeted`: ask it, don't read all of it.** The whole file is ~12k tokens that then sit in
the conversation for the rest of the build. Query it for what THIS report touches — the root
entity, the entities along each path, the field names, the template, and `--domain financial`
for any money:

```bash
python3 "$P/scripts/facts.py" --entity Case --entity PayPlan \
    --field balance --template eseries_summary --domain financial
```

It prints the matching sections **verbatim and in full**, then a one-line index of every other
section; `--section N` opens any of them. It reads the real file every time — nothing to go
stale. **"NO SECTION MATCHED" is a finding, not a pass**: that model question is open. Open the
full file whenever the targeted result is not enough to decide.

Then **one** precedent, not a tour of report folders:

```bash
python3 "$P/scripts/precedents.py" --root Case --template eseries_summary \
    --financial --params CaseId
```

It scores every report in the workspace on root entity, template, financial logic, parameters,
sections and environment, prefers ones verified on the current harness, and prints each
candidate's own *not verified* warnings. Open the rule it names; open a second only if the first
does not fit. "NO PRECEDENT" means a new shape: build from the template and model-facts rather
than forcing one.

**`lookup: full`:** read the whole file first, as above.

Follow the `jasper-reports` skill from step 1 of its sequence. Read it from the same plugin
(`$P/skills/jasper-reports/SKILL.md`), not from memory, so the skill and the scripts are the
same version.

Everything lands in `<project folder>/<Report Name>/`.

### Build plan (`build_plan: opt-in` only): write a plan, then ONE command does the mechanics

Only when `build_mode.py` prints `build_plan opt-in`. Otherwise skip this section entirely —
`build_plan.py` refuses to run (exit 4) unless `JTI_BUILD_PLAN=opt-in`. When it is on: after the
lookups, write the rule, write `build-plan.json` into the report folder
(`build_plan.py --example` shows every key; see `docs/perf/BUILD_PLAN.md`). **Every field a
section shows needs `provenance`** — `sdk` (with a traversal), or `computed` / `constant` with a
reason — plus an `outputs` entry and a value in every fixture row (or an entry in
`fixture.intentional_blanks`). Anything unaccounted for is exit 2, not a blank column. Then:

```bash
python3 "$P/scripts/build_plan.py" run "<report folder>/build-plan.json"
```

One call validates, decides the lane, checks the SDK, batch-resolves every traversal, scaffolds,
fills the fixtures, runs every gate in one JVM, fills the untouched NOTES seeds from the plan and
inventories the files. Its last line is `BUILD-RESULT {json}`. Exit **20** = expert lane: use the
steps below instead. Exit **3** = the rule or real fixture rows are missing. Exit **1** = a gate
failed; fix it and run the same command again. Then look at every page, as always.

**`build_plan: off`:** the steps below, as written.

### Scaffold the boilerplate — do not type it

Write a short `spec.json`, then generate the three files that carry no decisions:

```bash
python3 "$P/scripts/scaffold.py" --example    # the spec format
python3 "$P/scripts/scaffold.py" spec.json --out .
```

It writes `gen_jrxml.py`, `verification/fixture.py` and `verification/run.sh` — ~170 lines
expressing maybe 15 lines of actual choices. Writing them by hand is three or four turns and
several thousand of the slowest kind of token, to reach a file that was always going to be
the same shape.

**It will not overwrite an existing file without `--force`**, because a re-scaffold would
destroy exactly the two things worth keeping: the fixture rows and any hand-edit to the
generator.

### Three rules the executing gate enforces — write to them from the start

1. **Assign `_data`.** The output is read as `_data`; `data = rows` assigns an ordinary
   local, the engine produces nothing, and eSeries refuses the run.
2. **No `import com.sustain.*`.** The platform supplies those implicitly - 82 of the 95
   rules in this corpus carry none - and a fully-qualified import makes the rule impossible
   to compile off-platform, which disables the gate that runs it.
3. **Every value a String, every date coerced.** A `GString` is not a String and fails the
   gate. And whether eSeries hands a `java.util.Date` parameter over as a Date or a String
   is UNVERIFIED, so parse defensively (`toDate()`) rather than assuming - a rule that
   assumes Date dies with a GroovyCastException if it is a String.

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
python3 "$P/scripts/sdk_fields.py" Case caseType filingDate statuses ...
python3 "$P/scripts/refs.py" model-facts criteria-api
python3 "$SKILL/scripts/entity_field.py" county payPlan balance
```

All three cost the same for twenty names as for one — javap dumps the whole class, `refs`
reads files off disk, `entity_field` text-extracts the PDFs once. Asking one name per call
turns twenty questions into twenty turns, each re-sending the whole conversation first.

`sdk_fields.py` walks the whole `extends` chain and reports the field owner and the getter
owner separately, because they differ constantly — `Case` declares `caseType` while
`getCaseType()` lives on `CaseComponent`. **Read its closing note before concluding
anything from a `stripped` body**; it does not mean the getter is dead.

Then run the gates — **one command, from inside the report folder, through the job helper**:

```bash
python3 "$P/scripts/jobs.py" run --stage contract --gates -- "$P/scripts/finish.sh" \
    <rule>.groovy <report>.jrxml --code <Code> --name "<Human Name>"
```

It runs contract_check, `verification/run.sh render` and `rule_zip.py` in that order and
stops at the first failure. Do not run them separately: it is three turns instead of one,
and the order matters — contract_check is instant, the render costs ~20s, so a contract
fault has to stop the run before the JVM starts.

Then **look at every rendered page** in `verification/` (the page shows them to the user).

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

### Delivery and cost

The report folder the job names IS the delivery: the rule, the `.jrxml`, `RULE-<Code>.zip`
and the two filled `.txt` files end up there, and the page lists them. Say what was **not**
verified in the NOTES blocks and with `jobs.py log --level warn` - a local render proves
layout, not that a path resolves in the target environment. **Never import the zip** -
importing is a write, and the user does it.

`python3 "$P/scripts/usage.py"` prints what the build cost; put its lines in the job log with
`jobs.py log` so the figure is on the page.
