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
