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

Four short questions — project, SDK/JAR, template, what it should show. Answer any of
them up front and that question is skipped:

```
/build-report OKDAC, template D, payments by agency for a date range
```

Attach a folder-view export (`FORM-*.zip`) and the last question answers itself — its
panels, paths and column headings become the report.

## What's inside

| | |
|---|---|
| `commands/build-report.md` | the flow |
| `scripts/project.py` | project folders and per-project SDK/JAR tracking |
| `scripts/scaffold.py` | generate `gen_jrxml.py` + verification boilerplate from a `spec.json` |
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
to decide whether to ask for an SDK, and flags one older than 180 days.

The SDK matters because the local render harness runs against whatever JasperReports and
domain classes are on the machine. For a client that is not OKDAC that is an assumption,
and a wrong one is silent — the report compiles here and behaves differently there.

## Requirements

- Python 3
- A JasperReports Server install for local rendering (default
  `/Applications/jasperreports-server-9.0.0`; override with `JRS`)

## Building by form instead of by question

```bash
python3 scripts/serve_builder.py
```

Opens a local page (127.0.0.1 only) listing your real projects and all six templates with
their previews side by side. Fill it in, hit **Write spec.json**, and it prints the one
command to run. `/build-report` reads the spec and skips the questions.

The form exists because `AskUserQuestion` caps at four options, and that cap is what made
the template letters misleading, split a five-project list across two prompts, and forced a
two-step template menu. A form has no cap.

It writes a file and nothing else — it does not invoke Claude, and it cannot write outside
the workspace root. The gates are unchanged: a spec skips the questions, never the
verification.

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

## Build mode: legacy (default) or fast

One environment variable selects the build path. **Legacy is the default**, and it is the
pre-optimisation behaviour, unchanged.

```bash
export JTI_REPORT_BUILD_MODE=fast     # before starting Claude Code
```

Or put it in Claude Code's settings (`"env": {"JTI_REPORT_BUILD_MODE": "fast"}`) so every session
gets it.

| | legacy | fast |
|---|---|---|
| Gates | two JVMs (rule, render) | the same unchanged gate scripts in **one** JVM, fast-start JIT |
| SDK question | asked every build | asked only when missing, stale or unreadable (`project.py sdk-decide`) |
| Brief-only columns | confirmed in chat | recorded in `spec.json` → `"derived"` and in the handoff |
| model-facts.md | read whole | queried: `scripts/facts.py` |
| Precedent | explore folders | `scripts/precedents.py` |
| Mechanics | step by step | `scripts/build_plan.py run build-plan.json` (fast lane only) |

**Force legacy at any time:** `export JTI_REPORT_BUILD_MODE=legacy`, or unset it. Only fast mode
reads `JTI_JVM_OPTS` (default `-XX:TieredStopAtLevel=1`; set it to `""` to turn the flag off).

Fast mode falls back to the legacy gates, and says so, for any harness it does not understand.
Measurements: `docs/perf/BASELINE.md` and `docs/perf/RESULTS.md`. Plan design:
`docs/perf/BUILD_PLAN.md`. Benchmark any report on a temp copy: `python3 scripts/bench.py <folder>
--mode legacy|fast --runs 3`.

### Rolling back

Every phase is one commit on `perf/report-build-speed`; each can be reverted on its own
(`git revert <commit>`), latest first if more than one:

| Commit | Phase | Reverting it removes |
|---|---|---|
| `e23d27f` | 5 | `build_plan.py`, the plan design, the command's plan pointer |
| `ff1298b` | 4 | `facts.py`, `precedents.py`, the command's lookup text |
| `2cc6029` | 3 | `sdk-decide`, the command's FAST MODE section |
| `ea0483b` | 2 | the one-JVM verifier and the mode switch in `finish.sh` |
| `2fec819` | 1 | the perf record, `bench.py`, `usage.py --perf` |
| `ebd9bed` | — | the quoted-parameter parser fix (independent; keep it) |

No revert is needed to go back to legacy behaviour: leaving `JTI_REPORT_BUILD_MODE` unset already
does that.
