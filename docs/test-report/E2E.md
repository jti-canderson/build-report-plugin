# /test-report: supervised end-to-end exercise

Run on 28 September 2026 against a scratch workspace (one project, "Demo Project", no SDK on
file), on branch `perf/report-build-speed`. Every setting was at its default.

**Who did what.** The *user* side was the in-app browser: the form was filled in, **Build
report** clicked and the question answered on the page. The *worker* was the Claude session
that built this branch, following `commands/test-report.md` step by step with its commands as
written. It was **not** a fresh `/test-report` invocation in a new session, which is the next
test to run. The report is the suite's small fixture report: its rule is
`tests/fixtures/good_rule.groovy` with the title changed, and its columns were derived from a
brief.

## Browser-visible stage sequence (the successful run, "Cases By Type")

Straight from the job's event log (`.jti-build/job.json`), which is exactly what the page showed:

| # | Event | Stage | % | Status shown |
|---|---|---|---|---|
| 1 | submitted | submitted | 0 | Waiting for Claude to pick this up |
| 2 | claimed | submitted | 0 | Claude has picked this up |
| 3 | done | validated | 5 | List template, brief only - columns will be derived from it |
| 4 | start | destination | 5 | Checking the destination and SDK |
| 5 | **question** | destination | 5 | Question: Field list needed (answered on the page: *Skip*) |
| 6 | answered | destination | 5 | Answer received - continuing |
| 7 | log (warn) | destination | 5 | No SDK: no field was verified against this environment |
| 8 | done | destination | 12 | No SDK on file - skipped at your request; fields are unverified |
| 9-10 | start / done | requirements | 22 | 2 columns derived from the brief (recorded in spec.json) |
| 11-12 | start / done | plan | 35 | Rule written: Cases_By_Type_Test_V1.groovy |
| 13-14 | start / done | scaffold | 45 | gen_jrxml.py, fixture.py and run.sh generated |
| 15-16 | start / done | fixtures | 55 | 3 rows: a juvenile case type, an apostrophe |
| 17-20 | gate events | contract | 62 | Contract check passed |
| 21-22 | gate events | rule | 72 | Rule execution passed |
| 23-24 | gate events | render | 84 | Rendered |
| 25-26 | gate events | truncation | 90 | Truncation check passed |
| 27-29 | gate events | package | 93 | Rule package written; Every gate passed |
| 30 | done | review | 96 | Looked at both pages |
| 31-32 | start / done | documentation | 98 | NOTES filled; fields marked unverified (no SDK) |
| 33-34 | done / complete | complete | 100 | Report built and verified; 9 files ready |

The gate stages (events 17-29) came from `finish.sh`'s structured `JTI-GATE` lines via
`jobs.py run --gates`; nothing was reported by hand for them. The percentages never went
down, and each one changed only when a stage finished.

## Final artifacts

In `Demo Project/Cases_By_Type_Test/`, the report folder chosen in the form (the canonical
output; nothing was copied elsewhere):

`Cases_By_Type_Test_V1.groovy`, `Cases_By_Type_Test.jrxml`, `RULE-Cases_By_Type_Test.zip`,
`RULE_REGISTRATION.txt`, `JRXML_CONTRACT.txt`, `verification/full_sample.pdf`,
`verification/none_sample.pdf`, and the two page images. "Download a copy" returned
`Cases_By_Type_Test-package.zip` (`Content-Disposition: attachment`) holding the seven
deliverables and no page images.

## Chat interaction

**None needed after the start.** The command printed one line (where the builder is), and
every other step went through the page. The one question (no SDK) was asked and answered in
the browser. The user never had to return to the chat.

## Also exercised

- **Failure** (`Broken_Contract_2`, a rule that never assigns `_data`): the page showed
  *Failed at: Contract check*, the reason, the log excerpt, "Automatic retry: no", the files
  the build created, and no download.
- **Cancel** (`Cancel_Demo`, cancelled while a child process was running): the child was
  stopped and the helper exited 6 at once. The page showed *Cancelled*, "Nothing was
  deleted", and the one file created.
- **Refresh and restart**: the page was reloaded and the server restarted several times
  mid-build; each time the page came back to the same job and state.

## Defects this exercise found (all fixed before the phase 5 commit)

1. `complete` accepted a job whose NOTES blocks were still the untouched TODO seed. The worker
   (this session) had marked documentation done after a failed import. `complete` now refuses
   while a seed is unfilled.
2. A remembered job from an earlier server run left the page stuck on "Connecting…". It is
   now checked on load and forgotten if the server does not know it.
3. A spec posted without `meta`/`tiles` stored `null`, and `gen_jrxml.py` died on
   `META = null`. The job API now normalises the lists (the form always sent them).
4. The worker marked `scaffold` done after `jobs.py run` exited non-zero. The command now says
   a non-zero `run` is a failed stage.
5. A rebuild in the same folder kept the earlier build's scaffold (scaffold never overwrites).
   The command now says to use `--force`, which only replaces the scaffold's own three files.
6. The running line showed the completed label ("Rendered") while a stage ran. There are now
   present-tense labels ("Rendering the pages").
7. A failure read "Failed at: Contract check passed". Failures now use neutral stage names.
8. Every job in one folder shared a log file, so a rebuild's failure excerpt showed the
   previous build's lines. There is now one log per job.

9. (Found by the final `--core-only` suite run, not the browser run.) `jobs.py run` did not
   tell the gates which plugin to use, so the legacy `run.sh` searched for templates: up
   from the report folder, then in `~/.claude/plugins/cache`. Outside the workspace that
   meant the INSTALLED 0.32.0 templates, silently. `jobs.py run` now passes its own checkout
   as `JTI_PLUGIN`. In the real `/test-report` case (reports under the workspace) the walk up
   already found the checkout.

## Screenshots

`screens/1-form.png` (the Build report button and the "Claude is ready" indicator),
`2-running.png`, `3-question.png`, `4-complete.png`, `5-failed.png`, `6-cancelled.png`.
Captured with headless Chrome using a throwaway profile, from the job's own URL (`#job=…&t=…`).
