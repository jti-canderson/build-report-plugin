# jti-reports

Build eSeries (Sustain / Symphony) Jasper reports from JTI house templates.

## Install

**Try it for one session** — no permanent change, good for a first look:

```
claude --plugin-dir /path/to/jti-reports-plugin
```

**Install it permanently** — Claude Code loads a local plugin through a marketplace
wrapper, so give it one. From the folder that will hold both:

```
mkdir -p jti-marketplace/plugins
mv jti-reports-plugin jti-marketplace/plugins/
```

Then create `jti-marketplace/.claude-plugin/marketplace.json`:

```json
{
  "name": "jti-marketplace",
  "owner": { "name": "Journal Technologies" },
  "plugins": [
    { "name": "jti-reports", "source": "./plugins/jti-reports-plugin" }
  ]
}
```

and in Claude Code:

```
/plugin marketplace add /path/to/jti-marketplace
/plugin install jti-reports@jti-marketplace
```

See [INSTALL.md](INSTALL.md) for the full walkthrough.

## Use

```
/build-report
```

Opens the report builder in your browser (http://127.0.0.1:8789/) and does the whole build
there. The chat only says where the page is.

1. **Pick** the project and a template (all six previews side by side). The project's field
   list (SDK, registered per project) and Data Dictionary are found for you.
2. **Choose the fields.** The Search Criteria and Result Columns browsers open on the report's
   root record: drill into related records (Case › Parties › Person) with breadcrumbs, use
   Quick Find, see each field's Data Dictionary details, and add calculated fields. Each
   criterion becomes a launch input with the eSeries operator, required / hidden flags and a
   default; the builder checks names and pick-list defaults before it lets you build.
3. **Build report.** Progress, any follow-up question, the rendered pages and the verified
   downloads (rule, `.jrxml`, `RULE-<Code>.zip`) all appear on the page. Downloads are
   refused if a file changed after the gates passed.
4. **Done — stop Claude** ends the session from the page. Closing the tab does the same after
   a few seconds; a reload does not, and resumes the build in progress.

Nothing is imported into eSeries: importing the zip is yours to do.

`/test-report` is the old name for the same command and still works.

## What's inside

| | |
|---|---|
| `commands/build-report.md` | the flow (the browser worker) |
| `scripts/serve_builder.py`, `scripts/jobs.py` | the builder page and its job coordinator |
| `skills/jasper-reports/references/build-procedure.md` | how a submitted job is built |
| `scripts/project.py` | project folders and per-project SDK/JAR tracking |
| `scripts/layout.py` | where each report-folder file lives: only what ships at the top, the rest in `verification/` |
| `scripts/scaffold.py` | generate `verification/gen_jrxml.py` + verification boilerplate from a `spec.json` |
| `scripts/finish.sh` | the pre-handoff gate: contract check → render → truncation check → rule zip |
| `scripts/sdk_fields.py` | walk an SDK jar's `extends` chain, report field vs. getter owner |
| `templates/` | six house templates, the render harness, `contract_check.py` |
| `templates/examples/` | a rendered PDF and labelled page image per template, **pre-built** — picking a template never waits on a render |
| `skills/` | jasper-reports, report-deployment, financials, data-dictionary, running-reports, eseries-navigation |

## Templates

| | Template | For |
|---|---|---|
| A | Record Summary | everything about one person or case, in sections |
| B | eSeries Screen | a print copy of an eSeries folder view - looks like the application |
| C | List | a straight list, one row per record |
| D | Grouped Summary | a list split into groups with subtotals |
| E | Statement | a document you send someone |
| F | Wide Table | landscape, up to nine columns |

`python3 templates/catalog.py` prints the menu; `catalog.py B` details one.

## Per-project state

Each project folder carries `.jti-project.json` — the client name, the target
environment, and the registered SDK/JAR with its date and hash. `/build-report` reads it
through `project.py sdk-decide`: with no usable SDK on file (none, file gone, unreadable) the
SDK is **required** - the build asks for the jar on the page with no Skip and does not go on
without it. One older than 180 days is flagged and can be replaced or kept.

The SDK matters because the local render harness runs against whatever JasperReports and
domain classes are on the machine. For a client that is not OKDAC that is an assumption,
and a wrong one is silent — the report compiles here and behaves differently there.

## Requirements

- Python 3
- A JasperReports Server install for local rendering (default
  `/Applications/jasperreports-server-9.0.0`; override with `JRS`)

## The builder page

`/build-report` starts `scripts/serve_builder.py --jobs` (127.0.0.1 only, port 8789) and is
the worker: it claims the job the page submits and reports each step through
`scripts/jobs.py`. Job state is on disk in `<report>/.jti-build/`, so a reload or a restart
resumes. One build at a time. A builder left running by an older copy of the plugin is
replaced when idle and kept (with a message) while it holds a job.

It cannot write outside the workspace root, and the gates are unchanged: the page skips the
questions, never the verification. `python3 scripts/serve_builder.py` without `--jobs`
(port 8787) is the older form that only writes a `spec.json`.

### Folder shortcuts in the picker

The picker leads with the folder **above** the workspace root (here
`~/JaspersoftWorkspace`, which holds `MyReports` alongside `Config Work`) because that is
the one people navigate from most, then Workspace, Home, Downloads, Desktop and Documents.

A teammate's layout will not match. Drop a `.jti-shortcuts` file in the workspace root to
put your own first:

```
Checks      = ~/JaspersoftWorkspace/MyReports/OKDAC Reports/Checks
~/Projects/reports          # no label: the folder name is used
# lines starting with # are ignored
```

Nothing is read until a shortcut is clicked — the list is built with `stat`, which macOS
does not gate, so opening the picker never triggers a file-access prompt.

## Rollout switches

Each optimisation has its OWN switch, so any one can be turned on without the others. **Every
default is the pre-optimisation behaviour, unchanged, and all four stay at their defaults in
0.34.0** (see CHANGELOG.md for why). Print the current settings and where
each came from:

```bash
python3 scripts/build_mode.py
```

| Switch | Default | Other value | What the other value does |
|---|---|---|---|
| `JTI_VERIFIER` | `legacy` | `fast` | `finish.sh` runs the same unchanged gate scripts in **one** JVM, fast-start JIT. Falls back to legacy, saying why, for any harness that is not an exact, unmodified, supported scaffold harness (`# JTI_SCAFFOLD_HARNESS_VERSION=1 sha256=...` on line 2 of `verification/run.sh`) |
| `JTI_INTERACTION` | `confirm` | `unattended` | SDK decided by `project.py sdk-decide` (requires one when missing or unreadable, asks when stale); brief-only columns recorded under `"derived"` instead of confirmed in chat |
| `JTI_LOOKUP` | `full` | `targeted` | `scripts/facts.py` and `scripts/precedents.py` instead of reading model-facts.md whole and exploring folders |
| `JTI_BUILD_PLAN` | `off` | `opt-in` | `scripts/build_plan.py run build-plan.json` (fast lane only). **Opt-in for this release**: the script exits 4 unless this is set |

Set them before starting Claude Code (`export JTI_VERIFIER=fast`), or in Claude Code's settings
(`"env": {"JTI_VERIFIER": "fast"}`).

**`JTI_REPORT_BUILD_MODE` is a deprecated alias**, kept for this release: `fast` sets
`JTI_VERIFIER=fast`, `JTI_INTERACTION=unattended` and `JTI_LOOKUP=targeted`, and **not** the
build plan; `build_mode.py` prints exactly that whenever it is set. A switch set explicitly
overrides the alias. A misspelt value of any switch warns and uses the default.

Tests: `python3 tests/run.py --core-only` is the self-contained suite (HOME pointed at an
empty temp dir); plain `python3 tests/run.py` adds the integration tier, which reads private
exports in `~/Downloads`. Totals are printed per tier. What was run for this release, and the
results: [VALIDATION.md](VALIDATION.md).

Only the fast verifier reads `JTI_JVM_OPTS` (default `-XX:TieredStopAtLevel=1`; `""` turns it
off). Measurements (in the git repository; `docs/` is left out of the release package):
`docs/perf/BASELINE.md` and `docs/perf/RESULTS.md`. Plan design:
`docs/perf/BUILD_PLAN.md`. Benchmark any report on a temp copy: `python3 scripts/bench.py <folder>
--mode legacy|fast --runs 3`.

### Rolling back

**Back to 0.33.0 (the chat interview):** install the 0.33.0 package, or check out `0818987`
in the plugin folder, then `claude plugin update jti-reports@<marketplace>` and restart Claude
Code. Stop any builder still running (`lsof -iTCP:8789 -sTCP:LISTEN`) so the old page is not
reused.

**Switches:**

**Turning a switch off is the rollback** — unset it (or set its default value) and that
component is back to the pre-optimisation behaviour, with no code change. To remove the code as
well, every step is one commit on `perf/report-build-speed`; revert latest first if more than
one (`git revert <commit>`):

| Commit | What | Switch that disables it | Reverting it removes |
|---|---|---|---|
| `67a2a74` | core / integration test tiers | — (tests only) | the tier split and `--core-only`; the "63 passed" claim was mixed |
| `53a46cd` | plan field provenance | `JTI_BUILD_PLAN=off` | provenance, cross-checks, safe traversals, fake-SDK plan tests (do not revert alone: the plan would again ship blank columns) |
| `10ecb61` | separate switches | — | `build_mode.py`; `JTI_REPORT_BUILD_MODE` goes back to driving everything, the plan loses its opt-in gate |
| `d4529a9` | harness marker | `JTI_VERIFIER=legacy` | the marker; fast mode goes back to a substring check (do not) |
| `e23d27f` | 5 build plan | `JTI_BUILD_PLAN=off` | `build_plan.py`, the plan design, the command's plan section |
| `ff1298b` | 4 lookups | `JTI_LOOKUP=full` | `facts.py`, `precedents.py`, the command's lookup text |
| `2cc6029` | 3 no pauses | `JTI_INTERACTION=confirm` | `sdk-decide`, the command's unattended section |
| `ea0483b` | 2 one-JVM verifier | `JTI_VERIFIER=legacy` | the one-JVM verifier and its dispatch in `finish.sh` |
| `2fec819` | 1 measurement | — (measures only) | the perf record, `bench.py`, `usage.py --perf` |
| `ebd9bed` | parser fix | — | the quoted-parameter parser fix (independent; keep it) |

With nothing set, every component is already off.
