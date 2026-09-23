# Search forms (FV searches) — what is known, and how it was established

Two independent sources, and they answer different questions. Keep them apart: the export is
what gets generated, the admin screen is what a person configures, and each knows things the
other does not.

| Source | What it settles |
|---|---|
| **28 FORM exports** on this machine, all reproduced byte-for-byte by `form_import.py` | the file format, item classes, every stored key |
| **The Eh Team Config admin**, 36 search screens read 2026-09-21 (read-only) | the UI vocabulary, lookup list names, house defaults, what is rare |

---

## Identifying a search form

`"type": 4` on the form record. Across 28 exports from 6 environments that correlates
exceptionlessly with the `S-*` naming convention — but the convention is a free-text code and
is **not** what the system keys on. `LU-Detainee` sits in the searches list with an `LU-`
code, which is the counterexample.

The admin index is **`/ecms/admin/forms/list/searches`**, a sibling of the folder-views index
at `/ecms/admin/forms/list/folders`. A single form is `/ecms/admin/forms/edit?id=<id>`.

## Criteria vs result columns

One form, one flat `formItems` list, ordered by `num`, criteria and results interleaved.

- In `srcImportContent` they are different Java classes: `SearchCriteriaFormItem` and
  `SearchResultFormItem`, both extending `SearchFormItem`.
- In the `srcContent` JSON that class is **erased**. The only surviving marker is `readonly`:
  `true` = result column, **absent** = criterion. It is a key-PRESENCE test, not a truthiness
  test. Holds on 123 of 125 items across 9 search forms.
- **The admin UI presents them as two separate lists** — "Search Criteria Fields" and "Result
  Columns" — while storing them in one record. That was an open question; the screen settles it.

Shape across the 36 baseline searches: **12–29 criteria, 1–9 result columns**. Criteria
outnumber results heavily on every one of them. (Counts read from the DOM, so approximate;
the export's `readonly` split is authoritative.)

## The house default profile

Of 36 baseline search screens:

| Attribute | Set on |
|---|---|
| `doubleColumn` | 36 / 36 |
| `withBulkActions` | 34 / 36 |
| `skipSearchTotalCount` | 29 / 36 |
| `showGraph` | 4 |
| `showCriteria` | 3 |
| `defaultForm` / `publish` / `pivotTable` | 1 each |

**Everything else is unused.** Exactly two of the 36 set any other option at all —
`S-TimeEntry` has `minSearchFields=1`, `S-ExportBugTest` has `drilldownOptions=ID`. So
`maxResults`, `condition`, `helpKey`, `description` and `securityFilter` are all empty across
the entire baseline. A generated search that leaves them empty matches the house norm; one
that sets them is doing something unusual and should say why.

`unionCriteria` is `ALL` on every form seen, in both sources.

## Criteria features

- **Operators**: `EQUALS`, `NOT_EQUALS`, `STARTS_WITH`, `ENDS_WITH` (UI), plus `GREATER_THAN`
  and `CONTAINS` seen in exports. Absent on 35 of 52 exported criteria — what the platform
  defaults to when the tag is missing is **not established**.
- **Date macros**: `@TODAY` and `@THIS_WEEK` appear as criterion default values. A criterion
  can be pre-filled with a relative date rather than a literal.
- **Regex defaults**: e.g. `/\d{2}-\d{2}/` on a case-number criterion.
- **`subQueryIdentifier` correlates criteria.** Criteria sharing an identifier constrain the
  SAME element of a to-many relation. On `S-Case-Simple`, first/middle/last name and
  `parties[].partyType` all carry `subQueryFunction: EXISTS` with identifier `"def"` — so it
  finds a case with a defendant named John, not a case with some defendant and someone named
  John. Getting this wrong returns plausible wrong rows and never errors.
- **`additionalItems` is the OR.** A nested criterion appears ONCE in the XStream and TWICE in
  the JSON (nested and top-level). Counting JSON items naively double-counts. `S-Person-Simple`
  has 4 `additionalItems` blocks holding **6** items — counting blocks is also wrong.
- **Hidden forced filters**: `hidden: true` plus a `defaultValue`, or plus `operator` +
  `condValue`. The stored keys are proven; that the platform applies them and forbids override
  is inference from the key names.
- **Picklists**: a lookup list, or an inline HQL query via `customListType: QUERY` +
  `customListQuery` — which carries live Velocity, including `$DomainObject.querySQL(...)`.

## Lookup list names — the export does not carry them, the UI does

No tag in any export names the list behind a criterion. The admin screen shows it beside the
field. Seen in the baseline: `CASE_STATUS`, `CASE_TYPE`, `PARTY_TYPE`, `PERSON_TYPE`,
`DIR_ORG_TYPE`, `GENDER`, `ETHNICITY`, `EVENT_TYPE`, `EVENT_RESULT`,
`PERSON_REMOTE_ENV_SEARCH`. To resolve one for a form you only have as a file, read it off the
admin screen or query `LookupList`/`LookupItem`/`LookupAttribute` at run time.

## Drilldowns

`drilldownForm` names a **separate form record** — itself type 4, with its own criteria and
result columns. It is not the results half of the parent.

- The XStream namespaces it as `FORM=<code>`; the JSON carries the bare code; **the admin UI
  field holds the numeric form id**. Three spellings of the same link.
- Drilldown targets are ordinary searches and can be shared: two baseline forms both drill to
  form 87 (`S-CaseAssignment`).
- They chain: `S-Party-PIP-OpenCase` → `S-Party-PIP-OpenCase-DD-Charges`.
- `-DD` is a convention, not a rule (`S-CheckBatch` → `S-CheckBatch-Detail`).

## The platform validates config itself

The searches index filters by **Validation issues** and **Performance issues** — the platform
has its own opinion about whether a form is sound. On the baseline, **zero of 36** are flagged
on either. That is a free post-import check worth using: import, then look at whether the new
form appears under those filters.

## `validationRule ids` — count is meaningful, contents are not understood

Every export carries `<validationRule ids="...">` at the top of `screen-config-root`. Across
all 28 exports the id COUNT equals items + nested items, exceptionlessly — so there is one id
per form item. But:

- only **15 of 28** exports carry `configSourceId` on their items at all, and never on every
  item;
- the `configSourceId` set **never** equals the `validationRule ids` set, on any export.

So these are per-item primary keys from the source environment, but NOT the ids the items
themselves carry. What the importer does with them is unknown. Practical consequence: a
composed form that KEEPS every donor item leaves the list consistent in length and is safe;
one that drops or adds items leaves a list whose length no longer matches, and nothing here
says whether that matters. Until somebody watches that import, compose by keeping all items.

## Layout: `doubleColumn` alternates by `num`

With `doubleColumn` (set on 36 of 36 baseline searches), criteria alternate between the two
columns in `num` order — even to the left, odd to the right. On `S-Case-Simple` the criteria
are numbered caseNumber 6, location 7, firstName 8, caseType 9, middleName 10, status 11,
lastName 12, partyType 13, and the screen renders names down the left and case attributes down
the right. **Screen position is therefore controlled by interleaving the numbering**, not by
listing one column and then the other — which is the natural thing to assume and is wrong.

## The item schema, measured — what synthesising an item requires

Derived from all 841 top-level items in the 28 exports, not from reading one file.

**Field order is canonical and total.** One ordering explains all 1,051 `<default>` blocks with
zero cycles: nine unboxed primitives alphabetically (`grid, hidden, link, noHoliday, noWeekend,
num, readonly, required, type`), then the remaining 89 alphabetically. Per-class blocks follow
the same rule — `SearchCriteriaFormItem` has 9 fields of its own, `SearchResultFormItem` 4.

**But the emitted field SET is not canonical.** For a type-0 search criterion there are **47
distinct field sets** across 107 items; for a result column, 36 across 106. They cluster at two
extremes:

| Shape | Fields | Example |
|---|---|---|
| minimal | 25–28 | `S-Deposit-Listing-DD.depositDate` (9 items share it) |
| rich | 53–58 | `S-VoucherReconcile.cf_itemGroup` (58 fields) |

The core present on **every** type-0 criterion is 25 fields:

```
associatedForm carryOver conditionalFormats conditions existingEntityConditions
filterConditions grid hidden link multiSelectLookup newColumn newRow noHoliday
noWeekend num parameters path readonly required showIfValues showIfValues2 type
userSelectedList widgetInMassType xrefConditions
```

**Consequence for generation.** Byte-equality against an arbitrary existing item is NOT an
available oracle for synthesis — the platform itself does not emit a consistent set, so there
is no single right answer to reproduce. Emit the **minimal** shape: the 25-field core plus only
the fields the described search actually needs. It is the smallest surface to be right about,
and real exports demonstrably ship items at that size, so the importer must already be filling
the rest with defaults.

The oracle that IS available: take the real items whose field set equals the minimal shape,
re-synthesise each from its semantic content alone, and require byte equality. That validates
the emitter against real files without pretending the format is more determinate than it is.

**Structural values that must be emitted exactly** (constant on all 855 blocks):

| Field | Value |
|---|---|
| `associatedForm` | `<associatedForm reference="../../../../.."/>` — and the `../` DEPTH grows with nesting (9 levels for an item inside `additionalItems`) |
| `showIfValues`, `showIfValues2` | `<... class="sorted-set"/>` |
| `existingEntityConditions`, `filterConditions`, `xrefConditions`, `parameters` | self-closing |
| `widgetInMassType` | `NEVER_SHOW` |
| `noHoliday`, `noWeekend` | `false` |

**The one thing not in the search corpus — but fully available from the model.** Each item's
`FormItem` block is followed by `<string>com.sustain.cases.model.Case.caseNumber</string>` —
the resolved terminal `entityClass.field` for its path — then `<null/>`. A path no export
contains has no string to copy, so it must be resolved from the environment's model. This is
NOT a gap in what can be known; it is metadata both model exports carry, proven 2026-09-22:

- **SDK jar** (`javap` against `ecourt-sdk-local-2026-09-17.jar`): resolves every path in
  `S-Case-Simple` to exactly the string the export carries, including the CUSTOM field
  (`Case.cf_courtNum`) and the deep traversal — `getParties()` returns `Set<Party>`,
  `getPartyType()` on `Party` → `Party.partyType`; `parties.person.firstName` walks to
  `PersonComponent.getFirstName()`. TRAP: the export names the CONCRETE entity
  (`person.model.Person.firstName`) while the getter is declared on the superclass
  `PersonComponent` — so the terminal must be the concrete relation target, not the getter's
  declaring class. This is the same field-owner vs getter-owner split `sdk_fields.py` handles.
  There is no bundled JVM on the host by default; `javap` lives at
  `/Applications/jasperreports-server-*/java/bin/javap`.
- **Data Dictionary `.xlsx`** is the RICHER source and the better ask: per field it gives the
  type as `Collection (Party)` (the relation target that lets a traversal be walked) and
  `Lookup List (CASE_STATUS)` — which is **the lookup-list name the search export never carries
  and which otherwise has to be read off the admin screen**. It needs no inheritance walk and
  no field-owner/getter-owner reconciliation.

So `/build-search` should ask for a Data Dictionary export (SDK jar as fallback/cross-check),
and with one in hand a novel path is fully resolvable — terminal class, relation targets, and
lookup list names all included. It is required, not because the metadata is unknowable, but
because it is per-environment: `cf_*` fields and lookup lists differ between clients.

## Still not established

- **How criteria reach a report rule at run time.** Nothing in any source connects a user
  typing into a search screen to a rule input parameter. The only attested parameter origin is
  the report launch form. Treat both "it does" and "it does not" as unproven.
- The default operator when the tag is absent (35 of 52 criteria).
- What `unionCriteria: ALL` does at query time, and `skipSearchTotalCount`, `doubleColumn`,
  `showGraph` behaviour.
- Whether a *generated* form — as opposed to a reproduced one — imports cleanly. Byte equality
  proves the writer reproduces; it does not prove a novel combination is accepted.
- Whether re-importing the same code updates a form in place or duplicates it.
- The populated form of `hqlExpression`, `compoundCriteriaField`, `split`, `userSelectedList`,
  `existingEntityConditions`, `filterConditions`, `xrefConditions` — present in the schema,
  empty in all 28 exports.

## From-scratch synthesis — proven, and the two surfaces that are not

Building a search from a DESCRIPTION means emitting items for paths no export contains. Proven
2026-09-22 by re-synthesising real CLEAN (no-`configSourceId`) items from their semantics alone
and requiring byte equality:

- **criteria: 11/11** clean simple criteria reproduced byte-for-byte (plain, date-range, lookup).
- **result columns: both clean shapes** reproduced (`link=true`→`panelAutoCompleteWithAllData`
  present, `link=false`→absent; the `link=true`+pac-absent variant is a config toggle the
  emitter does not offer, not a defect).

A from-scratch item omits `configSourceId` (a source-environment primary key a new item never
had) and carries only the minimal-shape field set. `synth_criterion` / `synth_result` in
`form_import.py` are the emitters; `build_search` assembles a whole form by swapping synthesised
items into a real donor's envelope (head/tail/settings), same root entity.

**Two surfaces cannot be validated offline** and are flagged by `build_search`, because every
example on disk is already provisioned:

1. **form-level `<validationRule ids>`** — one per item, source-env pks, never empty in any
   export, no fresh-form example. `build_search` keeps the count consistent by reusing donor
   values; whether a new form needs real ids, a blank list, or a matching count is UNKNOWN.
2. **`srcContent` sparse-JSON key order** — the payload is `srcImportContent` (the XStream, built
   from proven items); `srcContent` is rebuilt to agree on paths and counts but its key order is
   canonical and may differ from the platform serializer.

**Therefore the safe first import is a CLONE** (`--copy`, byte-identical envelope to a real
form), which proves the pipeline imports at all and — imported twice — answers the
update-vs-duplicate question, before any from-scratch form is trusted. A from-scratch form
should follow only once an observed import has settled surfaces (1) and (2).

## SDK stub omits some derived getters — the DD is the fallback resolver

Resolving a path to its terminal `entityClass.field` via `javap` works for direct and most
traversal segments (6/7 in a Case search, including custom `cf_courtNum`), but the stub jar
omits some derived getters — `Party.person` has `setPerson(Person)` and no `getPerson()`, so
`parties.person.<field>` cannot be walked from the jar alone. The Data Dictionary carries that
relation and is the resolver of record for traversals; the SDK jar is the cross-check.

## Corrections from the 2026-09-22 review — read before trusting anything above

**The formItems list includes reference entries.** A form with an OR-ed criterion has one
more list entry than it has full items: a self-closing XStream back-reference at the end of
`<formItems>` (`<SearchCriteriaFormItem reference="../SearchCriteriaFormItem/.../additionalItems/SearchCriteriaFormItem"/>`)
that puts the nested criterion into the list without serialising it twice. The earlier claim
"14 items in the XStream, 15 in the JSON" was wrong: the list has 15 entries in BOTH halves,
and **list length == JSON length == validationRule id count on every export (28/28)**. The
reference picks its target by POSITION among criterion siblings, so reordering items silently
repoints it; removing its parent leaves it dangling. `compose` rebuilds it; the gate follows
every reference and faults on one that dangles.

**The JSON half is a projection of the XStream, and is now checked item by item.** One total
key order explains all 869 JSON items (declaration order, subclass fields first). A field
surfaces iff its value is non-default; multi-line strings become arrays of lines;
`parameters`/`conditions`/`conditionalFormats`/`userSelectedList` become structures;
`FORM=`/`CONDITION=` prefixes drop; sets come out sorted, `conditionalFormats` in hash order;
a condition's `hash` is not in the XStream at all. **Type comes from the field, not the text** —
`conditionalFormat.value` stays the string `"false"`, `includeNulls` is a boolean. The
projection reproduces 220 of 220 comparable search-form items byte-for-byte, and the gate's
XStream↔JSON agreement check has zero false faults on all 28 exports.

**A labelled criterion is always the full shape.** Every criterion with a custom label is
written in 54–56 fields, never the minimal ~26 — setting a label makes the admin write
everything. The constant part was extracted from the 6 clean labelled type-0 criteria
(identical on all of them); `synth_criterion_labelled` reproduces all 6 byte-for-byte. Two
semantic extras: `forceCreateObject=false` on a criterion whose path ends at an ENTITY (a
person picker), and a `memo` (an admin note, e.g. a ticket number) on the DomainObject block.

**Field resolution: the Data Dictionary first, the SDK jar for what it omits.** `dd_resolve.py`
walks a path hop by hop through the DD (`Collection (X)` = to-many, a bare entity name =
to-one, `Lookup List (X)` = picker, `Date` = range). The DD export leaves the financial
module out entirely — `TillDef`, `AssessmentGroup`, `PMInstrumentItem`, `Restitution`,
`AgencyAccount`, `CreditAuthorization` and root `CheckBatch` are in no dictionary on this
machine — so those hops, and base fields like `id` that no DD lists, fall back to the jar,
returning to the DD as soon as it covers the entity again (the jar lacks `getPerson`). Against
what the platform itself recorded: **OKDAC 410 identical (295 dictionary, 115 jar), Eh Team
65 identical, 0 wrong, 0 refused.** The DD is read with the standard library — identical to
openpyxl on all three dictionaries — so nothing needs installing.

**Generated forms carry synthetic identity; copies carry the source's.** `srcId` and the
validationRule ids look like the keys a later re-import matches on (an imported item stores
the source id as `configSourceId`). So a copy — like any cross-environment promotion — keeps
the source form's ids and must NOT be imported into the environment that holds the source
form; a generated form gets deterministic ids above 900,000,000 (max real id seen ~26,000)
and `srcActionUrl` on `generated.invalid`, so the worst case of an unaccepted identity is a
clean rejection rather than a collision.

