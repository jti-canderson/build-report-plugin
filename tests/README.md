# Regression suite

```bash
python3 tests/run.py        # -v for detail on passing tests too
```

Exits non-zero on any failure. Takes about a minute, most of it two renders.

## Why it exists

Every defect in this plugin was found by hand, and two were regressions:

- `scaffold.py` silently stopped calling `rulecheck.groovy`, so a rule that produced no
  output passed every gate and failed the first time it ran in eSeries.
- the builder page hand-copied the project filter and immediately disagreed with
  `project.py list`.

A gate that can quietly disappear is not a guarantee. **These tests make a missing gate fail
the same day.** Verified by deleting each of the two gates in turn and watching the suite go
red — the `_data` check and the rule-execution gate each take their own tests down.

## How it works

A known-good report (`fixtures/`) is scaffolded into a temp workspace, then every negative
test copies it, breaks exactly ONE thing, and asserts the RIGHT gate rejects it. The
baseline runs first: if the good report stops passing, everything below is noise, so the
suite stops there rather than reporting fifteen confusing failures.

A negative test has to actually break something. The truncation test first used a 62-char
value in a column that holds ~85 and passed for the wrong reason — it proved nothing until
the value got longer than the column.

Tests needing JasperReports **skip loudly** when it is absent. A skip is not a pass.

## Adding one

When a defect gets through, add the test in the same change as the fix. The shape is:

```python
b = mutate(good, ws, "tag", lambda f: edit(rule(f), "the good line", "the broken line"))
rc, out = gates(b)
check("a plain sentence describing what must be rejected", rc != 0 and "marker" in out, out)
```
