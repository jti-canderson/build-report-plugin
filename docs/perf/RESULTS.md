# Report build performance — results

Branch `perf/report-build-speed`, measured 28 September 2026 on the same machine as
[BASELINE.md](BASELINE.md). Legacy = `JTI_REPORT_BUILD_MODE` unset. Fast = `JTI_REPORT_BUILD_MODE=fast`
(today: `JTI_VERIFIER=fast`; see the README's rollout switches). Every run is on a temporary copy
(`scripts/bench.py`); no real report folder was modified.

> **Measured BEFORE the harness marker (`d4529a9`).** The fast verifier now takes the one-JVM
> path only for a `verification/run.sh` carrying an exact, unmodified
> `JTI_SCAFFOLD_HARNESS_VERSION=1` marker, which only a scaffold run on this branch writes.
> **Every existing report is unmarked and now falls back to the legacy gates** (with the JIT flag
> passed through, so roughly the "fast fallback" figure in case 4, not cases 1–2). Cases 1 and 2
> were existing reports; their fast figures apply once a report is re-scaffolded, and were not
> re-measured after the marker. The regression suite does exercise the marked one-JVM path on a
> freshly scaffolded report on every run (1 JVM, 1 compile, 2 rule runs, counted).

## Verification wall time (median of 3)

| # | Case | Legacy | Fast | Change |
|---|---|---|---|---|
| 1 | Simple known template — Cases By Type (List, 2 variants) | 15.63 s | **8.82 s** | −44% |
| 2 | Folder-view report — Case_Financials (eSeries Screen, 2 variants) | 17.95 s | **9.33 s** | −48% |
| 3 | Brief-only report — plan-built probe (List, 2 variants) | 17.27 s | **8.85 s** | −49% |
| 4 | Multiple variants, old harness — OCDA Case Summary (5 variants, falls back) | 67.5 s | **45.5 s** | −33% |

Fast mode with the JIT flag turned **off** (`JTI_JVM_OPTS=""`), isolating the one-JVM change:
12.42 s (−21%) and 14.06 s (−22%) on cases 1 and 2. The rest of the gain is the flag.

## Processes

| | Legacy (scaffold harness) | Fast | Legacy (old harness, 5 variants) | Fast fallback |
|---|---|---|---|---|
| JVM launches | 2 | **1** | 7 | 7 (each faster) |
| JRXML compiles | 1 | 1 | 5 | 5 |
| Rule executions | 2 | 2 | 9 | 9 |
| `gen_jrxml.py` runs | 2 | **1** | 1–2 | 1–2 |
| Page rasterisations | 2 (AWT, overwritten) | **1** | 1 | 1 |

Fast counts are exact (counted inside the JVM); legacy counts are derived from the scripts.

## Stage by stage (case 1)

| Stage | Legacy | Fast |
|---|---|---|
| regenerate + contract | 0.1 s | 0.1 s |
| JVM start-up | (inside each gate) | 3.5 s, once |
| rule executes | 6.6 s (own JVM) | 1.3 s |
| render (compile + fill) | 10.0 s (own JVM, with raster) | 4.3 s |
| raster, truncation, package | 0.3 s | 0.2 s |

## Negative cases — each must fail at the same gate, with the same lines

| # | Case | Legacy | Fast | Same failure lines |
|---|---|---|---|---|
| 5 | Broken rule (`data =` instead of `_data =`) | gate 1, rc 1 | gate 1, rc 1 | yes |
| 5b | GString value | gate 1.5, rc 1 | gate 1.5, rc 1 | yes |
| 6 | Broken rule/JRXML contract | gate 1, rc 1 | gate 1, rc 1 | yes |
| 7 | Overlong fixture value | gate 3, rc 1 (16.1 s) | gate 3, rc 1 (8.2 s) | yes |
| 8 | Unknown field | **passes every gate** (ships a blank column) | plan path: exit 2 if any declaration is missing; exit 20 at `resolve` if fully declared but absent from the SDK; nothing written | — |

Case 8 is not a regression: legacy has never caught it, because the fixture answers every property.
The verifier alone (either mode) still does not catch it — only the build plan does, and the build
plan is opt-in.

## Artifact equivalence

Legacy vs fast on cases 1–4: declared parameters, declared and placed fields, the rule zip's
contents, `RULE_REGISTRATION.txt`, `JRXML_CONTRACT.txt`, PDF text, page counts, per-page raster
hashes and page images — **all agree**. The `.jrxml` agrees once the random element `uuid`
attributes are masked; the generator mints new ones on every run, with or without the gates.
Case 4 compared 5 PDFs, 7 pages, 7 page images.

## Model side

| | Before | After |
|---|---|---|
| Pauses in a complete builder submission | 2 (SDK confirm, brief-only columns) | **0** unless the SDK is missing, stale or unreadable |
| Field resolution, 3-entity traversal set | 6.5 s, 3 calls | **3.6 s, 1 call** |
| `model-facts.md` loaded | 868 lines, every build | **24–29%** for real queries, plus a one-line index |
| Precedent search | open folders one by one | **one call**, ranked, with that report's warnings |
| Mechanical build steps (scaffold → fixtures → gates → docs → inventory) | many calls | **one call** (`build_plan.py run`) |

**Not measured end to end:** model turns and tool calls for a whole real build in each mode. The
only historical baseline is one build (88 turns, 84 tool calls, 2 questions, 23.3 min active);
see BASELINE.md. A headless comparison was not run: the command text only reaches a build through
a fresh session loading this branch, and one run per mode would not be a meaningful sample.

## Tests

The suite has two tiers, counted separately (see the docstring of `tests/run.py`):
**core** is self-contained (fixtures, a temp workspace, a fake SDK jar compiled on the fly) and
**integration** reads private platform exports in `~/Downloads` and the real workspace's SDK jar.
Both need the local tools: JasperReports and PyMuPDF.

Recorded 28 September 2026, at the commit that introduced the tiers:

| Command | core | integration |
|---|---|---|
| `env -u JTI_REPORT_BUILD_MODE JTI_VERIFIER=legacy python3 tests/run.py --core-only` | 70 passed, 0 failed, 0 skipped | not run (19) |
| `env -u JTI_REPORT_BUILD_MODE JTI_VERIFIER=fast python3 tests/run.py --core-only` | 70 passed, 0 failed, 0 skipped | not run (19) |
| `env -u JTI_REPORT_BUILD_MODE JTI_VERIFIER=legacy python3 tests/run.py` | 70 passed, 0 failed, 0 skipped | 19 passed, 0 failed, 0 skipped |
| `env -u JTI_REPORT_BUILD_MODE JTI_VERIFIER=fast python3 tests/run.py` | 70 passed, 0 failed, 0 skipped | 19 passed, 0 failed, 0 skipped |

`--core-only` points HOME at an empty temp directory, so no integration input is reachable
(HOME only keeps a link to the plugin under test, which scaffolded reports load their templates
through, and `PYTHONUSERBASE` for PyMuPDF). The integration counts depend on what is in
`~/Downloads` on this machine and are not reproducible elsewhere.

An earlier version of this page claimed "63 passed, 0 failed, 0 skipped" in both modes; that
figure mixed in the `~/Downloads` tests without saying so, and is superseded by the table above.
Baseline before the branch: 41 passed (also mixed).

## Experiments that did not make it, or made little difference

- **Trimming the command or the reference files** for cost: negligible (cache reads are cheap).
  Targeted retrieval (Phase 4) is about context size, not per-call cost.
- **In-process Python post-steps** (raster, truncation): saves well under 0.5 s. Kept, since it
  costs nothing, but it is not where the time was.
- **A narrower classpath**, and a class-data-sharing archive: not attempted. Java 8 here has no
  application CDS, and a trimmed classpath risks missing a class some report needs.
- **Parallel rasterisation**: not worth it at ~0.1 s per page.
