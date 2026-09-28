# The structured build plan and the fast path

`scripts/build_plan.py` — one command for everything mechanical in a report build, driven by
`build-plan.json`. Run `build_plan.py --example` for a complete plan.

## Division of labour

| Who | What |
|---|---|
| **The builder page** | writes `spec.json`: project, template, name, sections, columns, launch inputs, brief |
| **Claude** (judgment) | reads the spec; decides root entity and strategy, which entity each path lands on, awkward fixture rows, assumptions, what is not proven; **writes the rule**; writes `build-plan.json` |
| **`build_plan.py run`** (mechanical) | validate → decide lane → SDK check → batch-resolve every traversal → scaffold → fill fixtures → verify (one JVM) → fill the NOTES seeds → inventory → `BUILD-RESULT {json}` |
| **Claude** | looks at every rendered page, hands over the files |

**The rule is never generated.** Every line of it is a decision, and forcing reports through a
limited rule generator is exactly what this design avoids. The plan records the decisions *behind*
the rule so they can drive field resolution, fixtures, verification and documentation.

## Schema (plan_version 1)

| Key | Meaning |
|---|---|
| `lane` | `fast` or `expert` — what Claude requests; `validate` decides |
| `report` | `folder` (relative to the workspace root), `name`, `title`, `code`, `subtitle`, `slug` |
| `template` | house template module |
| `root` | root entity |
| `rule` | the authored rule's file name |
| `strategy` | `kind`: `direct-record` or `query-list`; `entity`, `id_param`, `filters`, `sort` |
| `params` | `name`, `class`, `coerce`, `required` |
| `sections` | as in `spec.json`: `key`, `title`, `cols` = `[header, width, align, field]` |
| `outputs` | output field expressions (documentation) |
| `traversals` | `field -> Entity.path.to.value`; `[]` marks a collection hop |
| `grouping`, `empty`, `missing` | grouping, empty-result and unresolvable-id behaviour |
| `fixture` | `rows` (awkward!), optional `graph` for `Fixture.groovy` |
| `verification` | `variants` |
| `assumptions`, `unverified` | written into the NOTES blocks and the handoff |
| `specialist` | e.g. `["financials"]` |
| `flags` | `financial_calc`, `custom_layout`, `conflicting_sources`, `unusual_grouping` |

## Lanes — decided in code

**Fast** requires all of: a scaffoldable template (`record_summary`, `eseries_summary`,
`tabular_list`); a `direct-record` or `query-list` strategy; `sdk-decide` exit 0; a root entity
that `model-facts.md` or a precedent already knows; every traversal resolving in the SDK; no flag set.

**Expert** is everything else. `run` refuses an expert plan with exit 20 and lists the reasons; the
existing process applies (which still gets the one-JVM verifier and targeted lookups).
Nothing approximates logic the plan cannot represent.

## Batched field resolution

Each hop of each traversal is checked against the project's SDK jar, following field and getter
types (collections unwrapped by their generic element type). Classes are loaded in rounds — every
class needed at that depth, for every path, in **one** `javap` run with the fast-start JIT.

Measured on the EPQA jar, Case → caseNumber, caseType, filingDate, `parties[].person.lastName` plus
one bogus field: **3.6 s, 1 call** vs **6.5 s, 3 calls** with `sdk_fields.py` per class — and the
per-class way needs the model to work out that `parties` holds `Party` itself.

A path that does not resolve prints a blank column with no error in eSeries, so it forces the
expert lane (exit 20) and nothing is written.

## What it never does

- generate a rule
- overwrite hand-written fixture rows, a hand-edited `Fixture.groovy`, or a NOTES block that is no
  longer the untouched seed
- import anything, or touch an environment

## Exit codes

`0` built, every gate passed · `1` a gate failed (`gates.failed_gate` says which) · `2` invalid plan ·
`3` a judgment file is missing (the rule, or TODO fixture rows) · `20` expert lane
