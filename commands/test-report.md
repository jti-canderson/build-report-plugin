---
description: TEST build of a report in the browser, from the local jti-reports-plugin checkout (unreleased branch)
argument-hint: [optional - nothing is needed; the builder page collects everything]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
model: sonnet
---

# /test-report

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

## 1. Locate the checkout, start the job server, say where it is

```bash
P="${PLUGIN:-$HOME/JaspersoftWorkspace/MyReports/jti-reports-plugin}"
[ -f "$P/scripts/jobs.py" ] || { echo "NO CHECKOUT at $P"; exit 1; }
echo "PLUGIN $P"
git -C "$P" log -1 --format='TEST BUILD from %D, commit %h' 2>/dev/null
python3 "$P/scripts/build_mode.py"
nohup python3 -u "$P/scripts/serve_builder.py" --jobs >/tmp/jti-test-builder.log 2>&1 &
sleep 2 && head -6 /tmp/jti-test-builder.log
```

If it prints `NO CHECKOUT`, stop and say so; do not search for it. If the server says the
port is in use by another server, stop and say that.

Then say exactly one line in the chat: *The builder is open at http://127.0.0.1:8789/. Fill it
in and click **Build report**. Progress, any questions, and the finished files all appear on
that page - click **Done — stop Claude** there when you are finished.* After that, nothing you do needs the chat.

Use `J="$P/scripts/jobs.py"` below. Run every command from inside the report folder the job
names (`cd "<folder>"`).

## 2. Wait for a job, then claim it

```bash
python3 "$J" wait
```

Exit **8** means the user is finished: they clicked **Done — stop Claude** on the page, or
closed the builder tab (the helper says which).
Stop at once - do not run `wait` again, do not tidy up - and end with exactly one line in the
chat: *Done - the builder session is closed. Run /test-report to build more.* (Nothing can
close the Claude window itself; ending the run is what the button asks for.)
Exit **7** means nothing was submitted yet: run it again. After **four** empty waits in a row
(about 36 minutes), stop and say in the chat that the builder is idle and `/test-report` can
be run again. Exit **0** prints the claimed job as JSON: `folder` (the report folder, the
canonical output; everything is written there and nowhere else), `spec` (what the user
submitted), and `destination` (the project folder they picked).

## 3. Build it, reporting each stage

The stages and their percentages are fixed in `jobs.py`. Report each one when it STARTS
(`jobs.py start <stage> "<what you are doing>"`) and when it is DONE (`jobs.py done <stage>
"<one-line result>"`). Keep status lines short and in plain English. Never report a stage as
done that is not.

**`jobs.py run` exits with its child's exit code.** Non-zero means that stage FAILED: never
report it done. Read the log, fix the cause and run it again, or `fail` the job (see "When a
gate fails").

**Every helper call may exit 6 (the user cancelled).** When it does, stop at once: do not
run another step, do not tidy up, and do not delete anything. Go back to step 2. **Exit 5**
means a question timed out and the job has ended; go back to step 2 as well.

For HOW to build, use the checkout's own references. Read them from `$P`, not from memory
and not through a skill loaded by name (that would load the installed version):

- `$P/commands/build-report.md`: use only **"A spec with a brief but no columns"**,
  **"`look_like`"**, **"Model routing"**, **"Then build"** and its subsections (scaffold, the
  three rules, one variant while iterating, batched model questions, the three files).
  **Ignore** its steps 0-4, the builder hand-off, "How to ask", and every instruction to ask
  in the chat or to send files in the chat. The page already answered the project, the
  template and the content, and the page is where the files go.
- `$P/skills/jasper-reports/SKILL.md`, and any reference it names, from the same checkout.
- Money: also `$P/skills/financials/SKILL.md`.

| Stage | What to do |
|---|---|
| `validated` | Read the spec. Check it has a template (or a `look_like` picture) and either columns or a brief. |
| `destination` | `python3 "$P/scripts/project.py" sdk-decide "<destination>"`. Exit 0: done, with the SDK line as the status. Exit 10: ask (below). |
| `requirements` | **Picked fields first.** `spec.paths` maps each column picked in the field browser to its SDK path (e.g. `Case.parties[].person.lastName`); `spec.criteria` lists launch inputs made from a field, with the path each filters and whether it is a `range` (From/To), `in` or `equals`, and for a pick-list its `lookup` list name (a launch input for it takes that list's values). Each criterion also carries the settings chosen in the builder, named as in the eSeries criterion editor: `operator` (`EQUALS`, `STARTS_WITH`, `ENDS_WITH`, `CONTAINS`, `IN`, `NOT_IN`, `BLANK`, `NOT_BLANK`, `GREATER_THAN`, or `RANGE` for a From/To date), `multi` (multi-select lookup; the value arrives as codes), `required` (register the input REQUIRED), `hidden` (a fixed filter: apply `default`, no launch input) and `default` (`@TODAY` / `@THIS_WEEK` for dates). `spec.columnOptions` gives each column `link`, `sort` (`ASCEND`/`DESCEND` - the rule's row order), `aggregate` (`GROUP_BY` groups rows, `SUM`/`COUNT`/... a total - pick a grouped template or say in the handoff it was not honoured), `format` (a date / money / number pattern, `YES_NO`, or `CUSTOM` with `customFormat` using `@value`) and `truncate` (characters). Apply them in the rule. **Launch inputs are generated, not written.** When `spec.criteria` is present, scaffold writes `verification/launch_inputs.groovy`: paste it UNCHANGED at the top of the rule and build the query from `def w = applyLaunchInputs(new Where())` (add the rule's own conditions to `w` after). It reads every input by its exact launch-form name, converts dates / lists / numbers from the text eSeries sends, applies each `default` when the input is left blank, and adds the attested Where call. Never rename an input, re-read one by hand, or add a second filter on the same field - `finish.sh` runs `verification/launch_inputs_check.groovy`, which launches the rule blank, filled and in the alternate arrival formats and fails the build if any input does not reach its filter. A pick-list `default` is a CODE (the Data Dictionary lists labels). Anything the template cannot show - a link in the PDF - is listed in the handoff as not honoured, never silently dropped. They came from the project's Data Dictionary (or its SDK), so use them as the traversals and filters; `[]` means one value per related record, so decide (and log) whether that is one row each or a joined list. **Nothing picked:** derive the columns from the brief (record them under `"derived"` in `spec.json`), and the launch inputs too, since a brief that says "filed in a date range" means a From/To pair on the filing date. Assume and log (`jobs.py log`) wherever a reasonable person would; ask on the page (section 4) only when two readings give materially different reports. Then the lookups (the `lookup` switch decides targeted or full) and check every field against the SDK. |
| `plan` | Write the rule (`<Name>_V1.groovy`). It is the judgment file, and every line of it is a decision. |
| `scaffold` | `python3 "$J" run --stage scaffold -- python3 "$P/scripts/scaffold.py" spec.json --out .`. If it says `kept … (exists)`, the folder holds an earlier unfinished build's scaffold (the page allows a rebuild only then); run it again with `--force`, which replaces only the scaffold's own `gen_jrxml.py`, `verification/fixture.py` and `verification/run.sh`. |
| `fixtures` | Give `verification/fixture.py` real, awkward rows. |
| gates | `python3 "$J" run --stage contract --gates -- "$P/scripts/finish.sh" <Name>_V1.groovy <Name>.jrxml --code <Name> --name "<Title>"`. **This one command reports contract, rule, render, truncation and package itself**; do not report those stages by hand. |
| `review` | Read EVERY page image in `verification/`. Done only when you have looked at each one. |
| `documentation` | Fill the NOTES blocks in `JRXML_CONTRACT.txt` and `RULE_REGISTRATION.txt`. |
| finish | `python3 "$J" complete` |

**The gates must run through `jobs.py run --gates`.** That is how the page learns each gate's
result, and `complete` is refused unless it recorded a pass. It is also refused if the rule,
`.jrxml` or zip changed after that pass, so re-run the gates after any edit. The build plan
(`build_plan.py`) is not used in `/test-report`: it runs the gates its own way.

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
risk, the same threshold as `build-report.md`'s unattended mode. A column order, a heading
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
  10. Offer a way out as an option:

  ```bash
  python3 "$J" ask --id sdk-required --type file --title "Field list needed" \
      --prompt "No current SDK for <project>. In eSeries: System Setup → Metadata → Entities → Download SDK. Upload the jar here, or skip - without it a wrong field name prints a blank column with no error." \
      --option "skip=Skip - build without field checks"
  ```

  With a file: `python3 "$P/scripts/project.py" sdk-register "<destination>" "<file>"`. With
  skip: `jobs.py log --level warn "No SDK: no field was verified against this environment"`.

## 5. Finish, and go back to waiting

After `complete` succeeds, the page shows the pages, the downloads, and where the report is
saved. **Never import anything; importing is a write, and the user does it.** Never delete,
move or overwrite a file the user already had. Then go back to step 2 and wait for the next
job, because the page's "Build another report" button relies on you still waiting. The
page's **Done** button is how that loop ends: the next `wait` exits 8 (step 2).
