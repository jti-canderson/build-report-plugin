---
description: Build an eSeries Jasper report in the browser - pick fields, preview the pages and download the verified files on one page
argument-hint: [optional - nothing is needed; the builder page collects everything]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
model: sonnet
---

# /build-report

`$ARGUMENTS`

A report build that happens **entirely in the browser**. The page collects the report, shows
progress, asks any follow-up question, shows the rendered pages, and offers the downloads.
You are the worker: claim the job the page submits, build it, and report every step through
`jobs.py`. The builder server coordinates.

**The user does not come back to this chat.** So:

- **Never ask a question here.** Every question goes through `jobs.py ask`, which puts it on
  the page and waits for the answer. Do not use a chat question tool, and never tell the user
  to reply in the chat.
- Anything the user needs to see (a warning, a finding, a decision you made) goes into the
  job with `jobs.py log --level warn` or into a stage status. Chat text is not seen.

## 1. Locate the plugin, start the job server, say where it is

```bash
P=""
for p in "$JTI_PLUGIN" "${CLAUDE_PLUGIN_ROOT}"; do
  [ -n "$p" ] && [ -f "$p/scripts/jobs.py" ] && P="$p" && break
done
if [ -z "$P" ]; then   # not loaded as a plugin command: the newest installed copy, then a checkout
  P=$(ls -d "$HOME"/.claude/plugins/cache/*/jti-reports/*/ 2>/dev/null | sed 's:/$::' \
      | awk -F/ '{print $NF"\t"$0}' | sort -t. -k1,1n -k2,2n -k3,3n | tail -1 | cut -f2)
  [ -f "$P/scripts/jobs.py" ] || P="$HOME/JaspersoftWorkspace/MyReports/jti-reports-plugin"
fi
[ -f "$P/scripts/jobs.py" ] || { echo "NO PLUGIN FOUND"; exit 1; }
echo "PLUGIN $P"
python3 -c "import json,sys; print('jti-reports', json.load(open(sys.argv[1]))['version'])" "$P/.claude-plugin/plugin.json"
git -C "$P" log -1 --format='  checkout on %D, commit %h' 2>/dev/null
python3 "$P/scripts/build_mode.py"
nohup python3 -u "$P/scripts/serve_builder.py" --jobs >/tmp/jti-builder-jobs.log 2>&1 &
sleep 2 && head -6 /tmp/jti-builder-jobs.log
```

Use the printed `PLUGIN` path **literally** as `$P` in every command below. If it prints
`NO PLUGIN FOUND`, stop and say so; **do not search the disk for it** (a `find` over `$HOME`
wanders into `~/Library` and raises a macOS privacy prompt). If the server says the port is
in use by another server, stop and say that. If it says a builder from another copy is
already running with a job in progress, say that in one line and stop.

Then say exactly one line in the chat: *The builder is open at http://127.0.0.1:8789/. Fill it
in and click **Build report**. Progress, any questions, and the finished files all appear on
that page - click **Done — stop Claude** there when you are finished.* After that, nothing you
do needs the chat.

Use `J="$P/scripts/jobs.py"` below. Run every command from inside the report folder the job
names (`cd "<folder>"`).

## 2. Wait for a job, then claim it

```bash
python3 "$J" wait
```

Exit **8** means the user is finished: they clicked **Done — stop Claude** on the page, or
closed the builder tab (the helper says which).
Stop at once - do not run `wait` again, do not tidy up - and end with exactly one line in the
chat: *Done - the builder session is closed. Run /build-report to build more.* (Nothing can
close the Claude window itself; ending the run is what the button asks for.)
Exit **7** means nothing was submitted yet: run it again. After **four** empty waits in a row
(about 36 minutes), stop and say in the chat that the builder is idle and `/build-report` can
be run again. Exit **0** prints the claimed job as JSON: `folder` (the report folder, the
canonical output; everything is written there and nowhere else), `spec` (what the user
submitted), and `destination` (the project folder they picked).

### A job with `inquiry`: a question about a finished report

**Pasted screenshots.** An `inquiry` or a `revision` can carry `images`: absolute paths to
screenshots the user pasted into the box (an eSeries screen, a page of the PDF with something
circled). **Open every one with the Read tool and look at it before you answer or change
anything** - "make it look like this" or "this column is wrong" usually means only the
picture says which. Never copy them into the report folder or the deliverables.

**Attached files.** The same request can carry `files`: absolute paths to files the user
attached or dropped in (a PDF of an existing report, a `FORM-*.zip` or `RULE-*.zip`, a
spreadsheet of expected figures, a `.jrxml` or `.groovy` from elsewhere, a log). The server
names each `file-<time>-<hex>-<original name>`, so the original name is the tail. Read every
one before you answer or change anything:
- PDF and text files (`.txt .csv .json .xml .jrxml .groovy .vm .md .log .sql ...`): the Read tool.
- `FORM-*.zip`: `python3 "<plugin>/skills/jasper-reports/scripts/formexport.py" <path>`.
  Any other zip: `unzip -l` first, then read the members you need from a scratch copy.
- `.xlsx` / `.docx` / `.pptx`: they are zips of XML. Extract the text with Python's `zipfile`
  in a scratch folder. If you cannot read one, say so in your answer rather than guessing.
Like the pictures, they are evidence. They are not deliverables, so never copy them into the
report folder.

When `wait` prints a job with an `inquiry` (`{n, text, images, files}`), the user clicked **Ask a question**
on a finished report. It is a question, not a change request: **change no file and run no
gate.** The job stays complete and its downloads stay valid. `earlier` lists the questions
already answered for this report, for context.

- Read what you need from the report folder (the rule, `verification/spec.json`,
  `verification/JRXML_CONTRACT.txt`, `verification/RULE_REGISTRATION.txt`, the rendered
  pages, the SDK) and answer in plain English, as briefly as the question allows. Say where
  a value comes from by field path when that is the question. If you are not sure, say so;
  never guess at what eSeries holds.
- Answer it with `python3 "$J" reply --job <id> --n <n> "<answer>"`. Do not use `ask`,
  `start`, `done` or `complete` for it - the job is not being built.
- If the honest answer is "that would need a change" (they asked whether it could show
  something it does not), say what the change would be and that **Request changes** on the
  page will make it. Do not make it yourself.
- Then go straight back to step 2 and `wait` again.

### A job with `revision`: changes to a report you already built

When the claimed job has a `revision` (`{n, text, images, files}`), the user has looked at the finished
report and typed what they want changed in the page's **Questions or changes?** box and clicked **Request changes**. It is
the SAME report in the SAME folder - not a new build:

- Do not re-ask the four questions, re-check the SDK or re-scaffold from scratch. Read
  `revision.text`, then change what it asks for: the spec (`verification/spec.json`), the
  rule, and the fixture rows to match. If a column changes, update the spec and re-run
  `scaffold.py verification/spec.json --out . --force` so the layout, launch inputs and
  launcher are regenerated, never hand-edited. `--force` also resets `verification/fixture.py`
  to TODO rows: give it real rows again before the gates. It regenerates
  `verification/gen_jrxml.py` from the template defaults too, so any override added to it by
  hand in an earlier round (a one-wide `HEADER_COLS`, a `markup="styled"` field) is GONE:
  diff it against the previous copy and reapply each one before running the gates. For a
  change that does not touch the columns (a heading, the launcher, the rule's logic), do not
  use `--force` at all: edit the spec and run scaffold without it.
- Report it like any build: `jobs.py start plan "Applying the requested changes"`, then the
  same gates row as below (`jobs.py run --stage contract --gates -- finish.sh …`). Fill the NOTES blocks
  again, adding a line for what changed in this round, then `complete`. The
  page shows the new files when it passes.
- **The preview must show the change.** The rendered pages come from the fixture rows, not
  from the rule, so a change to order, grouping or totals is invisible unless the rows show
  it: put the fixture rows in the order the rule now produces (newest first means the rows
  ARE newest first), and give a new column or total real values. Someone who asked for
  "newest first" and sees 10/14, 09/02, 12/01 will reasonably conclude it was ignored.
- Something that cannot be done, such as a chart or a click inside the PDF, is said on the
  page with `jobs.py ask --type choice` before you build, never silently dropped. An unclear
  request is asked about the same way, once. **An alternative you offer must be genuinely
  useful once built**: a summary of counts is its own small section or table with room for
  every value, not text squeezed into a fixed-width header box where it is cut to "+2 more".
- Log each change you made (`jobs.py log`), so the technical log shows what the round did.

## 3. Build it, reporting each stage

**The report folder's top holds only what ships**: the rule (`<Name>_V1.groovy`), the
`.jrxml`, `RULE-<Code>.zip` and `<Name>_Launcher.vm`. Everything else - `spec.json`,
`gen_jrxml.py`, `RULE_REGISTRATION.txt`, `JRXML_CONTRACT.txt`, `HANDOFF.md`, fixtures and
rendered pages - goes in `verification/` (`scripts/layout.py`). Never write a support file at
the top.

The stages and their percentages are fixed in `jobs.py`. Report each one when it STARTS
(`jobs.py start <stage> "<what you are doing>"`) and when it is DONE (`jobs.py done <stage>
"<one-line result>"`). Keep status lines short and in plain English. Never report a stage as
done that is not.

**`jobs.py run` exits with its child's exit code**, and on success it marks that stage done
itself (no separate `done` call). Non-zero means that stage FAILED: never
report it done. Read the log, fix the cause and run it again, or `fail` the job (see "When a
gate fails").

**Every helper call may exit 6 (the user cancelled).** When it does, stop at once: do not
run another step, do not tidy up, and do not delete anything. Go back to step 2. **Exit 5**
means a question timed out and the job has ended; go back to step 2 as well.

For HOW to build, read the references from `$P` (not from memory, and not through a skill
loaded by name, which could be a different installed version):

- `$P/skills/jasper-reports/references/build-procedure.md`: deriving columns from a brief,
  `look_like` pictures, model routing, and the build itself (scaffold, the three rules, one
  variant while iterating, batched model questions, the three files).
- `$P/skills/jasper-reports/SKILL.md`, and any reference it names.
- Money: also `$P/skills/financials/SKILL.md`.

| Stage | What to do |
|---|---|
| `validated` | Read the spec. Check it has a template (or a `look_like` picture) and either columns or a brief. |
| `destination` | `python3 "$P/scripts/project.py" sdk-decide "<destination>"`. Exit 0: done, with the SDK line as the status. Exit 11: the project has no usable SDK - **required**: ask for it with no way to skip (below) and do not go past this stage without one. Exit 10: the SDK is stale - ask, and the user may skip (below). |
| `requirements` | **Picked fields first.** `spec.paths` maps each column picked in the field browser to its SDK path (e.g. `Case.parties[].person.lastName`); `spec.criteria` lists launch inputs made from a field, with the path each filters and whether it is a `range` (From/To), `in` or `equals`, and for a pick-list its `lookup` list name (a launch input for it takes that list's values). Each criterion also carries the settings chosen in the builder, named as in the eSeries criterion editor: `operator` (`EQUALS`, `STARTS_WITH`, `ENDS_WITH`, `CONTAINS`, `IN`, `NOT_IN`, `BLANK`, `NOT_BLANK`, `GREATER_THAN`, or `RANGE` for a From/To date), `multi` (multi-select lookup; the value arrives as codes), `required` (register the input REQUIRED), `hidden` (a fixed filter: apply `default`, no launch input) and `default` (`@TODAY` / `@THIS_WEEK` for dates). `spec.columnOptions` gives each column `link`, `sort` (`ASCEND`/`DESCEND` - the rule's row order), `aggregate` (`GROUP_BY` groups rows, `SUM`/`COUNT`/... a total - pick a grouped template or say in the handoff it was not honoured), `format` (a date / money / number pattern, `YES_NO`, or `CUSTOM` with `customFormat` using `@value`) and `truncate` (characters). Apply them in the rule. **Launch inputs are generated, not written.** When `spec.criteria` is present, scaffold writes `verification/launch_inputs.groovy`: paste it UNCHANGED at the top of the rule and build the query from `def w = applyLaunchInputs(new Where())` (add the rule's own conditions to `w` after). It reads every input by its exact launch-form name, converts dates / lists / numbers from the text eSeries sends, applies each `default` when the input is left blank, and adds the attested Where call. Never rename an input, re-read one by hand, or add a second filter on the same field - `finish.sh` runs `verification/launch_inputs_check.groovy`, which launches the rule blank, filled and in the alternate arrival formats and fails the build if any input does not reach its filter. A pick-list `default` is a CODE (the Data Dictionary lists labels). Anything the template cannot show - a link in the PDF - is listed in the handoff as not honoured, never silently dropped. They came from the project's Data Dictionary (or its SDK), so use them as the traversals and filters; `[]` means one value per related record, so decide (and log) whether that is one row each or a joined list. **Nothing picked:** derive the columns from the brief (record them under `"derived"` in `verification/spec.json`), and the launch inputs too, since a brief that says "filed in a date range" means a From/To pair on the filing date. Assume and log (`jobs.py log`) wherever a reasonable person would; ask on the page (section 4) only when two readings give materially different reports. Then the lookups (the `lookup` switch decides targeted or full) and check every field against the SDK. |
| `scaffold` | `python3 "$J" run --stage scaffold -- python3 "$P/scripts/scaffold.py" verification/spec.json --out .`. If it says `kept … (exists)`, the folder holds an earlier unfinished build's scaffold (the page allows a rebuild only then); run it again with `--force`, which replaces only the scaffold's own `verification/gen_jrxml.py`, `verification/fixture.py` and `verification/run.sh`. Scaffold comes BEFORE the rule: it writes `verification/launch_inputs.groovy`, which the rule starts with. |
| `launcher` (no stage of its own) | `spec.launcher` = `{icon, text, param, style}`, from the builder's Launcher step: scaffold writes `<Name>_Launcher.vm` from it and the page offers it as a download. **Never write a launcher by hand.** If the brief asks for one ("velocity to trigger it", "a print button on the case screen") and `spec.launcher` is absent, add `"launcher": {"icon": "", "text": "Print <Title>", "param": "<the record-id input, e.g. caseId>", "style": "link"}` to `verification/spec.json` (`style`: `link`, or `blue` / `grey` / `red` for a button - eSeries `btn btn-primary` / `btn btn-default` / `btn btn-danger`) before scaffolding and log it. The rule must read `param` as the record id (scaffold adds it to `params` if missing). Icon classes: `templates/eseries_icons.json`. |
| `plan` | `jobs.py start plan`, write the rule (`<Name>_V1.groovy`), then `jobs.py done plan "<Name>_V1.groovy written"`. It is the judgment file, and every line of it is a decision. (The gates tick this stage themselves if you forget, since they run on the rule.) |
| `fixtures` | Give `verification/fixture.py` real, awkward rows. |
| gates | `python3 "$J" run --stage contract --gates -- "$P/scripts/finish.sh" <Name>_V1.groovy <Name>.jrxml --code <Name> --name "<Title>"`. **This one command reports contract, rule, render, truncation and package itself**; do not report those stages by hand. |
| `review` | Read EVERY page image in `verification/`. Done only when you have looked at each one. |
| `documentation` | Fill the NOTES blocks in `verification/JRXML_CONTRACT.txt` and `verification/RULE_REGISTRATION.txt`. |
| finish | `python3 "$J" complete` |

**The gates must run through `jobs.py run --gates`.** That is how the page learns each gate's
result, and `complete` is refused unless it recorded a pass. It is also refused if the rule,
`.jrxml` or zip changed after that pass, so re-run the gates after any edit. The build plan
(`build_plan.py`) is not used here: it runs the gates its own way.

### When a gate fails

The page already shows which gate failed. Read the log, fix the cause, and run the same gates
command again, at most **two** automatic fixes. Report each attempt with
`jobs.py log --level warn "Fix 1: <what you changed>"`. If it still fails, or the failure
needs a decision only the user can make:

```bash
python3 "$J" fail --stage <the failing stage> --message "<plain-English cause and what would fix it>" --attempts <n> [--retryable]
```

Use `--retryable` only when submitting the same spec again could plausibly succeed (a
transient environment problem), not when the spec needs to change. **Never call `complete`
after a failure**; it is refused anyway. Then go back to step 2.

## 4. Asking the user: through the page only

Ask only when a wrong guess would materially change the report or create a real correctness
risk, the same threshold as `build-procedure.md`'s INTERACTION section. A column order, a heading
or a width is your call: record it with `jobs.py log` and move on.

```bash
python3 "$J" ask --id <short-id> --title "<short title>" --prompt "<the question, with the context needed to answer it>" \
    --type choice|text|longtext|file [--option value=Label ...] [--allow-text] [--optional] [--timeout 3600]
```

A shell call is cut off after 10 minutes, but a question waits up to its `--timeout`. If the
call ends with no answer printed and no exit 5 or 6, **run exactly the same `ask` again**: it
resumes waiting on the question already open and does not ask twice.

It blocks until the page answers, then prints the answer as JSON (`value`, `text`, and for a
file, `file`: the uploaded file's path inside the job folder). One question at a time. Types:

- `choice`: one of the options; `--allow-text` also lets the user type their own answer.
- `text` or `longtext`: a short or longer free answer.
- `file`: **only when a file is genuinely required**, such as the SDK when `sdk-decide` exits
  11 or 10.

  **Exit 11 - no usable SDK in the project: REQUIRED.** No `--option`, no `--optional`, so
  the page offers no Skip. Say why it is needed and where to get it:

  ```bash
  python3 "$J" ask --id sdk-required --type file --title "SDK required" \
      --prompt "<project> has no SDK on file, and a report cannot be built without one: it is how every field is checked, and without it a wrong field name prints a blank column with no error. In eSeries: System Setup → Metadata → Entities → Download SDK. Upload the jar here."
  ```

  Register the upload (`python3 "$P/scripts/project.py" sdk-register "<destination>"
  "<file>"`), then run `sdk-decide` again. Still 11 (the upload was not a readable jar): say
  so and ask again with a new `--id`. **Never build without it**: not on a timeout, not
  because the brief is simple, not because a Data Dictionary is on file (the Data Dictionary
  feeds the field browser; the SDK is what checks the fields). A timeout (exit 5) ends the job.

  **Exit 10 - the SDK is stale.** Ask the same way, with a way out:

  ```bash
  python3 "$J" ask --id sdk-stale --type file --title "Newer SDK?" \
      --prompt "The SDK for <project> is <n> days old. In eSeries: System Setup → Metadata → Entities → Download SDK. Upload a newer jar, or keep using the one on file." \
      --option "keep=Keep the one on file"
  ```

  With a file: register it as above. With keep: `jobs.py log --level warn "SDK is <n> days
  old: fields were checked against it"`.

## 5. Finish, and go back to waiting

After `complete` succeeds, the page shows the pages, the downloads, and where the report is
saved. **Never import anything; importing is a write, and the user does it.** Never delete,
move or overwrite a file the user already had. Then go back to step 2 and wait for the next
job, because the page's "Build another report" button relies on you still waiting. The
page's **Done** button is how that loop ends: the next `wait` exits 8 (step 2).
