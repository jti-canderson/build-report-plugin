# Report rules — the data

*Part of the `jasper-reports` skill. Read when writing or debugging the Groovy that feeds a report: criteria, traversals, parameters, empty or duplicated rows.*

# Report business rules

A report is two halves: a Groovy business rule that builds `_data` (a list of Maps, one per
row) and a `.jrxml` that renders it from an empty query. This skill is about the rule and
the domain model behind it. For compiling, rendering and looking at the output, use the
`jasperreports-verification` skill — the two are meant to be used together, and its
`references/gotchas.md` covers Groovy and domain-model traps not repeated here.

## The one discipline that matters most

**Every traversal you write should be one you have seen work, and every one you invent
should be labelled as a guess when you hand it over.**

The failure mode here is silent. A path that does not resolve, or a null fed into a date
criteria, does not throw — it returns nothing, and the report renders a clean, plausible,
short page. Nobody can tell that from a report that legitimately has few rows. In ODA-4174 a
single unproven `collect()` form emptied half a merged report, and it took a before/after
comparison against a known-good version to notice at all.

So before writing a path, check whether it already exists:

```bash
cd "$MYREPORTS"
find . -name '*.groovy' -print0 | xargs -0 grep -n 'party.case.county'
find . -name '*.groovy' -print0 | xargs -0 grep -hoE 'add(Equals|In|DateRange|LessThan)\("[a-zA-Z_][a-zA-Z_.]*"' | sort | uniq -c | sort -rn
```

`references/criteria-api.md` has the full API and an inventory of which paths are attested
versus inferred. Read it before writing criteria. `scripts/entity_field.py` searches the
entity reference PDFs when the codebase has no precedent:

```bash
SK=jasper-reports
K=$(for p in . .. ../.. ../../..; do for b in System/Skills .claude/skills; do
      [ -d "$p/$b/$SK" ] && { echo "$p/$b/$SK"; exit; }; done; done
    [ -d "$HOME/.claude/skills/$SK" ] && echo "$HOME/.claude/skills/$SK")
S=$K/scripts
python3 "$S/entity_field.py" county
python3 "$S/entity_field.py" payPlan --dir "$MYREPORTS/Entities"
```

Those PDFs are the offline source of truth for property names and types. `pdftotext` is not
installed on these machines, which is why the script uses PyMuPDF — a `pdftotext` that
silently returns nothing will make you conclude a field does not exist.


## Rich-text fields usually hold a template, not prose

A field whose name suggests free text — `statuteLanguage`, `memo`, a `materialized_clob` — is often a **document template** rather than something readable. For example, `Charge.statute.statuteLanguage` holds the charging-document body:

```
<p>The defendant <defendant>, on or about <chargedate>, in Marion County, Oregon, did
unlawfully and intentionally <inchoate> cause serious physical injury to <victim> …</p>
<p>$document.docNumber</p>
```

Printed raw that is the ugliest thing on the page, and stripping the tags leaves prose full of holes where the merge fields were. Neither is worth shipping.

Decide in the **rule**, not the layout, and make the decision total: emit clean prose or emit an empty string, so the layout only has to ask "is this blank".

```groovy
def HTML_TAGS = ['p','br','b','i','u','strong','em','ul','ol','li','span','div','a', …]
def cleanRichText = { v ->
    def raw = str(v)
    if (!raw) return ""
    if (raw.contains('$')) return ""                       // Velocity reference
    def names = (raw =~ /<\s*\/?\s*([a-zA-Z][\w-]*)/).collect { it[1].toLowerCase() }
    if (names.any { !HTML_TAGS.contains(it) }) return ""   // merge placeholder
    raw.replaceAll(/<[^>]+>/, ' ').replaceAll(/&nbsp;/, ' ')
       .replaceAll(/&lt;/, '<').replaceAll(/&gt;/, '>').replaceAll(/&amp;/, '&')
       .replaceAll(/\s+/, ' ').trim()
}
```

Two tests, in this order, because they catch different templates: a `$` anywhere means Velocity, and a tag name outside the HTML whitelist means a merge placeholder. Real statute prose wrapped in `<p>` and `<b>` passes both and gets its tags stripped.

Check the actual strings from a render before trusting a cleaner like this — paste them into a scratch script and confirm each one is classified the way you intend. It is a two-minute check that a render cycle cannot give you.


## Report parameters

A `<parameter name="County" class="java.lang.String"/>` in the `.jrxml` becomes `_County` in
the rule. That is the whole wiring. Parameters are usually not referenced by `$P{}` in the
template at all; they exist to be surfaced as input controls and forwarded to the rule.

**Required versus optional is not a `.jrxml` property.** JasperReports does not enforce
mandatory parameters — that flag lives in the app's report parameter setup. Your rule can
tolerate a blank value, but the UI will still refuse to submit until someone marks the
control non-mandatory. Say so explicitly when handing over an "optional" criteria, or the
user will test it and conclude your code is broken.

**Normalize before using.** An input control hands back a single `String` when one item is
picked and a `Collection` when it is multi-select, and either can be null:

```groovy
def countyCodes = (_County instanceof Collection)
    ? _County.findAll { it != null }.collect { it.toString() }
    : (_County ? [_County.toString()] : [])
```

Declared parameters arrive in the binding as null rather than being absent, which is why
bare `if (_County)` is safe and is what the existing reports do.

**Never let a blank parameter become a filter value.** `def x = _Param ?: ''` followed by
`addEquals("cf_itemGroup", x)` filters for an empty item group and matches nothing. That
pattern exists in the past-due reports and is a live bug, not a model to copy. Guard the
clause instead, and be consistent about it — a report where one query treats a blank agency
as "all" and another treats it as "none" returns a half-populated page that is very hard to
reason about.

**A null date bound matches nothing.** `addDateRange(field, start, null)` and
`collect("installments[dateDue < #p2]", null)` do not ignore the bound, they exclude
everything. Resolve the window once, with defaults that mean what a user would expect:

```groovy
def rangeStart = _StartDate ?: new Date(0)
def rangeEnd = _EndDate ?: today
def rangeEndExclusive = rangeEnd + 1   // for predicates that use "<"
```

Adding a day to convert an exclusive bound to an inclusive one is the established idiom
here (`throughDatePlusOneDate` in the Voucher reports). Worth doing deliberately, because
mixing an inclusive `addDateRange` with an exclusive `<` in the same report means an item
due exactly on the end date appears in one half and not the other.

## When the output says "null"

JasperReports **swallows NullPointerException during expression evaluation** and yields
null, which a text field without `isBlankWhenNull` then renders as the literal string
`null`. So `new SimpleDateFormat("MM/dd/yyyy").format($F{someDate})` prints `null` rather
than failing when the date is missing. ClassCastException is *not* swallowed, so a
type mismatch does surface as a stack trace.

Two consequences. A literal `null` in the output means a value never arrived — chase the
data, not the template. And a report that renders without error has not proven its
expressions are sound.

## Scope mismatches force restructuring

Person-scoped and party-scoped calculations are not interchangeable, and this is what makes
"just add a filter" expensive. `TRANSIENT_PERSON_OBLIGATIONS_BALANCE_BY_GROUP` takes a
person and an item group and nothing else. The moment a report gains a case-level criteria
like County, any figure from that rule is wrong for filtered rows, because it silently
includes cases the user excluded.

The usual resolution is to sum a party-scoped equivalent across the parties that survive the
filter. Two things to hold onto when you do:

- Keep the unfiltered path on the original call, so the report's existing numbers do not
  move when nobody selects the new criteria. A change that alters output in the default case
  is a change the user did not ask for.
- Say which of the two calls is unattested. If a party-scoped rule has only ever been called
  one way in production, calling it the other way is a hypothesis — and it is worth telling
  the user what a wrong answer will look like ("Total Balance equal to Amount Past Due, or
  zero") so a bad result is diagnosable rather than mysterious.

## Deduplicating across two sources

Merging reports means two queries that can describe the same money. Pick the level at which
you deduplicate and be honest about what it costs:

- **Per obligation** is exact but needs a traversal that tells you whether an obligation is
  on a plan (`Invoice.payPlan`, `Restitution.payPlanRestitutions`).
- **Per party** is coarser — a party with both a plan and separate unplanned obligations
  gets reported only once — but needs nothing beyond ids you already have.

And do not assume the two sources partition the population. A pay plan reschedules its
obligations, so a plan can be overdue while the obligation underneath it is not yet due;
those people are invisible to an obligation query and have to be unioned in. That population
is usually the actual reason for merging, so it deserves a test case of its own.

**Do not sum figures that may overlap each other.** Two active pay plans on one case can
cover the same obligations (ODA-4174, case 26-23: one plan covered all $367, another covered
the $148 restitution already inside it). Summing plan balances double counted; summing
overdue installments did not, because those do not overlap. Prefer deriving a balance from
the obligations, and reconcile against the case screen before believing any total.

## Reconciling a report against the case screen

The case Financials screen is the ground truth you can reach without database access, and
matching it is how you prove a rule rather than assert it. Ask the user to print the case to
PDF, then rebuild its tables:

```bash
SK=jasper-reports
K=$(for p in . .. ../.. ../../..; do for b in System/Skills .claude/skills; do
      [ -d "$p/$b/$SK" ] && { echo "$p/$b/$SK"; exit; }; done; done
    [ -d "$HOME/.claude/skills/$SK" ] && echo "$HOME/.claude/skills/$SK")
S=$K/scripts
python3 "$S/case_pdf_tables.py" "Case.pdf" --rows           # look at the raw shape first
python3 "$S/case_pdf_tables.py" "Case.pdf" --obligations --match Bogus
python3 "$S/case_pdf_tables.py" "Case.pdf" --installments
```

Reading these PDFs in raw text order does not work — the columns fragment and labels,
amounts and statuses interleave, so hand-summing produces confidently wrong numbers. The
script groups words by y coordinate to rebuild the visual rows, then subtotals current
balances for the rows you filter to. Labels can truncate to their last wrapped fragment;
the amounts and dates are what you are reconciling, so that is usually fine.

How to compare:

- A report scoped to a collecting agency will **not** match the case header total. Filter to
  that item group's obligations and subtotal those. In ODA-4174 the header said $14,978
  while the report correctly said $12,537, because a $2,441 restitution belonged to another
  group.
- An amount-past-due driven by a pay plan should equal the sum of its **Past Due**
  installments only. Scheduled rows sit right underneath them and inflate the figure if you
  include them.
- The case header's own `Past Due` badge is a good independent check on a plan-derived
  figure.
- Inactive pay plans appear in their own section. A query filtered to `status = ACTIVE`
  correctly ignores them — do not count them when reconciling by hand.

State plainly what reconciled and what did not. "All five rows match the case screens; the
county paths are still unproven because no county was selected in this run" is worth far
more than "verified".

## Version files

While a change is still being iterated on, edit the same file rather than incrementing to a
new `_V4`, `_V5` — a folder full of broken versions destroys the value of version numbers as
rollback points. Bump the number once a version is confirmed working. Keep hard-won findings
from a failed attempt as a comment in the file, not as a leftover file.

Rule and template version numbers are independent; they pair by which fields they exchange.
State the pairing whenever you hand over either half, because deploying one without the
other makes fields resolve to null and the report renders blanks or the literal `null`
rather than failing.

## Fetching a record by id

`Entity.get(id)` is **not** uniformly available. One-argument `get` works on some classes (`Case.get(_caseId)`, `Receipt.get(_receiptId)`) and not others — on `DiscoveryItem` it raises `MissingMethodException`, listing the real signatures: `get(String, Serializable)`, `get(Class, Serializable)`, `get(MdEntity, Serializable)`.

The portable form is the **two-argument get with a Long id**, verified by probe on `DiscoveryItem` id 109:

| call | result |
|---|---|
| `get('DiscoveryItem', id as String)` | TypeMismatchException |
| `get('DiscoveryItem', id as Long)` | works |
| `get(DiscoveryItem, id as Long)` | works — prefer this, no name string to typo |
| `DiscoveryItem.find(where)` | IllegalArgumentException — not the API |

Since report parameters arrive as Strings, coerce first:

```groovy
def asLong = { v -> (v == null || !v.toString().trim()) ? null : v.toString().trim() as Long }
def item = DiscoveryItem.get(DiscoveryItem, asLong(_discoveryItemId))
```

Record ids are globally unique, so a child id alone is enough to scope a report — do not require a parent id as a traversal root just because `get()` is misbehaving. If a lookup fails, probe the available signatures (see `business-rules`) rather than working around it.
