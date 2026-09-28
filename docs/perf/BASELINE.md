# Report build performance — baseline (before optimisation)

Measured 28 September 2026 on branch `perf/report-build-speed` at commit `ebd9bed`
(= `main` 0.32.0 plus the committed quoted-parameter parser fix). No optimisation had been
made when these numbers were taken.

## Environment

| | |
|---|---|
| JVM | Java 1.8.0_241, an **x86 build running under Rosetta** on this Mac |
| JasperReports | Server 9.0.0; classpath = `groovy-3.0.13.jar` + all **486** jars in `WEB-INF/lib` |
| Harness | `scripts/bench.py` — temp copy of each report, JVMs counted by a shim `java` |
| Regression suite | `python3 tests/run.py` → **41 passed, 0 failed, 0 skipped**, 76.8 s wall |

## Two verification harnesses exist

Which one a report has decides its cost, so the distinction matters for every number below.

| | **scaffold harness** (what `scaffold.py` writes — every new build) | **asset template** (`skills/jasper-reports/assets/run_template.sh`, hand-copied) |
|---|---|---|
| Rule executed by | `finish.sh` gate 1.5 (`rulecheck.groovy`) | `finish.sh` gate 1.5 **and again** at the top of `run.sh` |
| Render | `render_check.groovy`, **all variants in one JVM**, fills from `fixture.py` TSVs | `render.groovy`, **one JVM per variant**, each re-runs the rule and re-compiles |
| Used by | 8 of the 10 reports with a harness | `OCDA Reports/Case Summary Report` (and `Config Change Audit`) |

`finish.sh` still tells a build to copy the asset template when no `run.sh` exists.

## Mechanical pipeline (`finish.sh`), median of 3 runs

| Report | Harness | Variants | Wall | JVMs | Time in JVMs | JRXML compiles | Rule runs |
|---|---|---|---|---|---|---|---|
| Test Builds / Cases By Type | scaffold | 1 | **15.63 s** | 2 | 14.6 s | 1 | 2 |
| Claude Reports / Case_Financials | scaffold | 2 | **17.95 s** | 2 | 16.0 s | 1 | 2 |
| OCDA Reports / Case Summary Report | asset template | 5 | **66.80 s** | 7 | ~67 s | 5 | 9 |

Compile and rule-run counts for these legacy runs are **derived** from the scripts'
semantics (see `bench.py` docstring); JVM counts are **exact** (shim).

### Where the scaffold path's time goes (Cases By Type, instrumented run)

| Stage | Seconds |
|---|---|
| regenerate (`gen_jrxml.py`) | 0.07 |
| contract (`contract_check.py`) | 0.06 |
| **rule executes** (`rulecheck.groovy`, 1 JVM) | **6.56** |
| **render** (`run.sh`: `gen_jrxml.py` again, `fixture.py` per variant, `render_check.groovy` 1 JVM, `pdfraster.py` per PDF) | **9.96** |
| truncation (`cliphunt.py` per PDF) | 0.21 |
| package (`rule_zip.py` + both docs, one process) | 0.08 |
| verdict | 0.03 |

**JVM time is ~93% of the wall clock.** Everything in Python together is ~1.6 s.

### The fixed cost of a JVM here

| | per JVM |
|---|---|
| empty Groovy script, default JIT | 2.01 s |
| empty Groovy script, `-XX:TieredStopAtLevel=1` (C1 only) | 1.28 s |
| `rulecheck.groovy` default → C1 only | 5.64 s → **3.30 s** (same 8 PASS) |
| `render_check.groovy` default → C1 only | 9.22 s → **5.95 s** (exit 0) |

### Duplicated work found

1. **Two JVMs where one would do** on the scaffold path: `rulecheck` and `render_check` pay
   JVM + Groovy start-up separately.
2. **Every page is rasterised twice**: `render_check.groovy` writes AWT PNGs, then `run.sh`
   re-rasters from the PDF with `pdfraster.py` under the same names, overwriting them.
3. **`gen_jrxml.py` runs twice**: `finish.sh` gate 0, then `run.sh` again.
4. **Asset-template path**: the rule runs in `finish.sh` *and* in `run.sh`, and the JRXML is
   compiled once per variant, each in its own JVM.
5. `finish.sh` labels a packaging failure `GATE 3` (it is gate 4). Cosmetic, but it misnames
   failures.

## Model side (from real session transcripts)

Only **one** fresh-session build in the history ran all the way to a passing `finish.sh`
without being a plugin-development session: **17 September 2026**.

| | |
|---|---|
| Model turns (API responses) | **88** |
| Tool calls | **84** (70 shell, 6 Read, 3 SendUserFile, 2 AskUserQuestion, 2 Skill) |
| Questions to the user | **2** |
| Active time | **23.3 min** |
| Waiting on the user | 1.4 min |
| `finish.sh` runs (fix loop) | 7 |

Time by stage for that build — model time producing each tool call, plus the call's own
execution — covering 14.3 min; the remaining ~9 min is text-only model output between calls:

| Stage | Minutes | Share | Calls |
|---|---|---|---|
| domain / field lookup (SDK, model-facts, corpus, precedents) | 2.9 | 21% | 31 |
| verification gates (`finish.sh` ×7) | 2.5 | 17% | 7 |
| rule authoring | 2.4 | 17% | 5 |
| questions to the user | 1.4 | 10% | 2 |
| PDF inspection (reading page images) | 1.3 | 9% | 3 |
| fixture creation | 0.9 | 7% | 3 |
| handoff | 0.9 | 6% | 9 |
| rendering (`run.sh`) | 0.8 | 6% | 1 |
| packaging, scaffolding, intake, other | 1.2 | 8% | 23 |

Caveat: one build is an anecdote, not a distribution. The other completed builds in the
history ran inside development sessions (hundreds of turns, days open) and are not
representative of real use. Controlled headless comparisons are in `RESULTS.md`.

## Deterministic vs judgment

| Deterministic — belongs in scripts, not in the model's loop | Needs judgment — stays with the model |
|---|---|
| reading the spec; project and SDK status | deriving columns from a brief |
| batch field resolution against the SDK | choosing the root entity and traversals when not given |
| scaffolding, JRXML generation, fixture plumbing | writing the rule's business logic |
| contract, rule execution, render, truncation, raster | writing awkward fixture rows that stress the layout |
| rule zip, registration and contract tables | the NOTES blocks: what is and is not proven |
| artifact inventory | looking at the rendered pages |
| choosing a precedent from indexed metadata | deciding the report is financial and needs the financials skill |
