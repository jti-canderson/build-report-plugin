# Deploying a report

*Part of the `jasper-reports` skill. Read when putting the rule and .jrxml into eSeries: the rule editor, Reports Admin, and the iteration loop.*

# Business Rules (eSeries admin)

Rules are where most eSeries behaviour actually lives: report datasets, financial actions, document rules, workflow steps, bulk merges, API handlers. They are Groovy held in the database, edited in-app, and compiled server-side. Nothing here is in your git repo, so treat every change as production configuration.

Not report-specific. When the rule *is* a report dataset, pair this with `report-builder` (designing a new one) or `jasperreports-verification` (checking the Groovy↔JRXML contract).

## Ground rules

**Never press a commit control. Stage, then hand it over.** That means Update, Save, Compile & Save, Save As, Submit, Replace, Delete — on any record, in any environment, including QA. Fill the fields, verify them on screen, report exactly which record and which values are staged, and let the user press the button.

This holds even when the user has approved the work. "Go ahead and update both", "you can update them in eSeries", "go straight to placing the item", and a repeated navigation instruction are **not** consent to commit — they describe the task, not the write. Ask for that specific commit, every time, and wait.

Two things in this UI commit without a button, so treat them as saves too: adds and deletes in the form-item editor, and drag-and-drop reordering. Everything you do runs in the user's own session, so every change is stamped with their name — which is precisely why an unrequested write is expensive for them. On a new rule the only commit control is **Compile & Save**, which compiles *and* persists in one action — there is no fill-and-stop-at-the-last-moment. So fill everything, verify it on screen, then ask. `Execute` actually runs the rule, which for a non-transactional report rule is usually safe but for a transactional one writes to the database.

**Say which environment you are on.** Read it from the page title — each deployment names itself there (a QA site, a master site, a conversion site, a district). Rules do not sync between environments; creating one on QA does nothing for master.

## Finding your way


In short: the rules index lists Category, Engine, # Usages, **Inputs** and observed runtimes — use it to find a comparable rule and copy its conventions before writing a new one. **Always open a comparable existing rule first.**


## The rule form

| Control | Notes |
|---|---|
| `ruleCode` | Code, e.g. `Annual_Report_by_Collecting_Agency` — Title_Case_With_Underscores, unique |
| `ruleName` | Human name, e.g. "Annual Report by Collecting Agency" |
| `ruleCategory` | Free text; `Reports`, `Financials`, `Document`, or blank (shows as NONE) |
| `ruleDescription` | Optional, often empty on existing rules |
| Transaction End | radio `transactional` — `true` = transactional (rollback on failure); `false` = **long running / does not update the database**. Report rules use `false` |
| Engine | radio `engine` — `JAVA`, `NAVIGATION`, or `SCRIPT`. Groovy rules are `SCRIPT` |
| Enabled flags | API / Case / Document / Batch / System — leave unchecked unless the rule is invoked that way |
| Input Parameters | separate table, see below |
| Output Parameters | same shape as inputs; report rules need `data` / REQUIRED / `java.util.List` — see below |
| Comment on Changes | commit message; fill it, e.g. `ODA-4235 initial Certified Discovery Report rule` |

Select the engine radio **before** touching the script: the CodeMirror editor is created when `SCRIPT` is chosen.

## The registration block — hand this over with every report

Whoever adds the rule is looking at an empty form with a Groovy file next to it, and the form will not tell them what to type. **Every time you hand over a report rule, hand over a filled-in block like the one below** — in the chat message, and as `RULE_REGISTRATION.txt` in the report's own folder (see "The report folder" in `SKILL.md`). It is the difference between "here is the code" and "here is a rule someone can add".

Fill it in for real; do not ship the placeholders.

**Rule**

```
Code                <Report_Name_In_Title_Case>
Name                <Report Name>
Category            Reports
Description         <one line: what it prints and what it is scoped to>
Transaction End     false          long running / does not update the database
Engine              SCRIPT         select this radio BEFORE pasting the script
Enabled flags       none checked
Script              <file name>.groovy
Comment on Changes  <TICKET> initial <Report Name> rule
```

**Input Parameters**

```
Name          Type       Class              Preset Value
<paramName>   REQUIRED   java.lang.Long     empty
<otherParam>  OPTIONAL   java.lang.String   empty
```

**Output Parameters**

```
Name   Type       Class
data   REQUIRED   java.util.List
```

**Report Registration** — Reports Admin, after the rule is saved

```
Name / Code             <Report_Name_In_Title_Case>
Data Source Generator   <Report_Name_In_Title_Case>    stored as rule:<Code>
Isolation               READ_UNCOMMITTED
Default Format          pdf
Parameters tab          auto-detected from the JRXML <parameter> declarations
```

### Filling each field

**Code** — `Title_Case_With_Underscores`, unique across the environment, and worth making identical to the JRXML `name=` attribute and the Reports Admin code. Three places holding the same string is what makes the stack greppable later; three near-misses is what makes it unsearchable.

**Name** — the same words with spaces. This is what appears in the rules index.

**Category** — `Reports`. It is free text, so a typo makes its own category; copy it exactly. (`Financials` and `Document` are the other conventional values.)

**Description** — often left empty on existing rules, which is a habit worth breaking. One line answering *what does it print, and scoped to what*: "Prints the case Charges tab — active charges, plea offers, charge history and sentencing — for one case." Someone scanning the rules index for a rule to copy is reading this field and nothing else.

**Transaction End** — `false` for every report rule. `true` means transactional; a report reads and does not write.

**Engine** — `SCRIPT`. Select this radio **before** touching the script box: the CodeMirror editor is only created once `SCRIPT` is chosen.

**Enabled flags** — API / Case / Document / Batch / System all unchecked. A report rule is invoked by the report, not by any of those channels.

### Input parameters — the seam that breaks silently

Inputs are declared in the table, not inferred from the script.

- **Name** is the bare name, no leading underscore: type `caseId`, and the Groovy sees `_caseId`. Getting this wrong does not error — the variable is simply absent, and criteria built from it quietly return everything or nothing.
- **It must match the JRXML `<parameter name="…">` exactly**, character for character. That name is how Reports Admin's auto-detected parameter reaches the rule; `caseID` in one place and `caseId` in the other is a blank report with no error message.
- **Type** — `REQUIRED` when the rule cannot work without it, `OPTIONAL` when the rule genuinely branches on its absence (`binding.hasVariable('_x') && _x`). Two mutually exclusive scopes are legitimately both OPTIONAL. `HIDDEN` and `FIXED` also exist.
- **Class** — `java.lang.String`, `java.lang.Long`, `java.lang.Integer`, `java.util.Date`, `java.lang.Boolean`, array forms (`[Ljava.lang.Long;`, `[Ljava.util.Date;`) for multi-select input controls, or a domain class. Ids are `java.lang.Long`; dates are `java.util.Date`; anything a user picks from a multi-select is the array form.
- **Preset Value** — leave it **empty** unless you specifically want a default. A stray value here is substituted on every run that omits the parameter and then coerced to the declared class, so the run fails with `NumberFormatException: Unparseable number: "caseId"` *before the script executes* — nothing in the Groovy explains it. Read the whole row back after filling.
- Values arrive as **Strings regardless of the declared class**, and a blank arrives as empty string rather than null. Coerce in the rule (`v.toString().trim() as Long`).

Note that "required" is enforced by this table, not by the JRXML — JasperReports has no mandatory-parameter concept. If you describe a parameter as optional to the user, mark it `OPTIONAL` here too, or the input control will refuse to submit without it and they will conclude your code is broken.

### Output parameters — the row everyone forgets

Every rule that feeds a JRXML report needs exactly this one row:

| Name | Type | Class |
|---|---|---|
| `data` | `REQUIRED` | `java.util.List` |

`data` declared as an output is what makes `_data = result` at the end of the script reach the caller — the same underscore convention as inputs. The class is `java.util.List` even when the script builds a `Set`.

Miss this row and the rule compiles, saves, and runs clean while the report renders nothing. It is the single most expensive silent failure in this stack, and it looks exactly like a bad traversal, so it costs an afternoon of debugging the wrong half.


## Getting Groovy into the editor

The visible editor is CodeMirror over a hidden `#scriptText` textarea. Setting the textarea's value alone can be discarded, so drive the editor instance and mirror it into the textarea:

```js
const cmEl = document.querySelector('.CodeMirror');
if (cmEl && cmEl.CodeMirror) cmEl.CodeMirror.setValue(text);
const ta = document.getElementById('scriptText');
if (ta) { ta.value = text; ta.dispatchEvent(new Event('change', {bubbles:true})); }
```

For anything longer than a few lines, **base64 the file and decode in the page** rather than pasting source into a tool call — it removes every quoting/escaping hazard, and `TextDecoder` keeps non-ASCII (em dashes in comment headers) from being mangled the way `atob` alone would:

```js
const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
const text  = new TextDecoder('utf-8').decode(bytes);
```

Then confirm the round trip before moving on: compare `CodeMirror.getValue().length` against the source length, and check the first and last lines. A silent truncation here becomes a compile error later that looks like a code bug.

## Input and output parameters — mechanics of the table

The *values* to enter are in the registration block above; this is how the table behaves.

Add rows with **Add Item** (the `Add Inputs` button in the editor toolbar is a different, code-side helper). New rows land at the end; the table is drag-and-drop to reorder. Existing rules normalise multi-select inputs with `_county instanceof Collection ? … : …`, because a single-select and a multi-select arrive differently — defend in code.

When filling a row programmatically, locate its controls **relative to the row** (`input.closest('tr')`), not by a global select index — indices shift as rows are added, and a global-index fill has previously written a parameter *name* into the previous row's **Preset Value**, which looked correct in Name/Type/Class and broke every run afterwards. Read back every column of every row.

## Verifying

This is the one place in the eSeries stack where you get real verification, so use it:

- **Compile** (editor toolbar) checks the Groovy compiles against the live domain model — it catches syntax errors, a missing import, and an entity class that does not resolve. Cheaper and far more informative than reading the code again.
- **Be precise about what a clean compile proves.** Groovy is dynamically typed, so property access is *not* checked: `pkt.availOnWeb`, `t.parent?.title`, `doc?.nameExact` all compile whether or not they exist, and a wrong one yields null at run time — an empty column, not an error. A clean compile means "the classes resolve and the syntax is valid", nothing more. Say it that way rather than implying the traversals are verified.
- **Compile & Save** does the same and persists.
- **Execute** runs it, with inputs, in a dialog with a **Rollback** checkbox (on by default — leave it on). The test fields are `testEditor.inputs[N].value`, not labelled inputs, so find them by name when driving the dialog.
- **Execute shows errors but not return values**, which makes it awkward for exploration. The way around that is a **probe**: temporarily replace the script with a throwaway that gathers findings and *throws* them, then read the answer out of the error banner. Nothing is saved unless you press Compile & Save, so keep the real script in a variable and restore it afterward:

```groovy
def out = []
try { out << 'a=' + SomeEntity.get('SomeEntity', id as Long)?.name } catch (e) { out << 'a!' + e.class.simpleName }
try { out << 'b=' + SomeEntity.get(SomeEntity,   id as Long)?.name } catch (e) { out << 'b!' + e.class.simpleName }
throw new RuntimeException('PROBE >> ' + out.join('  ||  '))
```

  One run then answers a question that would otherwise take several save-and-retry cycles. Restore the real script immediately and verify it came back intact before doing anything else.
- **Imports** manages the import list; `Add Rule Call` inserts a call to another rule.

## Shipping a rule as an import instead of typing it

A `RULE` config export is a complete, importable rule — code, name, category, every input and
output with its class and lookup list, the engine, and the script. So a rule can be **handed
over as a file** rather than pasted into CodeMirror and re-declared row by row in the
parameter form. Build one:

```bash
SK=jasper-reports
K=$(for p in . .. ../.. ../../..; do for b in System/Skills .claude/skills; do
      [ -d "$p/$b/$SK" ] && { echo "$p/$b/$SK"; exit; }; done; done
    [ -d "$HOME/.claude/skills/$SK" ] && echo "$HOME/.claude/skills/$SK")
S=$K/scripts
python3 "$S/rule_import.py" --groovy My_Report_V1.groovy --code My_Report \
    --name "My Report" --input caseId:long --input startDate:date \
    --input county:lookup:COUNTY:REQUIRED --output data:java.util.List:REQUIRED
python3 "$S/formexport.py" RULE-My_Report.zip        # read it back before handing it over
```

`--input` is `name:className[:LOOKUP_LIST][:REQUIRED]`, bare name, no underscore. Shorthands:
`date string long int bool lookup decimal`. `--selftest <a real export>` regenerates that
export from its own parts and diffs — it reproduces `RULE=Official_Depository_Ticket.xml`
byte for byte (619 lines), which is what establishes the writer is right.

### The format, and the three places it is easy to get wrong

`<com.sustain.api.model.ConfigExportRsp>` with, in order, `srcActionUrl`, `srcContent`,
`srcImportContent`, `srcRoot`, `srcHash`, `srcCode`, `srcId`. No XML declaration.

1. **`srcImportContent` is the payload, not `srcContent`.** `srcContent` is a round-trip text
   form that declares parameters as example assignments (`_startDate = new Date();`,
   `_agency = 'ABC';`, `_data = '???';`) between `// --- INPUT PARAMETERS START ---` style
   markers. It is **lossy** — it cannot express `lookupListName` or REQUIRED vs OPTIONAL.
   `srcImportContent` is a `com.sustain.rule.model.RuleDef` and carries everything.
2. **`<script>` is not the Groovy.** It is a nested doc — `<code>`, `<category>RULE`,
   `<language>groovy`, `<content>` — and the Groovy sits in `<content>`, escaped one level
   deeper than the tags around it. At file level a CR reads `&amp;#xd;` while the RuleDef's
   own tags read `&lt;code&gt;`.
3. **XStream escaping.** `& < > " '` all become entities, the payload is CRLF, and every CR
   becomes `&#xd;` with the LF left literal. The script's trailing CRLF supplies the blank
   line before `// --- RULE CONTENT END ---`; trimming it is the classic off-by-one.

Each param also carries `<ruleDef reference="../../.."/>`, an XStream back-reference to the
owning RuleDef — structural, not data, so emit it verbatim.

### What is still unproven

No hand-built file has been imported. Unknown: whether the importer needs `srcHash` / `srcId`
(left empty for a new rule), and whether it **creates or updates** when the target already has
that Code — Reports Admin's own Import creates and leaves a duplicate, so assume this may too
until someone proves otherwise. Worth noting `lookupListName` is declarable here at all, which
the rule form makes look like a UI-only setting.

Also worth flagging: a live production rule (`Official_Depository_Ticket`) declares its `data`
output as **OPTIONAL**, not REQUIRED. So what matters is that the output *exists*; the
REQUIRED that this skill recommends elsewhere is convention rather than a hard requirement.

**Importing is a write.** Generate the zip, say what is in it, and let the user import it.

Before asking to save, state on screen: code, name, category, transaction end, engine, script length, and each input with its type and class. After saving, re-read the rule page to confirm what persisted — do not trust the redirect.

## Reporting back — the handover message

Short, scannable, no prose recap of work the files already contain. Reasoning belongs in
the `.groovy` header and the contract file; the message is what someone acts on.

Use this shape:

````
**<Report Name>** — `<Report Name>/`

<One line: what it prints and what it is scoped to.>

**Files**

| File | |
|---|---|
| [<name>.groovy](…) | rule source |
| [RULE-<Code>.zip](…) | the same rule, importable — always include it |
| [<name>.jrxml](…) | layout, N String fields |
| [RULE_REGISTRATION.txt](…) | what to type in the rule form |
| [JRXML_CONTRACT.txt](…) | fields, grouping, geometry |

**Rule**

```
Code                <Report_Name_In_Title_Case>
Name                <Report Name>
Category            Reports
Description         <one line>
Transaction End     false
Engine              SCRIPT
Enabled flags       none checked
Script              <file name>.groovy
```

**Input Parameters**

```
Name          Type       Class              Preset Value
<paramName>   REQUIRED   java.lang.Long     empty
<otherParam>  OPTIONAL   java.lang.String   empty
```

**Output Parameters**

```
Name   Type       Class
data   REQUIRED   java.util.List
```

**Report Registration** — after the rule is saved

```
Name / Code             <Report_Name_In_Title_Case>
Data Source Generator   <Report_Name_In_Title_Case>
Isolation               READ_UNCOMMITTED
Default Format          pdf
JRXML                   <name>.jrxml
```

**Verified** — <the specific checks that passed: contract both ways, sections and panels
agreeing, column grids summing, jrxml parsing, rule compiling.>

**Not verified** — <one line. "Not rendered; layout and pagination unproven" is the
floor, and it is always true.>

**Needs your input** — <each open question in one line, or omit the section.>
````

Rules for the last three sections:

- **Verified** names the checks you actually ran. "Verified" alone is worthless; "field contract matches both ways, jrxml parses" is auditable.
- **Not verified** is never empty. A local render (`verification/run.sh render`) proves geometry and pagination against *stub* rows; it cannot prove a traversal, because the stubs answer whatever the rule asks for. Real data, real pagination and every path are unproven until eSeries runs it.
- **Needs your input** is one line per question, no hedging paragraph around it. If a value is inferred rather than taken from an export, this is where it gets said.

Also mention, in one line each where they apply: whether the rule compiled, whether to Execute, and that rules are per-environment — "done" on QA is never "done" everywhere.

---

# Reports Admin — registering the report

The `.jrxml` is uploaded in Reports Admin; the report is joined to its rule through **Data Source Generator**.

```
/ecms/admin/reports                    index (Search / Clear / Import)
/ecms/admin/reports/onEdit?id=<id>     the registration
/ecms/admin/reports/import             upload a .jrxml — CREATES A NEW REPORT
/ecms/admin/reports/onReplace          the form target when replacing an existing .jrxml
/ecms/reports/run?id=<reportId>        run screen with input parameters
/ecms/reportsGenerate/run/<CODE>/onRun rendered output
```

Order of operations: **save the rule first**, because the report cannot reference it as Data Source Generator until it exists.

Registration fields, matching the existing reports in the corpus:

| Field | Value |
|---|---|
| Name / Code | e.g. `Certified_Discovery_Report` |
| Data Source Generator | the rule (stored as `rule:<Code>`) |
| Isolation | `READ_UNCOMMITTED` |
| Default Format | `pdf` |
| Parameters tab | auto-detected from the JRXML `<parameter>` declarations |

**Import creates, Replace updates.** Using Import to fix an existing report leaves a duplicate report behind. Before submitting a replace, confirm the form posts to `/onReplace`.

## Iterating and running

Editing loop, parameter mechanics, and diagnosis by symptom now live in the **`running-reports`**
skill, which is the canonical home for everything after the report is installed. It needs no source
files, which is why it is separable.

The two things most likely to bite mid-deploy, kept here so you do not have to leave the page:

- **Refresh means reload, not re-navigate.** The output page is a POST result. A fresh GET loses the
  parameters and returns *"Report with code null cannot be found."*
- **Query-string parameters are ignored and prior values are session-sticky**, so a GET-based test
  can look like it worked when the parameter was never read.

---

## The rule's importable twin

Before handing anything over, prove the zip is real and current — three commands, and they
have each caught something:

```bash
SK=report-deployment
K=$(for p in . .. ../.. ../../..; do for b in System/Skills .claude/skills; do
      [ -d "$p/$b/$SK" ] && { echo "$p/$b/$SK"; exit; }; done; done
    [ -d "$HOME/.claude/skills/$SK" ] && echo "$HOME/.claude/skills/$SK")
S=$K/scripts
python3 "$S/formexport.py" RULE-<Code>.zip        # registration + every parameter row
python3 "$S/rule_import.py" --selftest RULE-<Code>.zip   # only against a real platform export
```

1. **The zip exists.** A folder without one is an unfinished handover.
2. **Its script matches the `.groovy` byte for byte** after normalising CRLF to LF. If they
   differ, the zip predates the last edit — regenerate, do not reason about which is right.
   This is also how you settle which version is live in a folder holding `_V1` and `_V2`.
3. **Its parameter rows match `RULE_REGISTRATION.txt`** name for name, class for class,
   REQUIRED for REQUIRED. Two folders in `Claude Reports` disagreed on exactly one cell —
   `data` REQUIRED in the text, OPTIONAL in the zip — which is invisible until someone
   deploys from whichever artifact they happened to open.
