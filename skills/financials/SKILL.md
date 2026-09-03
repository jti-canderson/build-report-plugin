---
name: financials
description: >-
  The eSeries (Sustain / Symphony) financial data model, and how to get money numbers out
  correctly — payments, receipts, allocations to fees and restitution, obligations, balances,
  pay plans, overpayments, deposits, vouchers and disbursements. Use whenever a task involves
  an amount: "report on payments collected", "why doesn't this total match the Financials
  screen", "past due obligations", "receipt shows the wrong amount", or any column named
  Amount, Paid, Balance, Allocated, Collected or Past Due. Reach for it before writing the
  query, not after: a total can look plausible and be quietly incomplete — a payment allocates
  down two branches plus an assessment side, some amount fields are integer cents and some are
  already dollars, overpayments have two representations, and reversed receipts carry no
  instruments of their own. Miss any of these and the number is wrong with no error. Pairs
  with `jasper-reports` for report work; this is the domain knowledge, that is the mechanics.
---

# eSeries financials

Money in this system is not one table you can sum. It is a small graph, and the shape of the
graph is why financial reports go wrong.

## The one thing to get right: there are two branches

A payment splits into **money instruments**, and each instrument allocates down one of two
separate paths:

```
Payment
  payerName, paymentDate, totalAmountCents, paymentReceipt
  └── monInstruments  (MonInstrument)
        instrumentType (lookup MON_INSTRUMENT_TYPE), amount, checkNumber,
        creditAuthorization.externalAuthorizationId, receipt.receiptNumber,
        checkOverPaymentAmountCents
        │
        ├── paymentInvoices  (PaymentInvoice)      ← FEES, COSTS, ASSESSMENTS
        │     amountCents
        │     └── invoice  (Invoice)
        │           cf_itemGroup, cf_name, balanceCents, dueDate, status, payPlan
        │
        └── trusts  (Trust)                        ← RESTITUTION
              └── trustTransactions  (TrustTransaction)
                    amountCents, trustTransactionType, voucher
              └── restitution  (Restitution)
                    cf_itemGroup, cf_name, amountCents, paidCents
```

**A report that walks only one branch under-reports and does not error.** Fees come through
`paymentInvoices → invoice`. Restitution comes through `trusts → trustTransactions`, with the
obligation itself on `trust.restitution`. Any filter on collecting agency or item group has
to be applied to *both*, which is why real reports do this:

```groovy
Or or = new Or()
agencies.each { agency ->
    or.add(eq("monInstruments.paymentInvoices.invoice.cf_itemGroup", agency))
    or.add(eq("monInstruments.trusts.restitution.cf_itemGroup", agency))
}
where.add(or)
```

### There is also a third path, on the assessment side

The branches above are how money was **collected**. What was **assessed** hangs off the charge,
and it is a different graph:

```
Charge
  chargeDate, case
  ├── fines  (OrderItemFine)      ← what was assessed
  │     cf_itemGroup, amount (DOLLARS), assessmentGroup.name, case
  └── cf_restitutions             ← restitution ordered on this charge
        paidCents, amount
```

So restitution is reachable **three** ways, and they answer different questions:
`trust.restitution` (what a payment applied to), `charge.cf_restitutions` (what was ordered on
a charge), and `Restitution.payorParties.payments` (who is paying it). Pick by question, and
say in the handoff which one a column came from.

**Assessment groups are matched by substring, not by code.** The Annual Report classifies a
fine by lower-casing `assessmentGroup.name` and testing `contains("bogus check")`,
`contains("check amt")`, `contains("merchant fee")`, `contains("ck da fee")`. That is how the
corpus does it, and it means **renaming an assessment group silently changes the report's
numbers**. Flag it whenever you touch such a report; do not quietly "improve" the matching.

Two convenience collections exist on the instrument and are worth using:
`sortedPaymentInvoices` and `sortedTrustTransactions`. Both need `.flatten()` when reached
through `monInstruments`.

## Money comes in two conventions, and mixing them is a 100x error

**Fields ending `Cents` hold an integer number of cents.** Divide by `100.0`:
`amountCents`, `paidCents`, `balanceCents`, `totalAmountCents`, `pastDueAmountCents`,
`checkOverPaymentAmountCents`.

**Fields named `amount`, `balance`, `paid` — with no `Cents` — are already dollars.** Never
divide these. Nothing in the corpus does:

| Dollars already | Cents |
|---|---|
| `MonInstrument.amount` | `MonInstrument.checkOverPaymentAmountCents` |
| `OrderItemFine.amount` (a charge's fine) | `PaymentInvoice.amountCents` |
| `Invoice.amount`, `Invoice.balance` | `Invoice.balanceCents` |
| `PayPlan.balance`, installment `balance` | installment `pastDueAmountCents` |
| `Restitution.amount` | `Restitution.paidCents`, `TrustTransaction.amountCents` |

Note `Invoice` exposes **both** `balance` (dollars) and `balanceCents`. Check the suffix every
time; the two differ by 100 and both look like money.

```groovy
def dollars = (thing?.amountCents ?: 0) / 100.0     // cents field: /100.0, not /100
def alsoDollars = thing?.amount ?: 0.0              // no suffix: use as-is
```

Use `100.0`. Integer division on a Long truncates the pennies silently.

Cents comparisons in criteria want a Long literal: `addGreaterThan("balanceCents", 0l)`.

**To render cents as a string without float error**, do it with integer arithmetic rather than
dividing into a Double:

```groovy
"${(amountCents / 100) as Long}.${String.format('%02d', Math.abs(amountCents % 100))}"
```

## Amount Paid is not Total Allocated

This distinction has caused real defects, so state which one a column means before writing it.

- **Amount paid** — what the payer handed over. `MonInstrument.amount`, or the payment's
  `totalAmountCents`. **Includes any overpayment.**
- **Total allocated** — what was applied to obligations. The sum of `PaymentInvoice.amountCents`
  plus `TrustTransaction.amountCents`. **Excludes the overpayment**, because an overpayment was
  never applied to anything.

So the two legitimately differ, and the difference is the overpayment. A report showing both
must not "fix" the gap.

**Overpayment has two separate representations, and reports need both.**

1. **On the instrument** — `checkOverPaymentAmountCents`, which is a **collection**, not a
   scalar:
   ```groovy
   def op = mon?.checkOverPaymentAmountCents?.find { it != null && it > 0 }
   ```
2. **As an explicit trust transaction** — `trustTransactionType == 'OVER_PAYMENT'`. These
   amounts appear in Payment Details on screen but have **no matching `PaymentInvoice`**, so a
   report that sums only the invoice branch is short by exactly the overpayment and cannot be
   reconciled against the screen. FEES_COLLECTED_DATASET V7 exists largely to fix this.

Exclude voided receipts when counting either. A payment that was voided did not overpay
anything, and counting it contradicts every other report.

## Obligations, balances and pay plans

**Invoice** is a fee obligation; **Restitution** is a restitution obligation. Both carry
`cf_itemGroup` (the collecting agency) and `cf_name` (the obligation type shown to users).

**Pay plans** are the trap. `PayPlan.status == 'ACTIVE'`, with `installments` carrying
`dateDue`, `balance` and `pastDueAmountCents`. Restitution obligations attach through
`payPlanRestitutions.restitution`.

**Never total a balance by summing `PayPlan.balance` across plans.** One case can carry two
plans covering overlapping obligations — a plan for the whole amount and a second plan for a
restitution already inside it — so summing double counts. Overdue *installments* do not
overlap, so sum those instead. That is what matches the case's own Past Due badge.

## Receipts, reversals and voids

A receipt is the printed record of a transaction, not the transaction. `Receipt.receiptType`
and `transactionTypesLabel` tell you which kind, and it matters:

- a **payment** receipt walks its instruments normally
- a **disbursement** receipt aggregates payments from several defendants across cases, so the
  same payment can appear more than once and needs de-duplicating
- a **reversal** or **void** carries `originalReceipt`, and **has no instruments of its own** —
  walk `originalReceipt.monInstruments` instead
- a receipt can also carry **non-monetary** items (`nonMonetarySetup.code`), such as credit for
  community service. A receipt with no instruments, no non-monetaries, and an `originalReceipt`
  is a reversal.

**Reversals are the most-handled case in the corpus** — `originalReceipt` appears over a
hundred times. Two things to know:

**Receipt numbers carry a dotted suffix for reversals.** The base receipt is everything before
the dot, and that is how reports decide whether a payment was voided:

```groovy
def base = sp.receipt.receiptNumber.split("\\.")[0]
if (sp.receipt.receiptType.toString() == "VOID") { voidedReceipts << base }
// ... later
if (voidedReceipts.contains(base)) { /* skip: this payment was reversed */ }
```

Note `receiptNumber` and `fullReceiptNumber` are different properties; reversal comparisons in
the corpus use both, so match whichever the report you are modelling on uses.

**Two types mean reversed:** `receiptType in ['VOID', 'PAYMENT_REVERSAL']`. To find whether a
receipt was later reversed, query for receipts pointing back at it:

```groovy
def w = new Where()
w.addIn("originalReceipt.receiptNumber", [receiptNumber])
def reversals = DomainObject.find(Receipt.class, w) ?: []
```

A report that ignores reversals overstates collections, and it will not tie to the Financials
screen.

## Vouchers and disbursements

**Vouchers** are the disbursement instrument. The link from a payment runs through
**`instrumentItems`**:

```groovy
instrument.instrumentItems?.voucher?.each { v -> ... }
v.trustTransactions.each { tt -> def payment = tt.trust.monInstrument.payment }
```

Also reachable as `monInstruments.allReceipts.vouchers`,
`monInstruments.trusts.trustTransactions.voucher`, and `person.cases.vouchers`.

Payee fields sit on the voucher itself: `name`, `payeeAddress1`, `cityStateZip`.

**Filter to ACTIVE `instrumentItems`.** A voucher whose items are not active is voided, and the
corpus skips it outright.

**Voucher numbers are strings with a prefix**, so a from/to range is a string comparison:

```sql
SELECT id FROM tVoucher WHERE voucherNumber >= '${fromVoucher}' AND voucherNumber <= '${toVoucher}'
```

**Checks** are a separate family of templates, one per district, all fed by one rule. They need
`amountCents`, `amountInWords`, `checkNumber`, `routingNumber`, `bankInfo`, `accountNumber`,
the payee block, and the district's `treasurer` and `districtAttorney`. The amount-in-words
conversion renders as `"<Words> Dollars And <Cents>/100"`.

**Filter null instruments before adding them to a `TreeSet`.** Both a check batch's
`sortedPMInstruments` and an explicit id list can contain a null (for example, when an id no
longer resolves). `TreeSet.addAll` then fails before the report loop with
`TreeMap.compare: Cannot invoke Comparable.compareTo(Object) because k1 is null`. This stack
shape means the set element itself is null; a broken comparison property would include the
domain object's `compareTo` frame. Guard both input paths:

```groovy
def valid = (candidates ?: []).findAll { it != null }
instruments.addAll(valid)
```

## Deposits and the county org unit

Deposit tickets resolve the receiving bank from the county's org unit:

```groovy
DirOrgUnitCore.getByCodeOrId(county)                                  // the org unit
  .attributes.find { it.attributeType == 'ACCOUNT_NUMBER' }?.value    // account number
  .collect("childPersons[role == 'TREAS' && status == true]")?.first() // treasurer
```

Counties can share a depository. One county's treasurer may bank another's funds for specific
item groups, in which case the deposit query widens across those counties while the *selected*
county still drives the org unit, account number, treasurer and printed name. Confirm whether
a site has such an arrangement before assuming one county means one county.

## Lookups you will need

| List | Holds |
|---|---|
| `MON_INSTRUMENT_TYPE` | cash, check, card, money order |
| `CASE_LOCATION` | county / location labels |
| `C_FIN_ITEM_GROUP` | collecting agency / item group (site-specific, `C_` prefixed) |

Resolve with `LookupItem.getLabel('LIST_NAME', code)`. A raw code reaching the page is a bug.

## Querying

See `references/queries.md` for the full patterns. The essentials:

**Find ids, then get objects.** `DomainObject.find` with `sel('id')` returns ids; fetch each
one. Multiple `Where` objects pass as varargs and are ANDed.

```groovy
def ids = DomainObject.find(Payment.class, sel('id'), whereDate, whereAgency)
ids.each { def p = Payment.get(it) /* ... */ }
```

**Date ranges are end-exclusive.** These fields are timestamps, so a payment at 14:00 on the
end date fails a `<=` against midnight. Add a day and use `<`:

```groovy
def endPlusOne = DateUtil.addDays(_EndDate, 1)
where.addGreaterThanOrEquals("dateCreated", _StartDate)
where.addLessThan("dateCreated", endPlusOne)
```

**`querySQL` exists** for aggregates the criteria API cannot express. Table names are `t` +
entity name (`tMonInstrument`, `tPaymentInvoice`, `tInvoice`, `tTrust`, `tRestitution`,
`tTrustTransaction`, `tVoucher`). Use it for `SUM ... GROUP BY`, then re-fetch objects by id
for the detail rows.

## Parameters arrive messy

A multi-select parameter arrives in **three** different shapes across the corpus, and reports
handle all three:

1. a plain **String** when one value is picked
2. a **Collection** when the control returns a list
3. a **String with literal brackets** — `"[BGCHK, SUPER]"` — which needs the brackets stripped
   before splitting

```groovy
def codes = (_County instanceof Collection)
    ? _County.findAll { it != null }.collect { it.toString() }
    : (_County ? [_County.toString()] : [])

// the bracketed form
def raw = (_CollectingAgency == null) ? "" : _CollectingAgency.toString().trim()
if (raw.startsWith("[")) raw = raw.substring(1)
if (raw.endsWith("]"))   raw = raw.substring(0, raw.length() - 1)
def agencies = raw.split(",").collect { it.trim().toUpperCase() }.findAll { it } as Set
```

All parameters arrive as Strings whatever class the rule declares.

**Item group codes are site-specific**, `C_` lookup values. Ones in the corpus: `BGCHK` (bogus
check), `REST` (restitution), `DADIV` (DA diversion), `SUPER` (supervision). Never hardcode a
set without checking the site's `C_FIN_ITEM_GROUP` list.

### A traversal through a to-many relation returns a Collection

Even for a scalar property. `cse.caseNumber` is a String on one case and a Collection when
reached through a relation, so the corpus guards constantly:

```groovy
def caseNum = (cse?.caseNumber instanceof Collection) ? cse.caseNumber.first() : cse?.caseNumber
```

Assume any property you reached by walking a collection is itself a collection until proven
otherwise. This is a frequent cause of a column printing `[1234]` instead of `1234`.

### Counting once per metric, not once overall

When one charge or payment feeds several aggregates, a single "seen" set is wrong — it
suppresses legitimate contributions to the other metrics. The Annual Report keeps **one dedupe
set per aggregate** (`countedBogusCharges`, `countedCollectedCharges`, `countedPaidCharges`,
`countedFeePayments`), each guarding its own total.

## The one question to ask about every money column

Before writing a single amount, settle which measure it means. These are three different
numbers and the requester usually has not distinguished them:

1. **Assessed** — what was ordered. `Charge.fines[].amount`, `Invoice.amount`,
   `Restitution.amount`.
2. **Paid** — what the payer handed over. `MonInstrument.amount`,
   `Payment.totalAmountCents`. Includes overpayment.
3. **Allocated / collected** — what was applied to obligations. `PaymentInvoice.amountCents`
   plus `TrustTransaction.amountCents`, or `Restitution.paidCents`. Excludes overpayment.

A column labelled just "Amount" is ambiguous, and picking wrong produces a report that looks
right and reconciles to nothing. Ask, in one line, naming the three options — and if the answer
is slow, build it with the measure the comparable report in the corpus used and label the
assumption.

Also settle **which environment**, because item group codes and `C_`-prefixed lookup lists are
per-environment. `BGCHK` existing on one site says nothing about another.

## Prove the number before you ship it

A financial total is either right or it is a liability. The case's own **Financials** screen
and its **Past Due** badge are ground truth you can reach without database access — ask for
the case printed to PDF and reconcile against it, obligation by obligation.

Say which figures you reconciled and which you did not. "The totals look reasonable" is not
verification.

## Adversarial review

A number that is quietly short is the characteristic failure of this whole model, and nothing
announces it — the report renders, the total looks plausible, and it reconciles to nothing.
Reconciling against the Financials screen is the real check and comes first. Where you cannot
reconcile — an aggregate across cases, a figure no screen displays — put one critic agent on it
instead. One, not a fan-out.

It asks the task questions before the money questions:

1. **Did this do what was actually asked?** Read the user's own words, not the restatement of
   them. Name anything added that was not requested, and anything requested that was quietly
   narrowed or dropped.
2. **Is the problem actually fixed?** Name the original symptom, then the specific mechanism
   that now prevents it. If the mechanism cannot be named, it is not fixed.
3. **Where is this guessing?** Mark every load-bearing claim *seen working* or *assumed*.
4. **What one question would settle the biggest guess fastest?** One question asked now beats
   three speculative rounds — and here it is usually "Assessed, Paid, or Allocated?", which is
   far cheaper to ask than to reverse-engineer.

Then the money:

- **Which of the three measures is this, and does the column label match it?** Assessed, Paid
  and Allocated are three different numbers; a column called "Amount" has not chosen one.
- **Does it walk both branches, plus the assessment-side third path?** A query down one branch
  under-reports with no error.
- **Which convention is each field — integer cents, or already dollars — and where do they
  meet?** Mixing them is a 100x error that still renders cleanly.
- **Is overpayment in or out, and is that what was asked?** Paid includes it, Allocated does not.
- **What happens to reversed and voided receipts?** They carry no instruments of their own.
- **Where can the same money be counted twice?** Two active plans on a case can cover the same
  obligations, and a traversal through a to-many returns a Collection, not a scalar.
- **Which figures were reconciled against the case screen, and which were not?** "The totals
  look reasonable" is not verification — and neither is a critic's approval.

Every answer is a data state — "case 26-23, two plans covering the same $148 restitution, the
total reads high" — never an opinion. Report what the critic broke *and* what it tried and could
not break, and turn any guess it could not resolve into a question for the user rather than a
decision made quietly.

## Finding precedent

`references/report-inventory.md` catalogues every financial report in the corpus and what each
one demonstrates — which to copy for a collections report, an aggregate, a voucher, a deposit
ticket. Start there rather than designing from scratch; most shapes are already solved.

Two warnings from that review. **The highest version number is not reliably live** — one
receipt rule is explicitly marked UNAPPROVED with an earlier version named as deployable. And
**one rule can feed two templates**, so changing it changes both reports.

## Related skills

- `jasper-reports` — building the report that presents these numbers
- `report-deployment` — putting it into an environment
- `data-dictionary` — confirming a field exists and its exact type before you traverse it
