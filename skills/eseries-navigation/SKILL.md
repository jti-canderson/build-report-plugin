---
name: eseries-navigation
description: >-
  Find your way around the OKDAC/eProsecutor (Sustain/Symphony) eSeries admin and case
  screens — which left-nav path leads where, the URL pattern for every admin screen, how to
  jump from a rendered case tab to the config behind it, and which environment you are
  actually on. Use this whenever you need to reach a screen ("where do I change X", "open
  the folder view for this tab", "how do I get to Reports Admin", "what's the URL for the
  rule editor") or when a page 404s, returns "Report with code null cannot be found", or
  shows unfamiliar config. This is the single home for eSeries navigation: other eSeries
  skills cover what to do once you are on a screen, not how to get there.
---

# Getting around eSeries

This skill is only about **reaching** screens and knowing **which environment** you are on. What to do once you arrive lives in the task skills (`jasper-reports`, `business-rules`, `folder-view-forms`, `adding-entities`, `velocity-widgets`, `system-properties`).

## Identify the environment first, every time

Hosts look alike and none of them are safe to confuse:

| Host | Page title says |
|---|---|
| `ocda-config-symphony.ecourt.com` | eProsecutor Baseline QA |
| `okdac-qa-symphony.ecourt.com` | OKDAC eProsecutor QA |
| `ocda-master-symphony.ecourt.com` | OCDA Master |
| `conv-orangecounty-ca.journaltech.com:8443` | OCDA-ConversionTest |
| `NN-pcms-app.dac.ok.gov/NN` | District NN eProsecutor (D04, D06, …) |

**Read the environment from the page title, not from habit.** District deployments carry the district as a path segment (`/04/ecms/...`), so any URL you build must tolerate it — derive the app root from `location.pathname` rather than hardcoding `/ecms/`.

Config does not sync between environments: a rule, form, or report id on QA means nothing on master.

So **scope every question and every answer to an environment.** "Does this field exist", "is that lookup list there", "which widgets are available" all have different answers per box — ask which environment before answering, and say which one your answer covers. Prefer codes over ids for anything that must travel.

## The left nav

Top level: Workspace, Add Record/Add Case, Searches, Reports, External Links, Financials, Financial Setup, Super Users, **System Setup**, **System Admin**.

- **System Setup** → Navigation, Security, *Screens*, *Metadata*, *Business Process*, Documents, Directory, Accounting, Statutes, Calendar Definitions, News Gadget, Manage Special Statuses, **Reports Admin**, Checklists, Questionnaires, Evidence.com Admin, Configuration Management
- **System Setup → Screens** → New Case Forms, Add Forms, Update Forms, **Folder Views**, Search Forms, Header Forms, Screen Index
- **System Setup → Metadata → Entities** → the entity list, and **Download SDK** at the top right. That button is where the environment's SDK jar comes from — the jar that makes the domain model answerable offline (`javap`, class lookups). It is the answer to "where do I get the JAR/SDK", which is not guessable from the button's placement.
- **System Setup → Business Process** → Conditions, **Business Rules**, Workflows, **Velocity Test**, **Templates**, **Widgets**, SMS/Email Templates, SQL Widget
- **System Admin** → **System Properties**, System Status, System Access Log, System Audit Log, System Emails, System Documentation, System Tests, Performance, Icons, Interface Search

Two quirks: the nav's **Search Navigation** box matches only nav-item labels (searching "url" finds nothing), and tree nodes are collapsed — their child links do not exist in the DOM until the parent is expanded (`Screens`, `Metadata`, `Business Process` are all toggles).

## URL patterns

**Case screens**
```
/ecms/case?formId=<formId>&id=<caseId>&caseId=<caseId>&caseNumber=<num>
/ecms/drive?caseNumber=<num>&caseId=<id>&id=<id>
/ecms/case/insert?formId=<id>&caseId=<id>&parentEntity=<E>&parentId=<id>&data(FIELD)=VALUE
```

**Forms (folder views)**
```
/ecms/admin/forms/list/folders        index   (NOTE: /ecms/admin/forms alone 404s)
/ecms/admin/forms/edit?id=<formId>    form editor
/ecms/admin/forms/item/edit?id=<itemId>   single item — a full page, not a modal
/ecms/admin/forms/widget              custom screen widgets index
```

**From a rendered screen to its config:** the small square-with-pencil icon beside a tab or panel header opens that form's editor in a new tab. That is the fastest route from "this grid looks wrong" to the config that drives it, and it tells you the formId. Inside the form editor, **Expand All** reveals every panel's items.

**Entity metadata**
```
/ecms/admin/metadata/entities                              index
/ecms/admin/metadata/entities/onView?entityName=<class>    read-only view
/ecms/admin/metadata/entities/edit?entityClassName=<class> editor
```
Class names are fully qualified and the package varies by area: `com.sustain.entities.custom.C_*` (custom entities), `com.sustain.discovery.*`, `com.sustain.document.model.*`, `com.sustain.cases.model.*`. Pull exact names off the index page's links rather than guessing a package.

**Business rules**
```
/ecms/admin/rule/search                 index (searchable by code, name, category, engine, groovy text)
/ecms/admin/rule/edit/onView?id=<id>    rule editor
/ecms/admin/rule/edit/onView            blank/new rule
```
The index's result table shows Category, Engine, **# Usages**, **Inputs**, and observed runtimes — the quickest way to find a comparable rule and copy its conventions.

**Velocity and templates**
```
/ecms/admin/velocity      Velocity Test (pick Entity + Id, paste, Test)
/ecms/admin/templates     named Velocity templates ($Template.run('CODE', $object))
```

**Reports**
```
/ecms/admin/reports                    Reports Admin index (Search / Clear / Import)
/ecms/admin/reports/onEdit?id=<id>     report registration
/ecms/admin/reports/import             upload a .jrxml (CREATES a new report)
/ecms/admin/reports/onReplace          form target when replacing an existing .jrxml
/ecms/reports/run?id=<reportId>        run screen with input parameters
/ecms/reportsGenerate/run/<CODE>/onRun rendered output
```
Two traps worth knowing before you touch these:

- **Import creates, Replace updates.** Using Import to fix an existing report leaves you with a duplicate.
- **The output page is a POST result.** Reload it to see changes after editing a rule or replacing the jrxml; navigating to that URL fresh loses the parameters and returns *"Report with code null cannot be found"*, destroying whatever the user was looking at.

**System properties, logs, docs**
```
/ecms/admin/sysProperties       ~2600 properties, 50/page; Search matches VALUES as well as keys
/ecms/audit                     audit log — case-data entities only, not config metadata
/ecms/search                    system access log
/ecms/admin/documentation       system documentation
```

**Platform endpoints you will see in rendered markup**
```
/ecms/forms/support/onWidgetRequest?name=<Widget>&action=<action>&entityId=<id>&entity=<Entity>
/ecms/doc?docId=<id>  |  /ecms/doc?storageId=<id>&storageType=<t>
/ecms/forms/blobFile?entity=<E>&id=<id>&fieldName=<field>
```
Compiled widgets use the first one; that is how `ReceiptIcon` and `GenericDownload` do their work.

## Working habits that save time

- **Ids are per-environment.** A form, rule, report or item id is a primary key on that host only. Prefer codes (`Certified_Discovery_Report`, `FV-Case-Referral`) when something has to be portable.
- **Open a second tab** before navigating away from any page holding unsaved state — the form editor, an entity editor, a rule with staged edits. A navigation discards it silently.
- **Report parameters are session-sticky**, so a value you entered earlier reappears and can make a test look like it passed.
- A standing banner *"Metadata has been altered, please restart system for changes to take effect"* means metadata edits are pending a restart; actions attempted mid-restart fail with `Unexpected error: 0`.
- Close tabs you opened when you are done, and leave the user's own tabs alone.
