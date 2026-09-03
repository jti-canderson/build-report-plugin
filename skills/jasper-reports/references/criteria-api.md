# Criteria API and attested traversals

Contents:
- [Where / Or / find](#where--or--find)
- [The addX methods seen in production](#the-addx-methods-seen-in-production)
- [collect() path expressions](#collect-path-expressions)
- [RuleDef.exec](#ruledefexec)
- [Attested traversal inventory](#attested-traversal-inventory)

---

## Where / Or / find

`DomainObject.find` takes the class, an optional `sel(...)` projection, and then any number
of criteria objects as varargs:

```groovy
def people = DomainObject.find(Invoice.class, sel("party.person.id"),
                               whereItemGroup, whereActive, whereBalance)
```

`sel("a.b.c")` projects a value rather than returning entities, so the result is a list of
ids or scalars. `maxResult(n)` can be passed as another argument.

An **empty `Where` or `Or` is a no-op**. That is the mechanism behind every optional
criteria in these reports: always build the object, always pass it, and only populate it
when the parameter has a value.

```groovy
def Where whereCounty = new Where()
if (countyCodes) {
  whereCounty.addIn("party.case.county", countyCodes)
}
// passed unconditionally; filters nothing when countyCodes is empty
```

`Or` is for alternatives and takes `eq(...)` clauses, and can be nested inside a `Where`:

```groovy
Or orAgency = new Or()
if (itemGroup) {
  orAgency.add(eq("invoices.cf_itemGroup", itemGroup))
  orAgency.add(eq("payPlanRestitutions.restitution.cf_itemGroup", itemGroup))
}
where.add(orAgency)
```

**Dotted paths work and cross relations freely.** `addIn("party.case.county", codes)`,
`addEquals("monInstruments.receipt.cases.caseType", t)` and
`addLessThan("glSubsidiaries.paymentInvoiceAssessment.paymentInvoice.receipt.dateCreated", d)`
are all in production. Depth is not the constraint; whether the specific path exists is.

---

## The addX methods seen in production

`addEquals`, `addNotEquals`, `addIn`, `addContains`, `addLessThan`,
`addLessThanOrEquals`, `addGreaterThan`, `addGreaterThanOrEquals`, `addDateRange`,
`addDayRange`, `addIsNull`.

`addIn` accepts a collection and is the right choice for multi-select input controls.
`addDateRange` and `addDayRange` take a low and a high bound.

---

## collect() path expressions

`collect()` walks a path from an entity and can filter with a predicate. Parameters are
positional placeholders `#p1`, `#p2`:

```groovy
party.collect("invoices[cf_itemGroup == #p1].dueDate", itemGroup)
payPlan.collect("installments[balance > 0 && dateDue >= #p1 && dateDue < #p2]", start, end)
receipt.collect("trustTransactions.trust[restitution != null].restitution")
```

The predicate supports `==`, `!=`, comparisons, `&&`, and comparison against `null`.

**Two forms, only one of them proven for entity properties.** A path ending in a property
(`invoices[...].dueDate`) reliably returns a list of that property's values. A path ending
at the collection itself (`invoices[...]`) is used successfully for `installments` on
PayPlan, but the same shape on `Invoice`/`Restitution` from a Party returned an **empty
list** in ODA-4174, which silently emptied the whole obligation half of a report and looked
exactly like a filtering bug. Prefer the suffixed form. If you need whole objects, either
collect `.id` and `DomainObject.get` them, or verify the unsuffixed form returns something
in a real run before building on it.

A filtered `collect()` returns an **empty list** where a plain GPath returns **null**, so
swapping one for the other flips any `x != null` test.

---

## RuleDef.exec

Transient rules are the platform's own calculations, and matching them keeps a report from
disagreeing with the case screen. Signature is
`RuleDef.exec(name, null, argMap).getValue("value")`.

Two are used across the past-due reports:

```groovy
// party scope -- the party's late obligation amount within an item group
com.sustain.rule.model.RuleDef.exec("TRANSIENT_GET_LATE_OBLIGATION_AMOUNTS_BY_CATEGORY",
    null, ["party": party, "category": itemGroup, "onlyOverdue": true]).getValue("value")

// person scope -- the person's obligation balance within an item group
com.sustain.rule.model.RuleDef.exec("TRANSIENT_PERSON_OBLIGATIONS_BALANCE_BY_GROUP",
    null, ["person": p, "category": itemGroup, "onlyOverdue": false]).getValue("value")
```

`onlyOverdue: true` gives the past-due portion, `false` the whole balance. The **person**
rule is called both ways in production; the **party** rule has only ever been called with
`true`, so `false` on it is an assumption. Note the scope difference: a person-scoped rule
cannot be restricted to a county or to a subset of cases, which is what forces per-party
summing whenever a report gains a case-level filter.

Rule names are discoverable by grepping the report folders:

```bash
find . -name '*.groovy' -print0 | xargs -0 grep -hoE 'RuleDef\.exec\("[A-Z_]+"[^)]*\)' | sort -u
```

---

## Attested traversal inventory

"Attested" means it appears in a `.groovy` under `MyReports` that runs in production. Paths
below are grouped by root entity.

**County** — `Case.county` is a `[COUNTY]` lookup list, with `countyLabel` for display.
There is no `cf_county` anywhere.

| Path | Root | Status |
|---|---|---|
| `county` | Case, Ce_VocaDemographic | attested |
| `party.case.county` | Ce_Voca* | attested |
| `receipt.cases.county` | Voucher | attested |
| `monInstruments.receipt.cases.county` | Deposit | attested |
| `payorParties.case.county` | Restitution | **inferred** — halves attested separately |
| `payor.case.county` | PayPlan | **inferred** |

**Party / person / case**

| Path | Notes |
|---|---|
| `party.person.id` | Invoice, via `sel()` |
| `payorParties.person.id` | Restitution, via `sel()` |
| `person.collect("parties")` | all of a person's parties |
| `party.case.cf_courtNum` | court number for display |
| `party.id`, `payor.id` | party identity, for dedup sets |

**Pay plans** — `Party.payPlans` (via `payor_id`) and `Party.billingPayPlans` exist in the
entity docs. `Invoice.payPlan` is a direct many-to-one, and `Invoice` also carries
`payPlanAmountCents` and `payPlanDateAdded`. `Restitution.payPlanRestitutions` is the join
side. On PayPlan itself, `pastDueDays`, `balance`, `installments`, `payor`, `invoices` and
`payPlanRestitutions.restitution` are all attested. `Case.activePayPlans` and
`Case.cf_pastDuePayPlanAmount` exist in the entity docs but are not used by any report yet.

Note `Restitution` has **no** direct `case` relation — reach the case through
`payorParties`.

**Item group** — `cf_itemGroup` is the collecting agency on Invoice, Restitution and
Voucher. On PayPlan it is reached through `invoices.cf_itemGroup` or
`payPlanRestitutions.restitution.cf_itemGroup`, which is why the pay plan query needs an
`Or` rather than a single equals.
