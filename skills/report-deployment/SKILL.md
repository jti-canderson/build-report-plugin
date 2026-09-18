---
name: report-deployment
description: >-
  Put an eSeries (Sustain / Symphony) Jasper report into an environment: create or edit the
  Groovy business rule, declare its input and output parameters, register the report in
  Reports Admin, attach or replace the .jrxml, and iterate on the result. Use this when the
  work is getting a report INTO eSeries or fixing a deployed one: "deploy this report",
  "register it in Reports Admin", "Import or Replace?", "the report runs but the page is
  blank", "it says Report with code null cannot be found", "add a parameter to the rule",
  "promote this report to master", or a screenshot of the rule form or Reports Admin. Also
  use it to produce an importable RULE export zip from a .groovy so the user can load a rule
  in one action instead of retyping every parameter row. Building the report itself — the
  Groovy logic, the .jrxml layout, the contract between them — is the `jasper-reports` skill;
  this one starts once those files exist. Reach for it before touching either admin screen,
  because the expensive mistakes here are silent: a missing output parameter renders a blank
  page while everything reports success, and Import creates a duplicate report where Replace
  would have updated the real one.
---

# Deploying a report into eSeries

This skill covers the two admin screens a report passes through, and nothing about writing
the report. For the rule logic, the `.jrxml`, and the contract between them, use
`jasper-reports`.

## The order, and why it is fixed

1. **The rule first.** Reports Admin cannot reference a rule as its Data Source Generator
   until the rule exists.
2. **Then the report registration** — attach the `.jrxml`, point it at the rule, set the
   parameters.
3. **Then run it** against a case you can also open on screen, and compare.

Rules and reports **do not sync between environments**. Doing this on QA does nothing for
master, conversion, or a district. Every id you see belongs to the environment you are on.

## The two silent failures

Learn these before you touch anything. Both look like success.

**A missing output parameter.** The rule needs an output row `data` / `REQUIRED` /
`java.util.List`. Without it the rule compiles, saves, and runs clean — and the report
renders nothing. It looks exactly like a bad field path. Check it first when a page comes
back empty.

**Import instead of Replace.** In Reports Admin, **Import creates a new report**. Using it to
fix an existing one leaves a duplicate behind, and the one you are looking at is not
necessarily the one being run. Replace updates in place. Confirm the form posts to
`/onReplace` before submitting.

## Everything else

`references/deploy.md` has the detail:

- finding both screens, and the URL patterns
- every field on the rule form, and what each value means
- getting Groovy into the CodeMirror editor (naive value-setting is lost)
- input and output parameter tables, and the mechanics of adding rows
- the registration block to hand over with every report
- shipping a rule as an importable export instead of typing it
- the iteration loop, and the handover message template

## Shipping a rule as a file

`scripts/rule_import.py` writes an importable `RULE` export from a `.groovy` plus a parameter
spec. That saves the user pasting Groovy into CodeMirror and retyping every parameter row,
which is where preset-value and REQUIRED/OPTIONAL mistakes come from.

```bash
SK=report-deployment
K=$(for p in . .. ../.. ../../..; do for b in System/Skills .claude/skills; do
      [ -d "$p/$b/$SK" ] && { echo "$p/$b/$SK"; exit; }; done; done
    [ -d "$HOME/.claude/skills/$SK" ] && echo "$HOME/.claude/skills/$SK")
S=$K/scripts
python3 "$S/rule_import.py" --groovy My_Report_V1.groovy --code My_Report \
    --name "My Report" --input caseId:long --output data:java.util.List:REQUIRED
python3 "$S/formexport.py" RULE-My_Report.zip        # read it back before handing it over
```

For a non-lookup input that must be REQUIRED, keep the empty lookup-list segment:
`--input caseId:long::REQUIRED`. Without that final segment the writer intentionally emits
an OPTIONAL input; always read the generated zip back before handing it over.

`--selftest <a real export>` regenerates that export from its own parts and diffs it. It
reproduces a real platform export byte for byte, which is what establishes the writer is
correct.

Regenerate the zip whenever the rule or its parameters change. A stale zip is worse than
none: it looks deployable and carries the old script. Its parameter rows must match
`RULE_REGISTRATION.txt` — same contract, two forms, and if they disagree the report deploys
differently depending on which one the next person opens.

**The import screen itself has never been observed.** Do not infer where it is, or what it
does when the target already has that Code. Reports Admin's own Import creates rather than
updates, so assume this may too until someone proves otherwise.

## Hard rules

**Never press a commit control. Stage, then hand it over.** Update, Save, Compile & Save,
Save As, Submit, Replace, Import, Delete — any record, any environment, QA included. Fill the
fields, verify on screen, say exactly which record and which values are staged, and let the
user press the button.

Approval of the *task* is not approval of the *write*. "Go ahead and update both", "you can
update them in eSeries", and a repeated instruction are not consent to commit. Ask for that
specific commit, every time, and wait.

Importing is a write. Generate the zip, say what is in it, hand it over.

Everything runs in the user's session, so every change carries their name.

**Say which environment you are on**, in every sentence that names an id. "Rule 10442 in QA",
never "rule 10442".

**Say what you did not verify.** A local render proves layout against stub data. Real data,
real traversals and real pagination are unproven until eSeries runs it.

## Iterating on a deployed report

To see a template change, **reload the report output tab**. Do not re-navigate to the output
URL: parameters travel in the POST body, so a GET loses them and returns *"Report with code
null cannot be found."*

## Related skills

- `jasper-reports` — building the rule, the `.jrxml`, and the contract between them
- `business-rules` — the Business Rules editor in general, beyond report rules
- `eseries-navigation` — finding your way around the admin
