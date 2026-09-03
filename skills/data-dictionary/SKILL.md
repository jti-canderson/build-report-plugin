---
name: data-dictionary
description: >-
  Read an eSeries Data Dictionary export (.xlsx) to answer domain-model questions offline —
  does a field exist, what is its exact type and length, what lookup list does it use, what
  relations and traversals exist from an entity, which widgets are valid there, and how two
  environments differ. Use this whenever you need the model and there is an export
  available, and use it *first* rather than clicking through the admin: one file answers in
  seconds what browsing answers in dozens of page loads. Also use it when a field name is
  in doubt, when a report or widget returns blank, or when promoting config between
  environments. If no export has been provided, ask the user for one — it is a single
  button in the admin (see "Getting an export").
---

# The eSeries Data Dictionary

A Data Dictionary export is the whole domain model of one environment in a single
spreadsheet: every entity, its table, every field with type and description, every relation,
every lookup list with example values, and every widget available at each entity.

It replaces most of the clicking. Before opening the admin to ask "does this field exist"
or "what is this type", check whether an export is available and read it.

## Getting an export

**System Setup → Metadata → Entities**, then the **Data Dictionary** button (Excel icon,
top of the entity index). It downloads as
`DataDictionary-<environmentLabel>-<YYYY-MM-DD>.xlsx`, so the filename records which
environment and when — worth keeping in the filename when you save it.

**A report or form dropped in with no dictionary is the common case.** The `jasper-reports`
intake gates on this: settle the target environment, then check whether the dictionary you hold
is for *that* environment before deriving any path. A dictionary from a different environment
tells you what a different site has.

**If you have no export and need the model, ask for one.** Say it plainly: *"Please upload a
Data Dictionary from that environment — System Setup → Metadata → Entities, then the Data
Dictionary button."* That is faster and more reliable than me browsing, and it works for
environments I cannot reach. Ask again when the target environment changes: **exports are
per-environment and per-date**, and the differences matter (see Diffing).

## Reading one

The file has a single sheet, no header row, and one row per field. Roughly 43,000 rows and
~290 entities is normal.

| Column | Meaning |
|---|---|
| **A** | Entity name — populated **only** on an entity header row |
| **B** | on a header row: the table (`tADR`); on a field row: the field/relation/widget name |
| **C** | the type (see below) |
| **D** | description |
| **E** | `Not Null` |
| **F** | `Unique` |
| **G** | `Indexed` |
| **H** | `Examples: a,b,c` — for lookup lists, a sample of the list's values |

Rows belong to the most recent entity header above them. Column A on field rows contains
whitespace, not an empty string, so test with `.strip()`.

Column C is the whole vocabulary:

| Value | Means |
|---|---|
| `String (255)` | scalar with max length; `String (0)` and `String (7500)` both occur |
| `Lookup List (CODE)` | lookup field; `CODE` is the list, and column H samples its values |
| `Date`, `Time` | temporal — note the editor's own type may be `timestamp` |
| `Double`, `double`, `Long`, `long`, `int`, `Integer`, `boolean`, `Boolean` | numeric/boolean; **case is meaningful** (`Boolean` is nullable, `boolean` is not) |
| `Collection (Target)` | **one-to-many** to `Target` |
| a bare entity name (`Case`, `Party`, `Document`) | **many-to-one** to that entity |
| `Widget` | a widget available at this entity, with its description in D |

## Querying it

`openpyxl` is not installed on this machine, so use the bundled parser — it is
standard-library only:

```bash
SK=data-dictionary
K=$(for p in . .. ../.. ../../..; do for b in System/Skills .claude/skills; do
      [ -d "$p/$b/$SK" ] && { echo "$p/$b/$SK"; exit; }; done; done
    [ -d "$HOME/.claude/skills/$SK" ] && echo "$HOME/.claude/skills/$SK")
D=$K/scripts/dd.py

python3 $D summary  dict.xlsx                      # entity/row counts, custom entities
python3 $D entity   dict.xlsx DiscoveryItem        # fields (add --all for widgets)
python3 $D rels     dict.xlsx DiscoveryItem        # many-to-one and one-to-many
python3 $D widgets  dict.xlsx DiscoveryItem        # widgets valid there
python3 $D type     dict.xlsx Document.originalFileName
python3 $D find     dict.xlsx 'storageSize|nameExact'   # regex over entity + field names
python3 $D lookups  dict.xlsx 'REFERRAL'           # lookup codes and who uses them
python3 $D diff     a.xlsx b.xlsx [Entity]         # environment comparison
```

`rels` is the one to reach for when building a traversal: it prints both directions, and the
`Collection (Target)` rows are the peer collections you traverse *from* the parent.

## What it settles, and what it does not

Settles immediately — no browsing:

- whether a field exists and its exact type, length, nullability, uniqueness, index
- which lookup list a field uses, plus sample values
- every relation from an entity, in both directions
- which widgets are valid at an entity (matches the form editor's path-scoped picker exactly)
- whether an entity or field exists in one environment and not another

Does **not** answer, so do not conclude from silence:

- **which paths the UI actually uses.** The dictionary lists everything that exists; a
  folder view uses a specific subset, sometimes surprising ones. The form config is
  authoritative for that.
- **whether a value is populated in practice.** `Document.nameExact` exists as
  `String (255)` and is empty in real data, while `originalFileName` holds the filename.
  Only real data answers this — the Velocity Test page against a real id, or an export of
  the data itself.
- **peer field names for relations.** You get the target entity, not the name the reverse
  side is called on it. The entity metadata screen shows that.
- ids of any kind (form, rule, report), rule or report configuration, or system properties.
- **lookup list membership.** Column H is a truncated sample labelled `Examples:`, not the
  list.

It is also a **snapshot**. If someone has changed config since the export, it is stale —
check the date in the filename before trusting it for a config decision.

## Diffing environments

This is where the export earns its keep, because config does not sync between environments
and the differences are exactly what breaks a promotion.

```bash
python3 $D diff config.xlsx master.xlsx              # which entities exist where
python3 $D diff config.xlsx master.xlsx DiscoveryItem # field-level, incl. type changes
```

Two real examples from the pair used to build this skill (`TheEhTeamConfig` 282 entities vs
`local` 293):

- **Custom entities diverge.** 11 custom entities on one, 23 on the other; `C_Investigation`
  and `Ce_PlanningSheet` exist only on the first, a dozen `Ce_*` staging and legacy entities
  only on the second. Custom entities are prefixed `C_`, `Ce_`, `CE_`, `D_`, `g_`, `wc_`.
- **Widgets differ per environment.** `Case` has `AddNewPetitionWidget` and
  `OpenSharebookWidget` on one, `ALLPAID_SUBMISSION` and `ObligationSummaryWidget` on the
  other. So before configuring a widget, confirm it exists in the *target* environment —
  and the same caution applies to lookup lists, which also differ.

When promoting an entity or a form between environments, diff first: it tells you what will
be missing on the far side before you start typing.
