---
description: Alias of /build-report - the same browser report builder
argument-hint: [optional - nothing is needed; the builder page collects everything]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
model: sonnet
---

# /test-report (alias of /build-report)

`$ARGUMENTS`

This is the old name of `/build-report`, kept so it keeps working. There is one builder.
Read `commands/build-report.md` from the same plugin folder as this file (the folder above
`commands/`; loaded as a plugin command that is `${CLAUDE_PLUGIN_ROOT}`) and follow it
exactly, with `$ARGUMENTS` as above. In its step 1, prefix the block with
`JTI_PLUGIN="<that plugin folder>"` so it runs this same copy.
