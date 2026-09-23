---
description: Build an importable eSeries search form (FV search) from a plain description
argument-hint: [anything you already know - environment, root entity, what to search on, what to show]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion, SendUserFile
---

# /build-search

Turn a description of a search into a `FORM-<code>.zip` the user imports into eSeries.

`$ARGUMENTS`

**A search form cannot be corrected in place after import - a bad one has to be deleted and
re-uploaded.** Everything below exists to make the first upload right. The gates are not
optional and a refusal is not a problem to route around: it is the build working.

## 0. Locate the plugin - FIRST

```bash
for p in "$CLAUDE_PLUGIN_ROOT" "$HOME/.claude/plugins/jti-reports" \
         "$HOME/JaspersoftWorkspace/MyReports/jti-reports-plugin"; do
  [ -n "$p" ] && [ -f "$p/skills/report-deployment/scripts/search_build.py" ] && echo "PLUGIN $p" && break
done
```

Use the printed path literally as `$PLUGIN` below. If nothing prints, STOP and ask where the
plugin is - do not search the filesystem for it.

Everything runs on stock `python3` - the Data Dictionary is read with the standard library.
Resolving a hop from an SDK jar needs a JVM; the one bundled with JasperReports is used.

## 1. Which environment? -> its Data Dictionary

The search is built against the **target environment's own model**. Field names, `cf_*`
custom fields and lookup lists differ between clients - `cf_courtNum` resolves in OKDAC and is
refused in the Eh Team environment - so a dictionary from another environment is the wrong
answer, not a close one.

```bash
ls -1 ~/Downloads/DataDictionary-*.xlsx ~/Downloads/ecourt-sdk-*.jar 2>/dev/null
```

Ask with `AskUserQuestion` which environment the search is for, listing the dictionaries on
file. If the target has none, ask for one: **System Setup -> Data Dictionary -> Export** in
that environment. An SDK jar from the same environment is an optional fallback - the
dictionary export leaves the financial module out, and the resolver walks those hops
(`TillDef`, `AssessmentGroup`, `PMInstrumentItem`...) from the jar.

## 2. What should it search, and what should it show?

Free text is fine: *"Search cases by number, status and defendant last name; show case
number, type, status and received date."* Also accept a screenshot of a search screen, or an
exported `FORM-*.zip` to adapt.

Draft a spec from it (`python3 "$PLUGIN/skills/report-deployment/scripts/search_build.py" --example`
prints the shape): `code`, `name`, `root`, `dictionary`, optional `sdk`, `criteria`, `results`.

- **code** - unique in the target environment, `S-` prefix by convention, no spaces.
- **criteria** - `path`, optional `label`, `operator` (EQUALS, NOT_EQUALS, STARTS_WITH,
  ENDS_WITH, CONTAINS, GREATER_THAN, LESS_THAN), `multi`, `default`. With `doubleColumn` the
  criteria are laid out two to a row in the order listed.
- **results** - `path`, optional `label`, `link` (the column that opens the record).

You do NOT set lookup, range or relation - the dictionary decides them: a `Lookup List (X)`
field becomes a picker, a `Date` becomes a range, an entity becomes a relation picker.

Write the spec into the project folder (or the scratchpad), then **show the user the spec in
plain words before building** - one line per field. That is their last chance to catch a
wrong field before it is a file.

## 3. Build

```bash
python3 "$PLUGIN/skills/report-deployment/scripts/search_build.py" "<spec.json>"
```

It prints a resolution table (every path -> the exact class the export records, and what was
derived), runs the gate, and writes `~/Downloads/FORM-<code>.zip`.

**If it REFUSES, fix the spec - never the zip.** A refused path is a field that does not exist
in that environment's model; in a search a wrong field does not error, it silently matches
nothing, so the refusal is the point. Ask the user what they meant, or check the dictionary:

```bash
python3 "$PLUGIN/skills/report-deployment/scripts/dd_resolve.py" "<dictionary.xlsx>" <Root> <path> [<path> ...]
```

Never hand-edit the XML inside the zip. Everything the gate checks - references, counts, the
XStream and JSON halves agreeing - is what a hand edit breaks.

## 4. Hand it over

Send the zip with `SendUserFile`, `display: "attach"`. Then tell the user, in this order:

1. **Where it is**: `~/Downloads/FORM-<code>.zip`.
2. **Where it goes**: the target environment's *Search screens* list
   (`/ecms/admin/forms/list/searches`) -> **Import**.
3. **What is not yet proven**, verbatim from the build's last lines.

**Never import it yourself - importing is a write.** Not in the in-app browser, not in
Chrome, not "just to test".

### The first import of a generated form - a protocol, not a suggestion

Until one generated form has been imported and exported back, the identity fields
(`srcId`, `validationRule ids`) are synthetic and unproven for FORM imports. So the first time:

- import into a **low-stakes environment** (the Eh Team config, not a client's QA);
- confirm the new search opens and runs, and that no existing search changed;
- **import the same zip a second time** and note what happens - a second copy, or an update
  in place. That answer decides how careful every later build has to be;
- **export the imported form back** and give Claude the export. It is the only file that
  shows what the platform does with a form it has never seen - and it closes the last
  unproven surface.

## Scope - what it builds, and what it refuses

Builds: plain, lookup, date-range and relation criteria; labels; operators; defaults;
multi-select pickers; result columns with labels and a link column; any root entity the
dictionary (or SDK) knows.

Not yet, and it will say so rather than approximate: OR-ed criteria (`additionalItems`),
correlated criteria (`subQueryIdentifier`), inline HQL pickers (`customListQuery`),
aggregation (`GROUP_BY`/`SUM`), drilldown forms, hidden forced filters, conditional formats.
Each is a real feature seen in exports; each needs its own byte-for-byte proof first.

The reference for all of it - what is proven, from which files, and what is not:
`$PLUGIN/skills/report-deployment/references/search-forms.md`.
