# The financial reports in the corpus, and what each one teaches

Every report below was read. Use it to find precedent: match the shape of your task to a
report that already solves it, and copy its idioms rather than inventing.

Paths are relative to the corpus root — `Projects/<Client>/` in this workspace (older setups: `~/JaspersoftWorkspace/MyReports/` on that
machine). Where several versions exist, the one named is the latest.

## Payments and collections

| Report | Latest rule | What it teaches |
|---|---|---|
| **Payments Report** | `Payments_Report_V4.groovy` | The canonical both-branches walk. `Or` over invoice + restitution item groups, voided-receipt exclusion by dotted receipt base, overpayment kept separate from allocated, multi-key sort in the rule |
| **Payments by Obligation Type** | `PaymentsbyObligationDataset.groovy` | `querySQL` for `SUM ... GROUP BY`, run **twice** — once per branch — then re-fetch objects by id for the detail rows. Reference-number fallback: `checkNumber` then `creditAuthorization.externalAuthorizationId` |
| **FEES_COLLECTED_DATASET** | `FEES_COLLECTED_DATASET_V7_Receipt.groovy` | The `OVER_PAYMENT` trust transaction. Payment Details on screen can include amounts with no matching `PaymentInvoice`; V7 exists to reconcile that. Also reversal-receipt lookup by `originalReceipt.receiptNumber` |
| **Restitution and DA Fees Collected** | `Restitution andDAFeesCollected.groovy` | `sel()` projecting *through* relations — `sel("party.payments.id")` from Invoice, `sel("payorParties.payments.id")` from Restitution. A second way to hit both branches |
| **Financial History Detail** | `Financial_Obligation_Payment_History_Report_V3.groovy` | Person-rooted rather than payment-rooted: `person.parties.payments` and `person.cases.vouchers` |
| **DA Supervision Payment Summary** | `DASupervisionPaymentSummary.groovy` | Balance splits — `addGreaterThan("balanceCents", 0l)` vs `addEquals(..., 0l)`, with `addIn("cf_itemGroup", ['DADIV','SUPER'])` |

## Obligations and pay plans

| Report | Latest rule | What it teaches |
|---|---|---|
| **Past Due Financial Obligations** | `PastDueFinancialObligations_V3_MergedPayPlans.groovy` | The best-documented rule in the corpus. Why summing `PayPlan.balance` double counts, why overdue installments can be summed, and the `collect()` filter that returns zero rows without a trailing property |
| **Past Due PayPlan Payments** | `PastDuePayPlanPayments.groovy` | The plain pay-plan case: ACTIVE status, agency `Or` over `invoices` and `payPlanRestitutions.restitution`, installment date range |
| **Payment Schedule Report** | *none — unbuilt* | A `.jrxml` with no rule. Its field list is the contract if anyone builds it: `nextPmt`, `nextPmtDate`, `balanceOwed`, `dueSchedule`, `numberPaymentsTotal`, `paymentAmt`, `schDate` |

## Annual and aggregate

| Report | Latest rule | What it teaches |
|---|---|---|
| **Annual Report by Collecting Agency** | `Annual_Report_by_Collecting_Agency_V4.groovy` | The assessment side: `Charge.fines` with `amount` in **dollars**, classification by substring-matching `assessmentGroup.name`, `Charge.cf_restitutions`, per-metric dedupe sets, county aggregation with `withDefault` |
| **Bogus Check Annual Report** | *same rule* | Its `.jrxml` consumes exactly the Annual Report's aggregates. **One rule feeds two templates** — change the rule and check both |

## Receipts, vouchers, checks

| Report | Latest rule | What it teaches |
|---|---|---|
| **Receipt** | `ReceiptBR_V18_UNAPPROVED_Overpayments.groovy` (V17 is the last approved) | The most branched rule here: payment vs disbursement vs reversal receipts, non-monetary items, payor address assembly, signature rules, an explicit overpayment kill switch. Note the file names carry approval state |
| **Voucher Payee Statement with Address** | `Voucher Payee Statement V8_Remove_Voided.groovy` | `instrumentItems → voucher`, filtering to ACTIVE items to drop voided vouchers, payee address from the county org unit via `CAREF` attribute |
| **Cleveland County Voucher Print** / **Voucher Receipt Cherokee County** | same-named `.groovy` | Voucher number ranges are **string** comparisons because of the prefix. Raw SQL for the id list, then `addIn("id", ids)` |
| **Checks** (`Checks/`, per district D08–D24) | `Checks/check_general.groovy` | One rule, a template per district. Cents formatted with integer arithmetic to avoid float error; amount-in-words; routing/account/treasurer from the org unit |
| **Official Depository Ticket** | `Official_Depository_Ticket_Filtered_County_V5.groovy` | Deposits: org unit, `ACCOUNT_NUMBER` attribute, `childPersons[role == 'TREAS' && status == true]`, and shared-depository counties where the query widens but the selected county still drives the printed identity |

## Not financial, but nearby

**VOCA** (`OKDAC Reports/VOCA/`, and `New Mexico Reports/VOCA.groovy`) is victim-services
statistics over `Ce_VocaVictimization`, `Ce_VocaSpecialClassification`, `Ce_VocaService`. No
money. Useful only for `LookupList.get("LIST").activeNowItems` and `addDayRange`.

**Yakima** and **New Mexico Reports** are other clients. Same platform idioms, different
entities and lookup lists — do not copy their item-group codes.

## Reading the corpus safely

- **The highest version number is not reliably live.** `ReceiptBR_V18` is explicitly marked
  UNAPPROVED, with V17 named as the deployable one. File names carry state; read the header
  before assuming.
- Header comments in the newer rules are worth more than the code. They record the defect that
  caused each change, often with the case number that proved it.
- `logger.debug` lines left in place show what the author could not see and had to check. They
  point at the fragile parts.
