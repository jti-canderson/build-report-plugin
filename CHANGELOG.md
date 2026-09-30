# Changelog

## 0.34.0 - 2026-09-30

**`/build-report` is now the browser builder.** The whole build happens on one local page
(http://127.0.0.1:8789/): the chat only says where the page is.

- **One page, start to finish.** Pick the project and template, choose fields, click
  **Build report**; progress, follow-up questions, the rendered pages and the downloads all
  appear there. The page opens on a clean form.
- **Field browsers.** Search Criteria and Result Columns open on the report's root record,
  read from the project's SDK and Data Dictionary: drill into related records with
  breadcrumbs, Quick Find, Data Dictionary details per field, calculated fields.
- **Launch inputs you can trust.** Each criterion becomes a launch input with the eSeries
  operator, required / hidden flags and a default. The rule's input block is generated
  (`verification/launch_inputs.groovy`) and a gate launches the rule blank, filled and in the
  alternate arrival formats; a date "equals" filters the whole day; a search report's real
  rows must carry exactly the report's fields. Off-root paths are refused, computed criteria
  are matched after the search. Names and pick-list defaults (codes, not Data Dictionary
  labels) are checked before the build starts.
- **Verified downloads.** The rule, `.jrxml` and `RULE-<Code>.zip` are offered only after the
  gates pass, and refused if a file changed afterwards.
- **Resumable.** Job state lives in `<report>/.jti-build/`; a reload resumes the build in
  progress. A new session does not reopen a finished build.
- **Ending the session from the page.** **Done — stop Claude** ends the worker; closing the
  tab ends it about 5 s later (`JTI_CLOSE_GRACE`); a reload is not mistaken for a close.
- **Works from an installed copy.** The command finds its plugin through
  `${CLAUDE_PLUGIN_ROOT}` (then the newest installed copy, then a checkout) and prints the
  version. A scaffolded report's `gen_jrxml.py` no longer hard-codes a checkout path to the
  templates. A builder left running by an older copy is replaced when idle.
- `/test-report` is kept as an alias of `/build-report`.

**Fixed during the release browser run:**

- **Wide Table builds.** The page offers it, but `wide_table.build()` took no arguments, so
  a Wide Table build stopped at the scaffold stage. It now takes `columns=` like the List;
  the sample layout is unchanged.
- **A submitted build clears the form draft.** The next `/build-report` opened pre-filled
  with the report just built.
- **A check-in already in flight from a closed tab no longer cancels the close** (the page
  sends a per-load id); before, that race left Claude waiting until the 180 s page timeout.

**Known limitation:** Grouped Summary and Statement still cannot be scaffolded (their
`build()` takes no arguments); a build that picks one composes its generator from
`jti_style` primitives, which takes longer.

**Removed:** the four-question chat interview. It is in 0.33.0 if you need it (see
INSTALL.md, "Rolling back"). The build know-how the interview carried is now
`skills/jasper-reports/references/build-procedure.md`.

**Rollout switches unchanged and still OFF by default** (`JTI_VERIFIER=legacy`,
`JTI_INTERACTION=confirm`, `JTI_LOOKUP=full`, `JTI_BUILD_PLAN=off`). The fast verifier passes
the same suite, but it has been measured on this machine only; targeted lookup and the build
plan have not been exercised on enough new-domain reports to be the default. The browser
build decides the SDK in code and asks on the page whatever `JTI_INTERACTION` says.

**Package:** `docs/` (perf records naming client report folders, raw timings, the
pre-release E2E record) stays in git and is left out of the zip.

## 0.33.0

Last release with the chat interview (`main` at `0818987`).
