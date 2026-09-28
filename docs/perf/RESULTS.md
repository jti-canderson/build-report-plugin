# Report build performance — results

Branch `perf/report-build-speed`, measured 28 September 2026 on the same machine as
[BASELINE.md](BASELINE.md). Legacy = `JTI_REPORT_BUILD_MODE` unset. Fast = `JTI_REPORT_BUILD_MODE=fast`.
Every run is on a temporary copy (`scripts/bench.py`); no real report folder was modified.

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
| 8 | Unknown field | **passes every gate** (ships a blank column) | plan path: refused at `resolve`, exit 20, nothing written | — |

Case 8 is not a regression: legacy has never caught it, because the fixture answers every property.

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

`python3 tests/run.py` → **63 passed, 0 failed, 0 skipped**, in legacy mode and in fast mode
(`JTI_REPORT_BUILD_MODE=fast python3 tests/run.py` runs every gate test through the fast verifier).
Baseline before the branch: 41 passed.

## Experiments that did not make it, or made little difference

- **Trimming the command or the reference files** for cost: negligible (cache reads are cheap).
  Targeted retrieval (Phase 4) is about context size, not per-call cost.
- **In-process Python post-steps** (raster, truncation): saves well under 0.5 s. Kept, since it
  costs nothing, but it is not where the time was.
- **A narrower classpath**, and a class-data-sharing archive: not attempted. Java 8 here has no
  application CDS, and a trimmed classpath risks missing a class some report needs.
- **Parallel rasterisation**: not worth it at ~0.1 s per page.
