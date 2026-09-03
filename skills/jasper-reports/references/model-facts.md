# Model facts — things already established, do not re-derive

Every entry here cost real tokens to find once. Reading this file is free. **Check it before
searching the SDK, the Data Dictionary or the corpus for a model question.**

Each fact carries how it was established and on which environment, because a fact is only
true of the environment that produced it.

---

## Users, roles and logins

*Established 2026-09-02 against `ecourt-sdk-local-2026-09-02.jar` + `DataDictionary-local-2026-09-02.xlsx`.
Cost ~$36 of agent time. Do not repeat it.*

### `com.sustain.security.model.LoginAudit` is UNUSABLE — do not start here

The name is the obvious lead and it is a dead end.

- The class file is 221 bytes. `javap -p` prints a default constructor and nothing else.
- It does **not** extend `DomainObject`, so `DomainObject.find(LoginAudit.class, ...)` has
  nothing to find and no field to range on.
- Absent from the Data Dictionary's 293 entities; absent from all corpus rules.
- `User.getLoginAudit()` compiles to `aconst_null / areturn`, and `loginAudit` is the one
  property whose type cell the Data Dictionary leaves blank.

### `User.lastLoginDate` is also wrong — twice over

- Not persisted: `getLastLoginDate()` compiles to `aconst_null / areturn`, and it sits in
  the Data Dictionary's derived-getter block, not the persisted block. It cannot go in a
  `Where`.
- Semantically wrong anyway: it is the *last* login, so anyone who logged in inside a date
  range and again afterwards is silently excluded.

### `com.sustain.security.model.SecurityLog` is the only login-shaped entity

Real, field-backed: `date`, `username`, `checkType`, `server`, `message`.

Three cautions:

- **Not proven searchable.** It is not a Data Dictionary entity and no corpus rule has ever
  queried it. Whether `DomainObject.find` accepts it is unverified — probe, do not assume.
- **One row per security CHECK, not per login.** `SecurityLog$CheckType` has 26 constants,
  mostly per-request (URL, TASK, ACL, CSRF…). The login ones are `LOGIN_SUCCESS`,
  `LOGIN_FAILURE`, `TWO_FACTOR_SUCCESS`, `TWO_FACTOR_FAILURE`, `LOG_OUT`. **Filter in the
  `Where`**, never in Groovy after loading, or you pull the whole table.
- **Purged on a schedule.** `SysProperty` carries `SECURITY_LOG_CLEANUP_INTERVAL_MINUTES`.
  A window older than retention returns zero rows with no error. Report the row count and
  the oldest row seen so an empty result is distinguishable from a bad date range.
- It has **no** `remoteAddress` / `remoteHost` / IP field. `AuditLog` and `AccessLog` do.

### Role = `User.securityGroup.name`

- `securityGroup` is a **scalar** field on `User` (not a Set), inverse `SecurityGroup.users`.
  Many-users-to-one-group, so grouping on it **cannot duplicate a user**.
- It has no Not Null flag — **coalesce the null** (`?: "(no security group)"`), or those
  users vanish from a by-role report.
- Open question, worth one look before building: are the group *names* job roles
  ("Assistant District Attorney") or permission tiers ("Read Only")? If the latter, a
  "by role" report answers a different question than the one asked.

### Do NOT use `User.get(String)` to look a user up by username

Its body in the SDK is `aconst_null / areturn`. Nothing establishes what key it takes.
`loadUserByUsername` and `getByUsernames` are equally stripped.

Use the evidenced join instead — one query, no static helper:

```groovy
def usersByLogin = [:]
for (u in (DomainObject.find(User.class, new Where()) ?: [])) {
    def k = u.username
    if (k != null) usersByLogin[k.toString().toLowerCase()] = u
}
```

### `AuditLog` — the near-miss

`com.sustain.audit.model.AuditLog` (table `tAuditLog`) has real fields: `username`, `userId`,
`category`, `subCategory`, `timeStamp`, `txId`, `remoteAddress`, `remoteHost`, `serverName`.
It is the shape you would want. But grepping all 1703 SDK classes for the literal `LOGIN`
matched only `SecurityLog$CheckType` and `SysProperty` — **no category constant naming a
login exists**, so there is no evidence AuditLog records logins at all.

---

## General, environment-independent

- **The `Where` API has no OR.** Two searches and a merge, or an `Or` object added to the
  `Where` where the corpus does that. See `Payments_Report_V4.groovy`.
- **A null date bound matches NOTHING** rather than being ignored. Default both bounds
  explicitly or the report silently empties.
- **Resolve classes by name off a known classloader**, never as a class literal — a corpus
  rule died on `Case.class.name` returning null in this engine.
- **A clean Compile proves only that classes resolve and syntax is valid.** Groovy is
  dynamically typed, so `obj.doesNotExist` compiles fine and yields null at run time — an
  empty column, not an error.

---

## Case / Charge — type fields, and the "date added" trap

*Established 2026-09-03 against `ecourt-sdk-local-2026-09-02.jar`
(`com/sustain/cases/model/Case.class`, `Charge.class`, `com/sustain/DomainObject.class`),
cross-checked against the corpus. No Data Dictionary for this environment was on hand; one
claim below leans on `User_Activity_Audit_Report_V2`'s header, which cites
`DataDictionary-local-2026-08-20.xlsx`.*

- **`Case.caseType`** and **`Charge.chargeType`** are real, plain `String` fields with real
  getters/setters (bytecode reads/writes the field, not a stub). Each has a `*Label` getter
  for display (`getCaseTypeLabel()`, `getChargeTypeLabel()`) — lookup-backed, so filter on the
  bare code, display the label. `caseType` is independently attested in production:
  `addEquals("monInstruments.receipt.cases.caseType", t)` (`references/criteria-api.md`).

- **`dateCreated` (declared on `DomainObject`, inherited by every entity including `Charge`)
  is a getter trap, same family as `User.lastLoginDate`.** `DomainObject.getDateCreated()`
  compiles to `aconst_null / areturn` in this SDK jar — a stub — and `Charge` does not
  override it. So **`someEntity.dateCreated` read as a Groovy property returns null**, even
  though the field is real. Do not display it, do not test it with `!= null` after a fetch.
  **But it IS a real, stored, filterable column** — `User_Activity_Audit_Report_V2` cites the
  Data Dictionary confirming `dateCreated` present on all 293 entities and uses
  `addDayRange("dateCreated", from, to)` in a `Where` successfully. Criteria queries resolve
  the property against the ORM mapping, not the compiled getter, so the trap is
  Groovy-property-read only. **Use `dateCreated` in a `Where`/`addDateRange` to filter "when
  was this record added"; never read it back after the fetch.**

- **`Charge.chargeDate`** (offense date) and **`Charge.dateFiled`** (filed with the court)
  both have real getters — bytecode confirmed, not stubs. Neither means "date added": a
  request for "the date [a charge] was added" maps to `dateCreated` (the record's own
  created-timestamp), not `chargeDate` or `dateFiled`. If a report needs to *display* an
  added-on date, `dateCreated` cannot supply it (see above) — surface `dateFiled` instead and
  say so; don't silently substitute one date concept for another.

- **Two `addX` calls on the same nested collection-path prefix, in one `Where`, constrain the
  SAME element of that collection** (not an independent per-condition join). Attested in
  production: `OKDAC Reports/Checks/check_general_V3_PayorCourtAccount.groovy` —
  `w.addEquals('attributes.attributeType', 'CAREF'); w.addEquals('attributes.value', caref)`
  against `DirOrgUnit`, used to find the one attribute that is both type CAREF and a specific
  value; it would silently mis-resolve counties if the two conditions matched independent rows,
  and it is load-bearing there. Lean on this whenever a report needs "a nested-collection row
  that satisfies two conditions at once" (e.g. a charge whose `chargeType` AND `dateCreated`
  both match) instead of restructuring into two queries and a merge.
  **A second, independent attestation on the `parties.charges` prefix specifically, using
  RANGE operators** (2026-09-03): `Yakima/Pros/Jasper/FinalDispo.groovy` does
  `addGreaterThanOrEquals("parties.charges.dispositionDate", start)` +
  `addLessThan("parties.charges.dispositionDate", throughPlusOne)` in one `Where` — which
  would be visibly nonsense (a case with charge A disposed 2010 and charge B disposed 2030
  matching a 2020 window) if the two bounds bound independent join aliases, and it has been
  running in production. And `Performance_Based_Budgeting_Reports.groovy` uses
  `addDayRange("dateCreated", start, DateUtil.addDays(end, 1))` — the same-element property
  holds for range operators, not only `addEquals`. Treat two conditions on one collection
  prefix as constraining the same element; a single `addDayRange` (both bounds in one call)
  resolves its alias once, so it is the safest form.
  **`addDayRange` end bound is not whole-day-inclusive on its own** — the corpus idiom is to
  pass `end + 1 day` (`throughDatePlusOneDate` in the Voucher reports;
  `DateUtil.addDays(_endDate, 1)` in Performance_Based_Budgeting on `dateCreated`).
  Truncating the end *down* to midnight silently drops everything added on the last day.

---

## How to add to this file

When a model question costs more than a couple of minutes to answer, write the answer here
with its evidence and its environment. The next report gets it for free, and the file is the
cheapest thing in the pipeline to read.
