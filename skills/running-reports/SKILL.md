---
name: running-reports
description: >-
  Run an eSeries (Sustain / Symphony) Jasper report that already exists, read its output, and
  diagnose a run that failed or came back wrong. Use for "run this report", "the report is blank",
  "the column is empty", "Report with code null cannot be found", "the totals don't match the
  screen", "how do I pass parameters", or a screenshot of a report output tab. This is the layer
  after the report is built and deployed — it needs no source files, so it is the part of the
  knowledge that travels without the report corpus. Building the rule and .jrxml is `jasper-reports`;
  registering and installing them is `report-deployment`.
---

# Running an eSeries report

You do not need the `.groovy` or the `.jrxml` to run a report or to diagnose most failures. You need
the report's **code**, its **parameters**, and the **environment**. That is why this knowledge is
separable from the corpus.

## Where a report runs

```
/ecms/admin/reports                      index — Search / Clear / Import
/ecms/admin/reports/onEdit?id=<id>       the registration (code, data source, format)
/ecms/reports/run?id=<reportId>          the run screen, with input parameters
/ecms/reportsGenerate/run/<CODE>/onRun   the rendered output
```

A report is joined to its Groovy rule through **Data Source Generator**, stored as `rule:<Code>`.
Registration also fixes **Isolation** (`READ_UNCOMMITTED`) and **Default Format** (usually `pdf`).
The Parameters tab is auto-detected from the `<parameter>` declarations in the `.jrxml`.

## How parameters actually travel — the part that misleads people

Parameters go in the **POST body**, as `reportParams[N].name` / `reportParams[N].value`, alongside
`format` and a `_csrf` token.

Two consequences, and both produce false confidence:

- **Query-string parameters on the run screen are ignored.** A URL with `?param=value` appended does
  nothing.
- **Previously entered values are session-sticky.** A GET-based test can return a correct-looking
  report using values left over from an earlier run — so it looks like the parameter worked when it
  was never read.

If you are verifying that a parameter is wired correctly, change its value to something that must
visibly change the output, and submit the form rather than crafting a URL.

## Iterating on a report you are changing

Edit the Groovy (**Compile & Save**) or **Replace** the `.jrxml`, then **refresh the report's output
tab**. There is no need to walk back through Reports Admin or re-enter parameters.

**Refresh means reload, not re-navigate.** The output page is a POST result. A fresh GET to that URL
loses the parameters, returns *"Report with code null cannot be found"*, and destroys the tab the
user was looking at.

## Diagnosing by symptom

| Symptom | What it almost always means |
|---|---|
| **Blank page**, every step reported success | The rule has no **output parameter** declared. The page renders, empty, with no error anywhere. |
| **"Report with code null cannot be found"** | A GET was issued against the output URL. Re-run from the run screen; do not reload by navigation. |
| **One column empty**, the rest correct | The `.jrxml` declares a field the rule never assigns, or the rule's path is wrong. Groovy is dynamically typed, so a property typo survives compilation and surfaces as an empty column. |
| **Every row identical, or the wrong record** | Usually a scope problem in the data, not the layout. If a launcher invoked the report, suspect the widget's `$object` scope first — see `velocity-widgets`. |
| **Totals disagree with the case screen** | A money path issue, not a rendering issue. Payments allocate down two separate branches plus an assessment side. See `financials` before touching the layout. |
| **Duplicate rows** | A traversal that fans out — a join through a to-many relation without a dedupe. |
| **Report missing from Reports Admin after an "install"** | Import **creates**; Replace **updates**. An Import used to fix an existing report leaves a duplicate behind under a near-identical name. |

## What a clean run does and does not prove

A report that renders is not a report that is correct. It proves the contract between rule and jrxml
holds for the rows returned — nothing about whether those are the right rows.

Verification that actually means something: run it against a case whose expected values you can read
off a screen, and compare figure by figure. Say which case, which environment, and which figures were
checked. **"It ran" is not a verification result.**

Reports cannot be rendered inside eSeries locally. Where a local JVM, Groovy, and the JasperReports
jars are available, a static harness can compile the `.jrxml` and fill it from stubbed data — but
stubs answer every property, so a green local run **cannot prove a traversal**. Say both halves.

## Before you run anything

**Name the environment.** QA, Master, ConversionTest, and district deployments are different systems
with different primary keys and different lookup lists. A report id or code without an environment
names nothing, and a report that is correct in QA can return different rows in a district.

Running a report is a read. It needs no special authorization. **Registering, replacing, importing,
or saving a rule is a write** and does not belong to this skill — that is `report-deployment`, and it
stops for a human to press the button.
