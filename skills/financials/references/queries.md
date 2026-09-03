# Financial query patterns

Every pattern here is taken from a working report in the corpus. Where an idiom is known to
fail, that is recorded too — those cost real debugging.

## The id-then-get pattern

`DomainObject.find` with `sel('id')` returns ids, not objects. Fetch each one.

```groovy
Where cse = new Where()
cse.addGreaterThanOrEquals("dateCreated", _StartDate)
cse.addLessThan("dateCreated", DateUtil.addDays(_EndDate, 1))
if (_PaymentType) {
    cse.addEquals("monInstruments.instrumentType", _PaymentType)
}

def payments = DomainObject.find(Payment.class, sel('id'), cse)
def objects = []
for (p in payments) { objects << Payment.get(p) }
```

Criteria paths traverse relations with dots — `monInstruments.paymentInvoices.invoice.cf_itemGroup`
is a legal criteria path even though it crosses three relations.

## Several Where objects, ANDed

`find` takes them as varargs. This reads better than one giant `Where`, and lets you build a
filter conditionally and pass it empty.

```groovy
def Where wherePlanActive = new Where()
wherePlanActive.addEquals("status", 'ACTIVE')

def Where wherePlanInstallmentDate = new Where()
wherePlanInstallmentDate.addDateRange("installments.dateDue", rangeStart, rangeEnd)

def Where wherePlanCounty = new Where()          // left empty when no county was picked
if (countyCodes) { wherePlanCounty.addIn("cases.county", countyCodes) }

def plans = DomainObject.find(PayPlan.class, sel("id"),
                              wherePlanActive, orAgency, wherePlanInstallmentDate, wherePlanCounty)
plans = plans.unique()
plans.removeAll([null])
```

`find` can return duplicates and nulls when the criteria cross a collection. Dedupe.

## Either-branch filters with Or

An agency or item-group filter must hit both allocation branches, or the report silently drops
half the money.

```groovy
Or or = new Or()
agencies.each { agency ->
    or.add(eq("monInstruments.paymentInvoices.invoice.cf_itemGroup", agency))   // fees
    or.add(eq("monInstruments.trusts.restitution.cf_itemGroup", agency))        // restitution
}
where.add(or)
```

Pay plans have their own pair:

```groovy
orAgency.add(eq("invoices.cf_itemGroup", itemGroup))
orAgency.add(eq("payPlanRestitutions.restitution.cf_itemGroup", itemGroup))
```

## Date ranges

The amount fields hang off timestamps, so an inclusive upper bound loses the last day.

```groovy
def endPlusOne = DateUtil.addDays(_EndDate, 1)
where.addGreaterThanOrEquals("dateCreated", _StartDate)
where.addLessThan("dateCreated", endPlusOne)
```

`addDateRange(path, start, end)` exists and is fine where the semantics suit — but check
whether it is inclusive on the upper bound before trusting it with a month boundary.

## `collect()` with SpEL filters

Filters go in brackets, parameters are `#p1`, `#p2`, passed positionally after the string.

```groovy
pp.collect("installments[balance > 0 && dateDue >= #p1 && dateDue < #p2]", rangeStart, rangeEndExclusive)
orgUnit.collect("childPersons[role == 'TREAS' && status == true]")?.first()
party.collect("invoices[cf_itemGroup == #p1].dueDate", itemGroup)
case.collect("otherCaseNumbers[type == 'CRT' && active == true]")
```

**The trap.** A `collect()` whose filter ends without a trailing property returned **zero
rows** in practice:

```groovy
party.collect("invoices[cf_itemGroup == #p1]")          // returned nothing
party.collect("invoices[cf_itemGroup == #p1].dueDate")  // works
```

An earlier cut of the Past Due report read Invoice and Restitution objects out of the first
form and filtered them in Groovy on `.status` and `.payPlan`. It produced no obligation rows
at all. Append a property, or fetch by id instead — and do not reintroduce the object-returning
form without proving it works first.

## Raw SQL for aggregates

`DomainObject.querySQL` is the escape hatch when the criteria API cannot express a
`SUM ... GROUP BY`. Table names are `t` + the entity name.

```groovy
def invAllocated = DomainObject.querySQL(
  "SELECT SUM(p.amountCents)/100, i.cf_name FROM tMonInstrument m " +
  "LEFT JOIN tPaymentInvoice p ON m.id = p.monInstrument_id " +
  "LEFT JOIN tInvoice i ON p.invoice_id = i.id " +
  "WHERE ... GROUP BY i.cf_name")

def restAllocated = DomainObject.querySQL(
  "SELECT SUM(tt.amountCents)/100, r.cf_name FROM tMonInstrument m " +
  "LEFT JOIN tTrust t ON m.id = t.monInstrument_id " +
  "LEFT JOIN tRestitution r ON t.restitution_id = r.id " +
  "LEFT JOIN tTrustTransaction tt ON tt.trust_id = t.id " +
  "WHERE ... GROUP BY r.cf_name")
```

To reach the payer and the case from an instrument, the corpus uses this chain:

```sql
LEFT JOIN tPayment tp ON m.payment_id = tp.id
LEFT JOIN tParty    pa ON tp.payor_id  = pa.id
LEFT JOIN tCase     c  ON pa.case_id   = c.id
```

Rows come back as `List`, indexed positionally — `q[0]`, `q[1]`. Re-fetch objects by id for
detail rows: `DomainObject.get(MonInstrument, q[0].toLong())`.

Note the two queries mirror the two branches again. One `querySQL` over fees only is the same
under-reporting bug in a different costume.

Voucher ranges are string comparisons, because voucher numbers carry a prefix:

```groovy
"SELECT id FROM tVoucher WHERE voucherNumber >= '${fromVoucher}' AND voucherNumber <= '${toVoucher}'"
```

## Helpers in scope

| Call | Does |
|---|---|
| `NumberUtil.format$(n)` | currency string |
| `NumberUtil.format(n)` | plain number formatting |
| `LookupItem.getLabel('LIST', code)` | code → label |
| `DateUtil.addDays(date, n)` | the end-exclusive idiom |
| `DomainObject.find` / `.get` / `.querySQL` | the query API |
| `DirOrgUnitCore.getByCodeOrId(code)` | county / agency org unit |
| `logger.debug "..."` | shows in the rule log; use it while building |

## Rows out

Financial reports are usually one flat `List<Map>` with a `section` or type discriminator,
because eSeries hands the template a single `_data` collection. Seed every key so no column
can print `null`, make every value a String, and pre-format money and dates in the rule.

Sorting is the rule's job, not the template's — sort `_data` before assigning it.

```groovy
_data = result.sort { a, b ->
    def d = a.paymentDate <=> b.paymentDate
    if (d != 0) return d
    return a.receiptNumber <=> b.receiptNumber
}
```

## De-duplication

Several patterns in the corpus keep a `Set` of keys seen, because a payment reached through
two branches, or a disbursement receipt aggregating several defendants, will otherwise emit
the same row twice.

```groovy
def uniqueKeys = [] as Set
def key = "${receiptNumber}|${caseNumber}|${amount}"
if (uniqueKeys.add(key)) { result << row }
```
