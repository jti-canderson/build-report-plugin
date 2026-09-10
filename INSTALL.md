# Installing jti-reports

You were handed `jti-reports-plugin-<version>-<date>.zip`. Two ways to use it, depending
on whether you want to try it once or keep it.

## 0. Unzip it somewhere permanent

Don't run it from `~/Downloads` long-term — pick a folder you won't clean out, e.g.

```bash
mkdir -p ~/ClaudePlugins
unzip ~/Downloads/jti-reports-plugin-<version>-<date>.zip -d ~/ClaudePlugins
```

You should end up with `~/ClaudePlugins/jti-reports-plugin/` containing
`.claude-plugin/plugin.json`, `commands/`, `skills/`, `scripts/`, `templates/`.

## 1. Try it for one session (fastest)

No permanent install, nothing written outside the session. Good for a first look.

```bash
claude --plugin-dir ~/ClaudePlugins/jti-reports-plugin
```

Then, inside Claude Code:

```
/build-report
```

Close and reopen Claude Code the normal way and the plugin is gone — this flag loads it
for that one run only.

## 2. Install it permanently

Claude Code loads a local plugin through a **marketplace wrapper** — a single plugin
folder cannot be added on its own. Set that wrapper up once:

```bash
mkdir -p ~/ClaudePlugins/jti-marketplace/plugins
mv ~/ClaudePlugins/jti-reports-plugin ~/ClaudePlugins/jti-marketplace/plugins/
mkdir -p ~/ClaudePlugins/jti-marketplace/.claude-plugin
```

Create `~/ClaudePlugins/jti-marketplace/.claude-plugin/marketplace.json`:

```json
{
  "name": "jti-marketplace",
  "owner": { "name": "Journal Technologies" },
  "plugins": [
    { "name": "jti-reports", "source": "./plugins/jti-reports-plugin" }
  ]
}
```

Then, inside Claude Code:

```
/plugin marketplace add ~/ClaudePlugins/jti-marketplace
/plugin install jti-reports@jti-marketplace
```

This persists across sessions. To update later, drop a newer `jti-reports-plugin/` into
`~/ClaudePlugins/jti-marketplace/plugins/` (replacing the old one) and run
`/plugin marketplace update jti-marketplace` — no need to reinstall.

## 3. Use it

```
/build-report
```

Walks you through project, SDK/JAR, template, and what the report should show — four
short questions, skipping any you've already answered in the same message. Attaching a
folder-view export (`FORM-*.zip`) or a `.jrxml` answers most of them on its own. See
`README.md` for what each file in the plugin does.

## Requirements

- Python 3
- A JasperReports Server install for local rendering (default
  `/Applications/jasperreports-server-9.0.0` — override with the `JRS` environment
  variable if yours lives elsewhere)
- An SDK/JAR export from the target eSeries environment, for field verification
  (`/build-report` asks for one; you can skip it, at the cost of unverified field names)

## Troubleshooting

- **`/build-report` isn't recognized** — confirm the install landed:
  `/plugin` inside Claude Code lists installed plugins and marketplaces.
- **A script complains about a missing JVM** — set `JRS` to your JasperReports Server
  install, or skip local rendering; building the files does not require it, only the
  `render`/`finish.sh` verification step does.
- **Paths inside the plugin reference `$CLAUDE_PLUGIN_ROOT`** — that variable is set
  automatically once the plugin is loaded (either flow above); you never need to set it
  yourself.
