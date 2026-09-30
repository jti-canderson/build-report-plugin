# Validation - 0.34.0

What was run for this release, on 2026-09-30, on one macOS machine (JasperReports Server 9.0.0
at `/Applications/jasperreports-server-9.0.0`). Only results rerun for this release are here.

## Test suite

Run at commit `17f84e1`. The last code change is `ba3ca85`; after it only CHANGELOG.md, this
file and a README link changed.

| Run | core | integration |
|---|---|---|
| `python3 tests/run.py` (all switches at defaults: legacy verifier) | 161 passed, 0 failed | 19 passed, 0 failed |
| `JTI_VERIFIER=fast python3 tests/run.py` | 161 passed, 0 failed | 19 passed, 0 failed |
| `python3 tests/run.py --core-only` (HOME = empty temp dir) | 161 passed, 0 failed | 19 skipped (by design) |
| `--core-only` from the extracted release zip | see the release report | skipped (by design) |

The integration tier reads private platform exports in `~/Downloads` and the workspace's SDK
jar, so it runs only on a machine that has them. The core tier is self-contained.

## Browser run of `/build-report`

The built-in browser drove the page; the worker followed `commands/build-report.md` from a
release-like copy (`git archive` of the release candidate, extracted to a temp folder, found
through `CLAUDE_PLUGIN_ROOT`). Scratch workspace with one project holding a copy of the OKDAC
SDK jar and Data Dictionary. Report: *Release Check Cases*, 4 search criteria (pick-list IN,
date EQUALS, a defendant last name through Case › Parties › Person, a calculated field) and
6 columns (one calculated). Nothing was imported anywhere.

| # | Check | Result |
|---|---|---|
| 1 | launches the browser builder | pass - job server from the package, version 0.34.0 printed |
| 2 | opens on a clean form | pass after a fix - see "Found and fixed" |
| 3 | discovers projects and registered SDKs | pass - project, SDK and Data Dictionary found |
| 4 | Search Criteria and Result Columns browsers open automatically | pass |
| 5 | Quick Find, traversal, breadcrumbs | pass - Case › Parties (each) › Person, back via the breadcrumb |
| 6 | several criteria and result fields | pass - 4 criteria, 4 picked + 2 derived columns |
| 7 | lookup, date, related, calculated, computed fields | pass - CASE_TYPE values shown; related and calculated criteria matched after the search |
| 8 | a complete report submitted and built | pass after a fix (Wide Table) - every gate passed |
| 9 | questions and progress | pass - two questions asked and answered on the page; stages advanced in order |
| 10 | preview renders | pass - both pages shown; looked at |
| 11 | downloads are the verified current files | pass - all 7 files and the package match the disk byte for byte |
| 12 | reload resumes the active job | pass - reload mid-question came back to the open question |
| 13 | Done stops the waiting worker once | pass - exit 8; the next session's wait was not ended by it |
| 14 | closing the tab stops it after the grace | pass - stopped 5 s after the last builder page went away (see note) |
| 15 | reload is not mistaken for close | pass - two reloads, worker still waiting 10 s later |
| 16 | a new session does not reopen the previous build | pass |
| 17 | date-equals filters the whole day | pass - generated `addDateRange(dayStart, dayEnd)`; the gate checks it |
| 18 | real search rows are checked | pass - blank-run gate: each row carries exactly the report's fields |
| 19 | no unexplained console or server errors | pass - no page errors on load; one aborted event stream on navigation (expected); server log clean |
| 20 | cleanup | pass - scratch servers stopped, no workers left; all files in a temp folder |

Also seen: a stale file download is refused (409) and a request without the job token is
refused (403); a cancel ends the worker's next step with exit 6 and deletes nothing; a job in
progress survives a server restart; a builder from another copy is replaced when idle and kept
(with a message) while it holds a job.

**Note on 14.** In the in-app browser, closing a tab does not always unload the page (a
"closed" tab was reused later still open), so the close was exercised by navigating each
builder tab off the app, which fires the same `pagehide` beacon. The close in a regular
browser tab was confirmed by the user earlier the same day (exit 8, about 6 s).

### Found and fixed during the run

- **Wide Table could not be built** - `wide_table.build()` took no arguments, so scaffold
  refused it. Fixed; the sample layout is unchanged.
- **The form draft outlived a submitted build** - the next session opened pre-filled. Fixed.
- **A check-in in flight from a closed tab could cancel the close** - reproduced in the test
  harness (old code still waiting at 14 s). Fixed with a per-load page id.

The truncation gate also caught two values cut mid-word in the first layout; the worker
widened the columns, then asked on the page and switched to Wide Table. That is the gates
working, not a defect.

## Performance

`scripts/bench.py` on a copy of `OKDAC Reports/Defendant_Test`, 3 runs each (the report
folder is only read):

| Verifier | median wall | JVMs |
|---|---|---|
| legacy (default) | 21.87 s | 2 |
| fast (`JTI_VERIFIER=fast`) | 12.73 s | 1 |

The switches stay at their defaults for 0.34.0; see CHANGELOG.md.

## Package

`jti-reports-plugin-0.34.0-2026-09-30.zip`, made with `git archive` from the release commit
(`docs/` left out by `.gitattributes`). Its size, SHA-256 and the `--core-only` run from the
extracted copy are recorded in the release report, since a file cannot carry its own
package's checksum.

## Not verified

- A fresh Claude Code session running the installed `/build-report` end to end (the worker in
  the browser run was this release session following the command step by step).
- Grouped Summary and Statement builds (they cannot be scaffolded; see CHANGELOG.md).
- Any eSeries environment: nothing was imported or run on a server.
