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

**The one thing not derivable from the corpus.** Each item's `FormItem` block is followed by
`<string>com.sustain.cases.model.Case.caseNumber</string>` — the resolved terminal
`entityClass.field` for its path — then `<null/>`. For a path no export contains, that class
has to be resolved from the environment's own model. That is exactly what the SDK answers, and
it is why `/build-search` must ask for one rather than treat it as optional.

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
