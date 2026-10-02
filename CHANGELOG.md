# Changelog

## 0.35.0 - 2026-10-01

**Ask a question or request changes after a build, with pasted screenshots.** When a report
finishes, the page shows a *Questions or changes?* box under the results.

- **Request changes** sends the job back to the build worker as a new round (up to 20,000
  characters). The page shows *Making your changes (round n)*, and the finished round replaces
  the downloads. The setup stages stay ticked, so the checklist does not start again.
- **Ask a question** gets an answer in a thread on the page and changes no files. The page
  polls until the answer arrives.
- **Paste a screenshot** (Cmd+V) into either box. Up to 6 pictures, 10 MB each, PNG, JPEG,
  GIF or WebP, checked by their first bytes. They are saved under `.jti-build/attachments/`
  (owner-only) and handed to the worker as file paths. The worker is told to open each one.
- The build instructions now cover revisions: re-apply hand overrides instead of running
  `scaffold.py --force` over them; make the preview show the change; give an alternative
  its own section rather than squeezing it into a header.

**Launcher look.** The Velocity launcher can be a text link, or a **Blue**, **Grey** or **Red**
button. The buttons only use eSeries' own classes: `btn btn-primary`, `btn btn-default`,
`btn btn-danger`. The plugin adds no styling of its own. The launcher is now written by
`scripts/launcher.py` as `<Name>_Launcher.vm`.

**Report folders are easier to navigate.** The top of a report folder now holds only what
gets deployed: the `.jrxml`, the Groovy rule, the `RULE-*.zip` and the launcher `.vm`. The
spec, `gen_jrxml.py`, `HANDOFF.md`, `JRXML_CONTRACT.txt`, `RULE_REGISTRATION.txt`, fixtures
and rendered samples go in `verification/`. `scripts/layout.py` is the single source for
where each file lives. It reads either place, so older reports keep working.
`scaffold.py` and `finish.sh` move an old flat folder's files on the next rebuild. An
unmodified `run.sh` and `gen_jrxml.py` are repointed; hand-edited ones are left alone.
Run it by hand with `python3 scripts/layout.py migrate <folder>`.

**Closing the tab stops the worker after a server restart.** The session token is now kept
in the server's pointer file. Before, a restarted server made a new one, and the page's
close signal was refused with a 403, so the Claude listener kept waiting.

- Tests: the suite uses its own pointer folder (`JTI_POINTER_DIR`), so it can never reach
  a builder the user has running. New checks cover the launcher classes, the folder layout and
  migration, questions, revisions, screenshot upload limits and types, and the token
  surviving a restart.
- The form gate knows `linkFormPathIndex` (a linked form's path index). A platform export
  with one was reported as a fault, *XStream and JSON disagree*, though both halves agreed.
- `model-facts.md`: findings from the 1 October builds (fixture newline escaping,
  `Party.person` has no getter, fixture keys going stale when header columns change, a vanished
  SDK file, a long-running builder serving old code).

## 0.34.1 - 2026-10-01

**The SDK is required when a project has none.** A build for a project with no usable SDK
on file (none registered, the recorded file gone, or a file that cannot be read) now asks
for the jar on the page with no Skip, and does not go past the *Destination and SDK* stage
without it. The server refuses a skip on that question. Before, the page offered
"Skip - build without field checks", and a build could ship with no field verified against
the client's environment.

- `project.py sdk-decide` exits **11** (`REQUIRED ...`) for a missing or unreadable SDK.
  A stale but readable SDK still exits 10: the page asks, and **Keep the one on file** goes on.
- The builder says so as soon as such a project is picked: *No SDK on file for this project*,
  with where to get one.
- Tests: the old "asks (exit 10)" check is split into required (none, gone, unreadable,
  stale-and-unreadable) and stale; two more check the command's required question has no
  way out and the page shows the notice.

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
