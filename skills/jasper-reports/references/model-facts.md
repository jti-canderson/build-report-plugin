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

- **`Case.caseType`** and **`Charge.chargeType`** are real, plain `String` fields, and both
  are attested filterable in production criteria.

  **CORRECTION 2026-09-08 — the "real getter, not a stub" half of this was wrong.**
  `Case` declares the `caseType` *field*, but `getCaseType()` is declared on
  **`CaseComponent`**, the parent, and its body is `aconst_null / areturn` in BOTH SDK jars
  (local 09-02 and eProsecutorBaselineQA 09-03). The original claim came from grepping one
  class's bytecode for the field and assuming the getter beside it; javap prints DECLARED
  members only, so the real getter was never in the output being read.

  This is a third pattern, and the one that makes a `stripped` body carry the least
  information of all: **when a getter is declared on a parent that has no such field, the
  SDK export has nothing to emit, so `stripped` is the expected result and says nothing
  whatever about runtime.** Do not read `c.caseType` as broken on this evidence; do not
  read it as proven either. `scripts/sdk_fields.py` now prints the field owner and the
  getter owner in separate columns precisely so this pattern is visible rather than
  collapsed into one misleading verdict. Each has a `*Label` getter
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

## Contact details, custom-field prefixes, and the WinAnsi trap

*Established 2026-09-03 while building `Case Summary Report EPQA` from the
`FORM=FV-AdultCaseSummary` export taken from `ocda-config-symphony.ecourt.com`, checked
against `ecourt-sdk-local-2026-09-02.jar` — a DIFFERENT environment's jar, which is the
point of the first entry. `javap` lives at
`/Applications/jasperreports-server-9.0.0/java/bin/javap`; there is no system Java on this
machine.*

### A custom field's prefix is per-environment. Read BOTH spellings.

The same field is `c_active` in eProsecutor Baseline QA's folder view export and
`cf_active` in the local SDK jar. Confirmed pairs: `c_active`/`cf_active`,
`c_lead`/`cf_lead` on `OtherCaseNumber`; `c_bradyTag`/`cf_bradyTag` on `DirPerson`.
A wrong prefix is a `MissingPropertyException` at best and a silent null at worst — either
way an empty column with nothing anywhere saying so. The cheap defence costs one helper:

```groovy
def first = { o, String... names ->
    for (n in names) {
        def v = null
        try { v = o?."$n" } catch (ignored) { v = null }
        if (v != null && v.toString().trim()) return v
    }
    null
}
// r.cnActive = tick(first(o, 'c_active', 'cf_active'))
```

Custom *collections* carry the same problem with a third prefix in play — `c_snoopies`,
`ce_Snoopies`, `cf_snoopies` — so the collection reader needs the same treatment.

### `Address` / `Telephone` / `CaseContact`: use the dates, not `isEffectiveNow()`

The folder view filters contact details through named conditions "Address is Effective
Now" (`25d5fab4`), "Telephone is Effective Now" (`51d6e75f`), "Contact is Effective Now"
(`b2835879`). All three entities carry **real `effectiveFrom` and `effectiveTo` fields**,
so the condition is reconstructible exactly.

**Do not reach for `isEffectiveNow()` / `getEffectiveNow()`.** They exist on all three, and
`javap -c` shows the body is `iconst_0; ireturn` — the boolean form of the stripped stub
(cf. `aconst_null; areturn` for `getDateCreated`). If that behaves at run time the way
`dateCreated` does, the getter returns false for every record and the Contact Information
column is empty on every row.

`.title` on these entities is `DomainObject.getTitle()`, also stripped in the jar, and the
screen renders it — so a stripped body in this jar does **not** by itself prove the engine
returns null. Treat a stub as "unproven, do not depend on it", not as "known broken".

### `Party` has no `getFullName()` — the folder view path `parties.fullName` is resolved elsewhere

`javap -p com/sustain/cases/model/Party.class` lists `getFullNameAndPartyType`,
`getOrderedFullName`, `getTitleFML`, `getNameAndAlias` — no `getFullName`, and none on
`PersonAwareCaseComponent` (which declares nothing but a constructor) or `CaseComponent`.
`Person` has none either. The folder view renders `parties.fullName` fine, so the form's
property resolver reaches it some other way; a Groovy rule may not. Fall through:
`first(p, 'fullName', 'title', 'orderedFullName')`.

Real and confirmed on `Party`: `getIsPrimaryInvolvedPerson()` — so the very common
"Party is Primary Involved Person (PIP)" condition (`3a585c3e`) is not a pure guess.

### A tick character is DROPPED SILENTLY at PDF export

`U+2713` ✓ is outside WinAnsi. JasperReports exports Helvetica in WinAnsi unless a font
carries `pdfEncoding="Identity-H"` and `isPdfEmbedded="true"`, and no report in this corpus
embeds a font. The character vanishes: no error, no placeholder box, an empty cell — and
the row map still holds the right value, so every assertion above the render passes. This
cost the OKDAC cut of the Case Summary Report two permanently blank columns, found only by
reading the rendered page (2026-09-01).

**Print the word "Yes".** `rulecheck.groovy` now asks the real `windows-1252` encoder and
fails the run, so this is caught at build time — but only if the harness is actually run.
`·` (U+00B7) and `—` (U+2014) are inside WinAnsi and are safe.

**And the local PNG DOES NOT SHOW THIS — established 2026-09-04, the hard way.**
`render_check.groovy` rasterises with `JasperPrintManager.printPageToImage`, which draws
through **AWT** and renders any glyph the JVM font has. The PDF is exported through
**WinAnsi**. The two disagree, so a character can be plainly visible in the picture a human
is shown and simply absent from the document that ships.

Measured by extracting the text of the PDF itself:

| Glyph | in the AWT PNG | in the PDF |
|---|---|---|
| `▼` U+25BC, `▾` U+25BE, `⌄` U+2304, `∇` U+2207 | **visible** | **GONE** |
| `🔽` `📁` `📍` (U+1F5xx) | gone | gone |
| `•` U+2022, `–` U+2013, ASCII | visible | visible |

This was caught building the eSeries Screen template, whose collapse carets and column funnels looked perfect
in verification and did not exist in the PDF. Two fixes are now in place, and both matter:

- **`jti_style.static()` refuses a non-WinAnsi literal at generate time** (`_winansi`), so
  the character never reaches a page. Do not route around it by moving the glyph into a
  `$F{}` expression - the guard cannot see there, and the PDF will still drop it.
- **`render.sh` and every scaffolded `run.sh` re-raster from the PDF** with `pdfraster.py`
  (PyMuPDF), overwriting the AWT PNGs under the same filenames. The page you look at is now
  the page that ships. The JVM has no PDFBox, so this cannot be done inside `render_check`.

**Draw the shape instead of typing it.** `jti_style.tri_down()` is a caret built from
stacked rectangles; the folder in the eSeries Screen template is two rectangles. At 6-8pt no one can tell.

### Every `lookupItemFormat: LABEL` field has a `<name>Label` getter — USE IT

Confirmed real in the jar: `ScheduledEvent.getTypeLabel()` / `getResultTypeLabel()`,
`CaseAssignment.getStatusLabel()`, `OtherCaseNumber.getTypeLabel()`,
`CaseSpecialStatus.getStatusLabel()`, `CaseSeal.getTypeLabel()`, `Case.getCountyLabel()`,
plus the `partyTypeLabel` / `assignmentRoleLabel` the exports name directly.

**Not** present, so these three legitimately fall back to prettifying: `Asset.type`,
`Custody.status`, `CaseStatus.value`.

This matters more than it looks. A rule that prettifies the code instead —
`s.split('_').collect{ it.toLowerCase().capitalize() }.join(' ')` — produces a
**plausible-but-wrong page, not a blank one**: `SEX_OFFENDER` → "Sex Offender" is right by
luck, while `PRELIM_HRG` → "Prelim Hrg", `CURR` → "Curr", `FTA` → "Fta" are wrong and
nothing on the page says so. A fixture whose codes are already English words hides it
completely. Prefer the sibling, fall back to prettifying:

```groovy
def labelled = { o, String codeProp ->
    def l = null
    try { l = o?."${codeProp}Label" } catch (ignored) { l = null }
    if (l != null && l.toString().trim()) return l.toString().trim()
    label(safe(o, codeProp))
}
```

An assertion that fails when any display cell matches `/[A-Z0-9_]{3,}/` catches the
regression cheaply.

### `CaseSeal` has `effectiveFrom` / `effectiveTo` fields and SETTERS but no getters

`javap -p com/sustain/cases/model/CaseSeal.class` lists `setEffectiveFrom`,
`setEffectiveTo`, the private fields, and **no** matching getters. Neither
`SealCaseComponent` (which declares nothing) nor `CaseComponent` nor `DomainObject`
supplies them. Folder views render `seals[].effectiveFrom`, so the ORM reaches them; a
Groovy property read may not. If it does not, the panel still prints — the type column is
non-blank — with two permanently empty date columns.

### `Date.format(String)` is groovy-dateutil, same as `Date.clearTime()`

`Date.format("MM/dd/yyyy")` is `DateGroovyMethods.format` from the optional
**groovy-dateutil** module — the same module the corpus avoids for `clearTime()`. A rule
cannot coherently refuse one and rely on the other, and the failure is asymmetric: a
missing `clearTime` throws and takes the report down, while a missing `format` drops into
the catch and prints `Wed Sep 27 17:47:00 CDT 2026` in every date cell. Use
`java.text.SimpleDateFormat`, which is core Java, and the question does not arise.

### Folder-view items carry filters as `operator` / `condValue`, not only as named conditions

Not every filter on a folder view is a named condition with a hash. `FV-AdultCaseSummary`
item 10 (`parties.custodies[].status`) carries `"operator": "IN"` with `"condValue": "IN"`
— the screen shows the custody record whose status is `IN`, not the party's whole custody
history. These live in `--json` output only; the default `formexport.py` view does not
print them. **Read `--json` before deciding a column is unfiltered.**

Two related reading habits, both learned the same day:

- **A panel owns only the items between it and the next panel.** An item under Defendant
  (items 9–19) says nothing about Other Case Involvements (29–37). Copying a cell between
  two panels that look alike prints something the screen never shows.
- **`sort: ASCEND` on a multi-value cell is not decoration.** The source collections are
  `Set`s (`ScheduledEvent.getAssignments()`, `.getParties()`), so iteration order is a hash
  order and two runs of the same case produce different pages unless the rule sorts.

### Case entities confirmed real in the SDK jar (2026-09-02 local)

`Case.assets` → `Set<Asset>` with real `seizureDate`, `type`, `assetName`, `assetNumber`,
`description`, `memo`. `CaseAssignment` has real `dateAssigned`, `dateRemoved`, `victim`,
`locationName`, `directoryPerson`, `getAssignmentRoleLabel()`, `getDirectoryPersonIcon()`.
`DirPerson.getLfm()` / `getFml()` are real. `CaseSpecialStatus` has `status`, `startDate`,
`endDate`, `memo`, `category`, `value`. `CaseStatus` has `value`, `beginDate`, `endDate`.
`ScheduledEvent` carries both `assignments`/`parties` and `subpoenaAssignments`/
`subpoenaParties` — four distinct collections, so a folder view naming one of them means
that one and not its neighbour.

---

## `aconst_null` in an SDK jar is WEAK evidence on its own — read this before citing it

*Established 2026-09-04 against BOTH `ecourt-sdk-local-2026-09-02.jar` and
`ecourt-sdk-eProsecutorBaselineQA-2026-09-03.jar` — the property holds in both, so it is a
property of the SDK export itself, not of one environment.*

**The SDK jar strips the body of every derived getter.** In `com.sustain.cases.model.Case`,
**253 of 379 getters** compile to `aconst_null / areturn` (`Charge`: 44 of 110). Field-backed
accessors keep their real body (`getFilingDate()` is `aload_0 / getfield / areturn`); anything
computed is emptied.

So `getCaseTypeLabel()` reads as a stub — and it demonstrably works in production, and this
file tells you to use it (see *Every `lookupItemFormat: LABEL` field has a `<name>Label`
getter*). A stub body means **"not a stored field"**, which is exactly what a derived getter
is. It does not mean "returns null at run time".

**The rule:** `aconst_null` alone establishes only that a property cannot go in a `Where`.
To conclude a getter is *dead*, corroborate it — the Data Dictionary's derived-getter block,
an empty/absent class, or absence from the whole corpus. The two dead getters recorded above
(`User.lastLoginDate`, `DomainObject.dateCreated`) each carry that second source; that is why
they stand, and re-deriving either from bytecode alone would now be a wrong conclusion.

---

## Case search: type, sub-type, jurisdiction and the four dates

*Established 2026-09-04 by `javap` against `ecourt-sdk-eProsecutorBaselineQA-2026-09-03.jar`,
while building `Claude Reports/Case Search`. Field shape is PROVEN; nothing here has been
executed against a live environment.*

All of these are **real, field-backed, `Where`-able columns on `Case`** — bytecode confirms
`getfield`, not a stub:

| Field | Type | Note |
|---|---|---|
| `caseType` | String | lookup code. Independently attested in production criteria |
| `caseSubType` | String | lookup code |
| `caseJurisdiction` | String | lookup code. `subJurisdiction` and `geographicalJurisdiction` are SEPARATE fields — do not substitute |
| `filingDate` | Date | |
| `receivedDate` | Date | |
| `originalFiledDate` | Date | |
| `dispositionDate` | Date | |

**There is no single "case date".** Four plausible dates exist and they mean different things,
so *which one* a report should search is a question for the requester, never a default you
pick quietly. `Case Search` whitelists all four and defaults to `filingDate` — and says in its
handoff that the default is unproven. Copy that pattern: a free-text field name reaching a
`Where` is both a wrong-answer risk and injection-shaped.

`Case` also has `getCaseTypeFullLabel()` / `getCaseJurisdictionFullLabel()` alongside the
plain `*Label` getters. Both are derived (stripped bodies — see the section above); the
difference between "label" and "full label" is unverified.

### Still unproven — do not record these as facts until something runs

- The lookup list names **`CASE_SUB_TYPE`** and **`CASE_JURISDICTION`**. `CASE_TYPE` is
  attested; the other two were inferred from its shape and nothing has confirmed them.
- Whether `DomainObject.find(Case.class, w)` returns rows for a bare type/date `Where`.
- `Case.statuses` was deliberately not traversed — untested, not ruled out.

---

## How to add to this file

When a model question costs more than a couple of minutes to answer, write the answer here
with its evidence and its environment. The next report gets it for free, and the file is the
cheapest thing in the pipeline to read.

---

## Custom-field prefix on eProsecutor Baseline QA is `c_`, not `cf_` — SETTLED

*Established 2026-09-04 by `javap` against `ecourt-sdk-eProsecutorBaselineQA-2026-09-04.jar`,
the jar for the environment the `FV-AdultCaseSummary` export comes from. Supersedes the
"read BOTH spellings" uncertainty above for THIS environment only.*

The earlier entry ("A custom field's prefix is per-environment. Read BOTH spellings.")
recorded a disagreement between EPQA's folder-view export (`c_`) and the **local** SDK jar
(`cf_`). With EPQA's own jar in hand the disagreement resolves: **`c_` is EPQA's spelling and
`cf_` does not exist there.** The rule stands — the prefix IS per-environment — but the
lesson is sharper: *the disagreement was never between the export and reality, it was between
two environments.* Get the matching jar before treating a prefix as unknown.

Bytecode-confirmed on EPQA — real private fields, real public getters, not stubs:

| Class | Fields |
|---|---|
| `OtherCaseNumber` | `c_active`, `c_lead` (`Boolean`) |
| `Party` | `c_appearanceStatus` (`String`), `c_appearanceStatusDt` (`Date`) |
| `Case` | `c_snoopies` → `Set<C_Snoopy>`, `c_CaseReviews` → `Set<C_CaseReview>` |
| `com.sustain.entities.custom.C_Snoopy` | `c_source`, `c_name`, `c_type`, `c_description` (also `c_other`, `c_searchInfo`, `c_case`) |
| `com.sustain.entities.custom.C_CaseReview` | `c_type`, `c_content`, `c_status`, `c_statusDate` |
| `com.sustain.dir.model.DirPerson` | `getC_bradyTag()` |

Two incidental gotchas worth the line each:

- **`DirPerson` lives in `com/sustain/dir/model`, not `com/sustain/directory/model`.** A
  `javap` against the guessed path prints nothing and reads exactly like "the field does not
  exist" — a false negative that costs a real column.
- Custom entities extend `CaseComponent` and are named `C_<Thing>` in
  `com.sustain.entities.custom`, so the collection getter is `getC_snoopies()` — the odd
  underscore-after-C capitalisation is real and Groovy property access (`o.c_snoopies`)
  reaches it.

### `CaseSeal` getters: the gap is REAL, not a wrong-environment artifact

EPQA's own jar lists `effectiveFrom` / `effectiveTo` as private `Date` fields with
`setEffectiveFrom`, `setEffectiveTo` and `isEffectiveNow()` — and **no getters**, same as the
local jar. Two independent environment jars agreeing means this is a property of the class,
so the earlier caution stands unchanged: a Case Seals panel may print with two empty date
columns and nothing will say why.

---

## `list.sort(comparatorClosure)` returns NULL — always use the two-arg `sort(false, cmp)`

*Established 2026-09-04 while reworking `Case Summary Report EPQA`'s header. Cost one full
render cycle to find, because the failure surfaces one line later as an unrelated NPE.*

A one-argument `.sort(cmp)` on a `java.util.List` binds to **Java 8's
`List.sort(Comparator)`, which is declared `void`** — not to Groovy's DGM `sort(Closure)`.
The expression therefore evaluates to `null`, the list *is* sorted in place, and the failure
appears at the next use of the result:

```groovy
// WRONG - `upcoming` is null; dies on the following line with
//   java.lang.NullPointerException: Cannot invoke method size() on null object
def upcoming = hearings.findAll { isFutureEvent(it) }
                       .sort(byKey({ safe(it, 'startDateTime') }, false))

// RIGHT - mutate=false returns a NEW sorted list
def upcoming = hearings.findAll { isFutureEvent(it) }
                       .sort(false, byKey({ safe(it, 'startDateTime') }, false))
```

The two-arg form is already the idiom throughout the corpus (seven call sites in
`Case_Summary_Report_EPQA_V1.groovy` alone) — this was a new call site written from memory,
which is exactly how it gets reintroduced. The NPE names `size()`, or whatever method the
next line happens to call, and says nothing about sorting; grep the rule for
`.sort(` **not** followed by `false,` before debugging anything else.

---

## `fml` is NOT a getter on `CaseAssignment` or `Party` — both need a fall-through

*Established 2026-09-04 by `javap` against `ecourt-sdk-eProsecutorBaselineQA-2026-09-04.jar`
while building `Claude Reports/Case Summary Report EPQA` from the full 11-panel
FV-AdultCaseSummary export. Same family as the `parties.fullName` entry above.*

`FV-AdultCaseSummary` renders `hearings.assignments.fml` (item 4) and
`hearings[].parties[].fml` (item 5). Neither class has the getter:

- **`CaseAssignment`** — no `getFml`, no `getLfm`, no `getTitle`. It *does* have a real
  `directoryPerson` field, and `DirPerson.getFml()` / `getLfm()` are real, so the chain
  `first(a,'fml','lfm')` then `a.directoryPerson?.fml` has a proven floor.
- **`Party`** — no `getFml` and no `getFullName` either. Real and confirmed:
  `getFullNameAndPartyType()`, `getOrderedFullName()`, `getTitleFML()`. So the chain is
  `first(p,'fullName','fml','titleFML','orderedFullName','title')` then the person behind
  the party.

The form's property resolver reaches `fml` some other way. A Groovy rule may not, and the
failure is a blank cell, not an error.

### Header fields on `Case`, all bytecode-confirmed real on EPQA

Verified while sourcing the `CaseBannerWidget` header block — these are the eleven-field
banner's backing fields, and none of them had to be guessed at:
`receivedDate`, `caseUnit`, `location` (+ `getLocationLabel()`), `caseJurisdiction`
(+ `getCaseJurisdictionLabel()`), `getCategoryLabel()`, `caseNumber`,
`getCaseNumberDisplayed()`, `getNextEvent()` → `ScheduledEvent`, `c_caseRelatedDetails`.

`ScheduledEvent` confirmed: real `startDateTime`, `type`, `resultType`, plus real
`getTypeLabel()` / `getResultTypeLabel()`, and both `assignments` and `parties` Sets.

**`Case.getC_caseTypeHistories()` EXISTS** (→ `Set<C_CaseTypeHistory>`). This matters for
reading an export: FV-AdultCaseSummary's twelfth panel, Case Type History, has zero field
items (item 90 header, item 91 end-of-panel) — so that panel is **unconfigured on the
screen, not unbacked by data**. An empty panel in an export is a config gap to fill, not a
traversal to go discover.

---

## Template B's DEFAULT two-column header block CLIPS real values — silently

*Established 2026-09-04 building `Case Summary Report EPQA` on the shared
`templates/eseries_summary.py`. Caught by an awkward fixture, not by the code.*

`eseries_summary.HEADER_COLS` defaults to **two** label/value columns at x=238 and x=368.
The title block owns a fixed 238pt of the 572pt page, so the header has 334pt; split two
ways, minus a 50–84pt label column, **every value box lands at 70–116pt**. At 7pt that
truncates ordinary values mid-word, with **no ellipsis and nothing in the render saying a
character was dropped**:

| Printed | Actual |
|---|---|
| `Featherstonehaugh,` | Featherstonehaugh, Margaret A. |
| `Delacroix-Mbeki,` | Delacroix-Mbeki, Jean-Baptiste (retained) |
| `Oklahoma City - Downtown` | Oklahoma City - Downtown Division |
| `Preliminary Hearing` | Preliminary Hearing 10/14/2026 9:00 AM |

**Pass one wide column instead** whenever a header value can hold a person's name — which
on a case screen is Attorney, Defense, and the next-event line at minimum:

```python
HEADER_COLS = [(238, 82, [("Received", "hReceived"), ..., ("Location", "hLocation")])]
```

That gives every value 248pt. The band grows from ~77pt to ~140pt; `_title()` already
derives its height from the deepest column, so nothing in the template needs changing.

**The general lesson, which is the reusable half:** a `S.text()` in the title band has no
`grow=True`, so a header value is CLIPPED where a detail cell would WRAP. A fixture whose
header values are short cannot see this. Put a full "Lastname-Hyphenated, Firstname M."
and a date-plus-time string in every header field of every fixture.

---

## Case header: which of the nine header values have a real label getter, and which do not

*Established 2026-09-09 by `scripts/sdk_fields.py` against
`ecourt-sdk-eProsecutorBaselineQA-2026-09-04.jar` while building
`Claude Reports/Adult Case Header` from the `FORM=H-AdultCaseHeader` export. Extends the
"Header fields on `Case`" entry above with the label side, which that one did not cover.*

**A business rule has no `$lookupListTool`.** The header form calls
`$lookupListTool.getLabel("CASE_UNIT", $case.caseUnit)` for five of its nine values; a
Groovy rule cannot, so each coded value has to reach its display text through the sibling
`<name>Label` getter. Two of the five have no such sibling **anywhere on the Case chain**:

| Header value | Code field | Label getter |
|---|---|---|
| Jurisdiction | `caseJurisdiction` | `caseJurisdictionLabel` — real |
| Crime Category | `category` (NOT `caseCategory`) | `categoryLabel` — real |
| Location | `location` | `locationLabel` — real |
| Status | — | `statusLabel` — real |
| **Vertical Unit** | `caseUnit` | **NONE. `caseUnitLabel` is not on the class** |
| **Related Details** | `c_caseRelatedDetails` | **NONE** |

Those last two can only be prettified from the raw code, and that is a
**plausible-but-wrong page, not a blank one** — the failure mode this file warns about
under the `lookupItemFormat: LABEL` entry. Say so in the handoff; it takes one look at a
real case to settle and cannot be settled locally.

`caseCategory` deserves its own line: the form's velocity calls `$case.caseCategory`, and
**`caseCategory` is not a field on `Case`** — it is a stripped getter on `CaseComponent`.
The real field is `category`. Read both spellings, `caseCategory` first. A form rendering
a property is not proof the property is the field.

---

## The eSeries Screen template CLIPS the title, subtitle, status and banner captions — not just the header columns

*Established 2026-09-09 on `templates/eseries_summary.py`, extending the
"Template B's DEFAULT two-column header block CLIPS real values" entry above. The earlier
entry fixed the header COLUMNS by passing one wide column; these four are template
constants and cannot be fixed from `gen_jrxml.py` at all.*

`_title()` hard-codes the identity boxes at **230pt on one line each** (x=18, independent
of `HEADER_COLS`) and `_banners()` fixes each caption at **150pt**. With realistic values
that clips four separate strings, mid-word, with no ellipsis:

| Printed | Actual |
|---|---|
| `Felony Citation ~ CF-2026-` | Felony Citation ~ CF-2026-0114837-A |
| `Featherstonehaugh-Delacroix, Margaret ` | …Margaret Anne Elizabeth |
| `SEX OFFENDER REGISTRATION ` | … REQUIRED |
| `Adult Case Header - case 4417829 - printed ` | … 09/09/2026 14:22 |

Note also that `S.text(18, 230, ...)` runs to x=248 while the default `HEADER_COLS` starts
at x=238 — the identity boxes already overlap column one.

**For a case-header-shaped report, start from `case_screen.py`** in
`OCDA Reports/Case Summary Report/` rather than the eSeries Screen template. It is the same screen look and
it has none of these limits: the title box is two lines deep and top-aligned, every info
value box holds two lines of 8pt, and the flag bars span the full width split *n* ways.
Copying it into the new report folder is the corpus convention and took one command.

Two fixes were made to that copy and both belong to any report using it:

* **Put the case title on its own FULL-WIDTH line.** In a 186pt box a real case number
  wraps *inside itself* (`Felony Citation ~ CF-` / `2026-0114837-A`), because
  JasperReports fills a line greedily and will break at a hyphen inside a token to do it.
  Nothing is lost, but it reads badly and it defeats `cliphunt.py` (below).
* **The defendant line needs three lines, not one.** It is a JOIN of every primary
  involved person; at 186pt one 16pt line printed the surname and dropped the rest.

---

## `cliphunt.py` has two blind spots. Know both before trusting a green gate.

*Established 2026-09-09, both the hard way, on `Claude Reports/Adult Case Header`.*

**1. A value that appears TWICE on the page hides a clip in one of them.** cliphunt
searches the whole page's normalised text for each fixture value. A header field whose
value is also printed in full by a detail panel is therefore always "found" — so the
header can be clipping it to a prefix and the gate passes. This is not hypothetical: the
defendant-line clip above was found by extracting the PDF's own text by hand, *after* a
clean gate run.

**The fixture is the fix.** Where a header field can also appear in a panel, make the two
values differ — for a joined field, put the join in the header (`"Name A  /  Name B"`) and
the single names in the panel. That is more realistic anyway.

**2. A hyphen-wrapped value reads as a truncation.** cliphunt normalises the page's
newlines to spaces, so `"CF-\n2026-0114837-A"` becomes `"CF- 2026-0114837-A"` and no
longer matches the fixture's `"CF-2026-0114837-A"`. That is a FALSE positive, and the only
real fix is a box wide enough that the wrap never happens — do not shorten the fixture to
get past it, or the check stops proving anything.

**And a section KEY is a fixture value too.** cliphunt reads every TSV cell, `section`
included, and `PERSONNEL` has the printed column header `PERSON` as a prefix — so it
reported that header as a truncated section key. Name section keys so that no printed
label is a prefix of one (`JUSTICE`, not `PERSONNEL`).

---

## `flagText${i}` is INVISIBLE to `contract_check.py` — write every key literally

*Established 2026-09-09. Cost one gate cycle.*

`contract_check.py` reads the keys a rule emits out of the Groovy **source**. A map built
in a loop —

```groovy
(1..3).each { i -> FLAGS["flagText${i}"] = ... }     // WRONG
```

— emits the right keys at run time and shows the checker nothing, so the gate reported six
fields "declared but NOT emitted" and would just as happily have passed a rule that really
did omit them. Write the slots out one per line:

```groovy
def flagAt = { int i, String k -> (i <= flags.size()) ? flags[i - 1][k] : "" }
def FLAGS = [flagCount: flags.size().toString(),
             flagText1: flagAt(1, 'text'), flagTone1: flagAt(1, 'tone'), /* ... */]
```

The general rule: **any key the layout declares must appear as a literal in the rule
source**, or the contract gate is passing on a file it cannot actually read.

---

## FINANCIALS: every dollar getter is a stripped stub; every `*Cents` getter is real

*Established 2026-09-10 by `javap -c` against `ecourt-sdk-local-2026-09-02.jar` while
building `Claude Reports/Case Financials` from the FV-CaseObligations export. Measured
across eight classes, so it is a property of the SDK export, not of one class.*

| Class | dollars | cents |
|---|---|---|
| `Invoice` | `getAmount` / `getBalance` **STUB** | `getAmountCents` / `getBalanceCents` **REAL** |
| `Restitution` | `getAmount` / `getOutstandingAmount` **STUB** | `getAmountCents` / `getPaidCents` **REAL** |
| `PaymentInvoice` | `getAmount` **STUB** | `getAmountCents` **REAL** |
| `MonInstrument` | `getAmount` **STUB** | `amountCents` **REAL** |
| `TrustTransaction` | `getAmountSignedCents` **STUB** | `getAmountCents` **REAL** |
| `PayPlan` | `getBalance` / `getPayPlanAmount` **STUB** | **no cents field exists** |
| `Installment` | `getBalance` / `getAmount` / `getFullyPaid` **STUB** | `amountCents` **REAL**, no balance |
| `Receipt` | `getTotalAmount` / `getTotalAmountCents` **STUB** | **no amount field at all** |

### The double stub returns `-1.0d`, and that is worse than null

The stripped-getter signature has a form per return type: `aconst_null / areturn` for an
object, `iconst_0 / ireturn` for a boolean, and — new here — **`ldc2_w -1.0d / dreturn`
for a double**. So a dead money getter does not blank the cell, it prints **`$-1.00`**:
a plausible-looking wrong number that no assertion above the render will catch.

**The rule that follows from it:** where a real `*Cents` column exists, compute dollars
from it (`cents / 100.0d`) and never read the derived getter — that is provable
arithmetic. Where none exists (`PayPlan` totals, `Installment` balance, `Receipt`
total), read the getter, **reject `-1.0`**, and fall back to computing:
plan totals from the sum of its installments, installment balance from `amountCents`
less its `InstallmentPayment.amountCents`, receipt total from the sum of
`MonInstrument.amountCents`.

Note this does NOT contradict the financials skill's "fields named `amount` are already
dollars" table — they are. It says only that in *this jar* they are derived rather than
stored, so the cents column is the safer read and the sentinel must be guarded.

Also confirmed real and useful: `Case.getInvoicesBalance()`, `Case.getActivePayPlans()`
and `Case.getPayPlans()` (both `List`, not `Set`), `Case.getPayRestitutions()` (`List`),
`Case.getReceipts()` (`Set`). `Receipt` stored fields include `originalReceipt`,
`receiptType`, `fullReceiptNumber`, `receiptNumber`, `till`, `monInstruments`,
`vouchers`, `nonMonetarys` — but **no amount of any kind**.

### Enums to reconstruct two folder-view conditions

`PayPlanStatus` = ACTIVE / INACTIVE / HOLD. `Installment$InstallmentStatus` = ACTIVE /
INACTIVE / SKIPPED. `PayPlan.getInactiveStatus()` is a stub, so "Pay Plan is Inactive"
(`366329d7`) rebuilds as `status != ACTIVE` — which puts HOLD on the inactive side, a
judgement call worth naming in a handoff.

---

## `fml` is not a getter on `Person` either — three classes now, treat it as a rule

*Established 2026-09-10 on the local jar, extending the 2026-09-04 finding.*

`Party`, `CaseAssignment` and now **`Person`** all render `*.fml` in folder views and
none of them declares `getFml()`. `Person` has `getFmlAndAkas()` / `getLfmAndAkas()` and
no plain `getFml`. Treat **`fml` as a form-resolver path, never a getter**, on any class,
and always fall through:

```groovy
def personName = { p -> str(first(p, 'fml', 'fmlAndAkas', 'lfmAndAkas', 'title', 'fullName')) }
```

Same family: **`TrustTransaction` has no `getTitle()`** — the folder view's
`sortedTrustTransactions.title` needs `getShortTitle()` / `getInstrumentTitle()`.

---

## Template B: the DEFAULT column-heading alignment and right-column spacing were wrong

*Found 2026-09-10 by the Case Financials fixture; both fixed in
`templates/templates/eseries_summary.py`, so they are already gone.*

Two defects that only appear once a section has a **right-aligned** column, which no
earlier template-B report had:

- The heading was hard-coded Left. Over a right-aligned money column that puts the
  heading at one end and every value at the other, and it reads as though the heading
  belongs to the neighbouring column. Headings now take their column's alignment (the
  first column stays Left, because the funnel indent would fight a right-aligned label).
- A right-aligned value sits hard against its column's right edge while the next
  column's left-aligned value starts 2pt into its own — ~4pt apart, rendering as one
  run of text: `$4,882.50 Active`, `$2,000.00 04/15/2026`. `_rw()` now narrows a
  right-aligned box by an 8pt gutter, which moves the text without changing any
  column's share of the width.

**`subrows=True` is also new** — an opt-in second detail layout giving an indented,
wrapping, full-width line (`rowKind` / `subText` / `subDepth`), for `[tree]` panels and
for a detail block too wide for the column set. It is off by default and adds no fields
when off. Once ON, `rowKind` is required on EVERY row: the template gates both layouts
on it, so a null matches neither and the row vanishes silently.

**And the general lesson about fixtures, again:** all three of these were invisible until
a fixture had a right-aligned money column next to a left-aligned one. Put a
right-aligned column, a name long enough to wrap, and a full date-plus-time string in
every fixture — the defects these catch are all silent ones.

---

## FINANCIALS, corrected: there is a `-1L` LONG sentinel too, so "every `*Cents` getter is real" is FALSE

*Established 2026-09-17 by `javap -c` against `ecourt-sdk-local-2026-09-17.jar` while
building `OKDAC Reports/Case Financials` from the FV-CaseObligations export. This
CORRECTS three claims in the 2026-09-10 FINANCIALS entry above, which was measured on the
2026-09-02 jar. Where the two disagree, believe this one for the 09-17 jar and re-measure
before trusting either on a third.*

The 09-10 entry established the `ldc2_w -1.0d / dreturn` double sentinel and concluded
**"every `*Cents` getter is real"**. That second half does not hold. There is a **`ldc2_w
-1l` LONG sentinel** as well, and it lands squarely on cents getters:

| Sentinel | Getters |
|---|---|
| `double -1.0d` | `Invoice.getAmount/getBalance`, `Restitution.getAmount/getOutstandingAmount`, `PayPlan.getBalance/getPayPlanAmount`, `Installment.getBalance/getAmount`, `MonInstrument.getAmount`, `PaymentInvoice.getAmount`, **`Case.getInvoicesBalance`** |
| **`long -1l`** | **`PayPlan.getBalanceCents`, `PayPlan.getPastDueAmountCents`, `Installment.getAmountPaidCents`, `Installment.getBalanceCents`, `Installment.getPastDueAmountCents`, `Receipt.getTotalAmountCents`, `TrustTransaction.getAmountSignedCents`** |

Genuinely real (`aload_0/getfield`): `Invoice.amountCents/balanceCents/paidCents`,
`Restitution.amountCents/balanceCents/paidCents`, `Installment.amountCents`,
`InstallmentPayment.amountCents`, `InstallmentTrustPayment.amountCents`,
`MonInstrument.amountCents`, `PaymentInvoice.amountCents`, `TrustTransaction.amountCents`.

**Three corrections to the 09-10 entry, each of which would have shipped a wrong number:**

- **`Case.getInvoicesBalance()` is a `-1.0d` stub.** The 09-10 entry lists it under
  "confirmed real and useful". It is not. A case-balance header sourced from it prints
  `-$1.00`.
- **`Receipt.getTotalAmountCents()` returns `-1l`** rather than being absent. Same
  practical advice (sum the `MonInstrument`s) but the failure mode is a plausible number,
  not a blank.
- **`Restitution.getBalanceCents()` is REAL**, so outstanding restitution is a direct read;
  no need to compute `amountCents - paidCents`. And `Restitution` lives in
  **`com.sustain.cases.model`**, not `com.sustain.financial.model` — a `javap` against the
  guessed package prints nothing and reads exactly like "the class does not exist".

**The rule that survives all of it: reject `-1` on EVERY money read, long and double
alike, and never test for null alone.**

```groovy
def cents = { o, String n ->          // returns null, never -1
    def v = safe(o, n); if (v == null) return null
    long l; try { l = ((Number) v).longValue() } catch (ignored) { return null }
    return (l == -1L) ? null : Long.valueOf(l)
}
```

`PayPlan` has **no readable amount of any kind** — sum its installments. `Installment` has
only `amountCents` — its paid figure sums `installmentPayments` + `installmentTrustPayments`.

### `sdk_fields.py` REPORTS THESE SENTINELS AS `field-backed` — do not trust it on money

This is the dangerous half. Asked about `Installment.balance`, `PayPlan.payPlanAmount` or
`Receipt.totalAmountCents`, `scripts/sdk_fields.py` prints **`field-backed`** — the verdict
that means "the getter returns the stored field". `javap -c` on the same method prints
`ldc2_w -1.0d / dreturn`. The tool's classifier evidently does not recognise the sentinel
form, so **the one verdict that should warn you reads as the all-clear.**

`sdk_fields.py` remains right for "does this name exist, and where is it declared", which
is what it is for. For any getter whose value is MONEY, confirm with `javap -c` before
reading it. The batch form costs one call:

```bash
JAVAP=/Applications/jasperreports-server-9.0.0/java/bin/javap
$JAVAP -c -p -cp "$JAR" com.sustain.financial.model.Invoice | grep -A4 ' getBalance();'
```

### cliphunt has a THIRD blind spot: static column HEADINGS

Extending the two recorded above. cliphunt matches **fixture values** against the page, and
a column heading is a `S.static()`, not a field — so a heading clipped by its own column is
invisible to it. On this build the heading `Charge` printed as `Charg` through a completely
green gate, and only reading the rendered page found it. **Look at the headings, every
time.** A narrow right-hand column with a word longer than its digits is the usual shape.
