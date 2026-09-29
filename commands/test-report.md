---
description: TEST build of a report from the local jti-reports-plugin checkout (unreleased branch), not the installed plugin
argument-hint: [same as /build-report - project, template, what the report should show, or a spec.json]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Skill, AskUserQuestion, Task, SendUserFile
model: sonnet
---

# /test-report

`$ARGUMENTS`

This is `/build-report`, run from the **local working checkout** instead of the installed plugin,
so an unpushed branch can be tried for real. It changes nothing about the installed plugin.

## 1. Use the checkout, and say which version this is

```bash
P="$HOME/JaspersoftWorkspace/MyReports/jti-reports-plugin"
[ -f "$P/commands/build-report.md" ] || { echo "NO CHECKOUT at $P"; exit 1; }
echo "PLUGIN $P"
git -C "$P" log -1 --format='TEST BUILD from branch %D, commit %h (%cd)' --date=short
git -C "$P" status --short | head -5
python3 "$P/scripts/build_mode.py"
```

If it prints `NO CHECKOUT`, stop and tell the user. Do not search for it.

Tell the user in one line which branch and commit is under test. If `git status` listed
files, add that uncommitted edits are included. Show the switch settings exactly as
`build_mode.py` printed them.

## 2. Then follow the checkout's /build-report, exactly

Read `$P/commands/build-report.md` (the printed PLUGIN path) in full, and follow it as if the
user had typed `/build-report $ARGUMENTS`, with three substitutions:

- **Paths.** Wherever that file says `${CLAUDE_PLUGIN_ROOT}`, or a path under
  `~/.claude/plugins/...jti-reports...`, use the printed PLUGIN path. Its step 0 ("Locate the
  plugin") is already answered by step 1 above.
- **Skills.** Do not call `Skill(jasper-reports)` or any other jti-reports skill by name. That
  loads the INSTALLED version's instructions, not the branch under test. Read
  `$P/skills/<skill-name>/SKILL.md` instead, and follow any references it names from the same
  checkout.
- **Handoff.** In the handoff, say it was a test build and give the branch and commit.

Everything else in that file applies unchanged: the four questions, every gate, looking at every
rendered page, and the *not verified* list. **Importing is still a write**: hand the zip to the
user, and never import it yourself.
