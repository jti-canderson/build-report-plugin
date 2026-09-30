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

This persists across sessions.

### Updating

Claude Code runs a **copy** of the plugin, pinned to its version
(`~/.claude/plugins/cache/<marketplace>/jti-reports/<version>/`), so replacing the folder is
not enough on its own:

1. Replace `~/ClaudePlugins/jti-marketplace/plugins/jti-reports-plugin/` with the new one
   (unzip the new package there).
2. Refresh and update:

   ```bash
   claude plugin marketplace update jti-marketplace
   claude plugin update jti-reports@jti-marketplace
   ```

3. **Restart Claude Code.** A running session keeps the version it started with.

A builder page left open from the old version is replaced by the next `/build-report` when
it is idle. If it is still holding a build, `/build-report` says so; finish it or click
**Done — stop Claude** first.

### Rolling back

Put the previous package's `jti-reports-plugin/` back in place, run the same two commands,
and restart Claude Code. 0.33.0 is the last version with the chat interview.

## 3. Use it

```
/build-report
```

Opens the report builder in your browser (http://127.0.0.1:8789/). Pick the project and a
template, choose the search criteria and result columns from your environment's fields,
and click **Build report**. Progress, any follow-up question, the rendered pages and the
downloads (rule, `.jrxml`, `RULE-<Code>.zip`) appear on the same page; you do not need to
come back to the chat. Click **Done — stop Claude** when you are finished, or close the tab.

Nothing is imported into eSeries for you. `/test-report` is an older name for the same
command. See `README.md` for what each file in the plugin does.

## Requirements

- Python 3
- A web browser (the builder page runs on 127.0.0.1 only)
- A JasperReports Server install for local rendering (default
  `/Applications/jasperreports-server-9.0.0` — override with the `JRS` environment
  variable if yours lives elsewhere)
- An SDK/JAR export from the target eSeries environment, for field verification
  (the builder asks for one on the page when the project has none; you can skip it, at the
  cost of unverified field names)

## Troubleshooting

- **`/build-report` isn't recognized** — confirm the install landed:
  `/plugin` inside Claude Code lists installed plugins and marketplaces.
- **A script complains about a missing JVM** — set `JRS` to your JasperReports Server
  install, or skip local rendering; building the files does not require it, only the
  `render`/`finish.sh` verification step does.
- **The page says no Claude session is waiting** - `/build-report` is not running in any
  session. Run it; the page picks the build up.
- **An old version of the page opens after an update** - restart Claude Code (the new
  version is only loaded on start), then run `/build-report`.
- **Paths inside the plugin reference `$CLAUDE_PLUGIN_ROOT`** — that variable is set
  automatically once the plugin is loaded (either flow above); you never need to set it
  yourself.
