#!/usr/bin/env bash
# Run all three gates in ONE command, from inside the report folder.
#
#   finish.sh <rule>.groovy <report>.jrxml --code CODE --name "Human Name" \
#             [--template NAME] [--description TEXT]
#
# WHY: the gates used to be three separate calls with a fix-and-rerun loop between them, and
# every one of those turns re-sends the whole conversation before it does anything. Three
# turns became one. The ORDER is the other half of the point - contract_check is instant and
# the render costs ~20s, so a contract fault must stop the run before the JVM ever starts.
#
# Stops at the first failed gate. Nothing here writes to an environment.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ $# -ge 2 ] || { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
RULE="$1"; JRXML="$2"; shift 2

for f in "$RULE" "$JRXML"; do
  [ -f "$f" ] || { echo "  no such file: $f"; exit 2; }
done

fail() { echo; echo "  GATE $1 FAILED - $2"; echo "  Fix it and re-run finish.sh. Later gates were not run."; exit 1; }

# REGENERATE FIRST. contract_check reads the .jrxml ON DISK, and the render is what
# rebuilds it from gen_jrxml.py - so checking before regenerating checks the PREVIOUS
# layout. Caught 2026-09-08 forward-testing: an edited generator was checked against the
# stale artifact. It failed loudly that time; the same ordering silently passes a stale
# layout whenever the old one happens to satisfy the contract, which is a false green.
if [ -f gen_jrxml.py ]; then
  echo "== 0/4  regenerate ========================================"
  python3 gen_jrxml.py || fail 0 "gen_jrxml.py failed"
  echo
fi

echo "== 1/4  contract =========================================="
python3 "$ROOT/templates/contract_check.py" "$RULE" "$JRXML" || fail 1 "the rule and the layout disagree"

echo
echo "== 1.5/4  rule executes ==================================="
# THE GATE THAT WAS MISSING. Everything else inspects TEXT - columns against fields,
# parameters against reads - and a rule that never assigned _data passed all of it and died
# on first use in eSeries (09/17). This RUNS the rule against a stub object graph and reads
# _data back out of the binding, so "produces no output" fails here instead of in front of
# a user.
#
# It proves the rule executes, returns rows, that every value is a String (a GString reaching
# a Jasper field is not), and that an unresolvable id still yields a page. It proves NOTHING
# about whether a traversal resolves - the fixture answers every property. Only eSeries
# settles that.
FX=verification/Fixture.groovy
if [ -f "$FX" ]; then
  SK="$ROOT/skills/jasper-reports"
  JRS="${JRS:-/Applications/jasperreports-server-9.0.0}"
  RC="$JRS/buildomatic/lib/groovy-3.0.13.jar:$JRS/apache-tomcat/webapps/jasperserver-pro/WEB-INF/lib/*"
  rlog=$(mktemp); rrc=0
  "$JRS/java/bin/java" -Djava.awt.headless=true -cp "$RC" groovy.ui.GroovyMain \
    "$SK/scripts/rulecheck.groovy" --rule "$RULE" --jrxml "$JRXML" --fixture "$FX" \
    >"$rlog" 2>&1 || rrc=$?
  grep -vE '^\s+at |^\s+\.\.\. |log4j|SLF4J|Illegal reflective|^$' "$rlog" || true
  rm -f "$rlog"
  [ $rrc -eq 0 ] || fail 1.5 "the rule did not execute cleanly"
else
  echo "  NO verification/Fixture.groovy - the rule was NOT executed, only inspected."
  echo "  Scaffold one, or copy the pattern from a recent report. A rule that is never run"
  echo "  can still fail on its first use in eSeries."
  RULE_NOT_RUN=1
fi

echo
echo "== 2/4  render ============================================"
if [ -x ./verification/run.sh ]; then
  ./verification/run.sh render || fail 2 "the jrxml did not compile or fill"
else
  # Not a pass. A missing harness means the layout is unproven, and saying so here is the
  # only place anyone would notice before the handoff claims it was verified.
  echo "  NO verification/run.sh - layout is UNPROVEN."
  echo "  Copy skills/jasper-reports/assets/run_template.sh and fill its PER-REPORT block."
  RENDER_SKIPPED=1
fi

echo
echo "== 3/4  truncation ========================================"
# A cell wider than its column is cut mid-word with no ellipsis and no error. _fits_width
# guards column HEADERS, which are known at generate time; row VALUES are not, so nothing
# guarded them and only a human who knew the intended text could catch it. Comparing the
# PDF against the fixture that produced it makes the cut loud.
clip=0
for p in verification/*_sample.pdf; do
  [ -f "$p" ] || continue
  v=$(basename "$p" _sample.pdf)
  f="verification/fixture_${v}.tsv"
  [ -f "$f" ] || continue
  python3 "$ROOT/scripts/cliphunt.py" "$p" "$f" || clip=1
done
[ "$clip" = 1 ] && fail 3 "a value was truncated - widen it, shorten it, or make the fixture carry the abbreviated form"
[ -f verification/fixture_full.tsv ] || echo "  (no per-variant fixtures - skipped)"

echo
echo "== 4/4  rule zip =========================================="
python3 "$ROOT/scripts/rule_zip.py" "$RULE" "$JRXML" "$@" || fail 3 "contract fault - no zip written"

echo
echo "== verdict ================================================"
ok=1
for f in "$RULE" "$JRXML" RULE-*.zip RULE_REGISTRATION.txt JRXML_CONTRACT.txt; do
  if [ -f "$f" ]; then echo "  ok      $f"; else echo "  MISSING $f"; ok=0; fi
done
[ "${RENDER_SKIPPED:-0}" = 1 ] && echo "  WARN    layout unproven - no render was run"
[ "${RULE_NOT_RUN:-0}" = 1 ] && echo "  WARN    rule never executed - no Fixture.groovy"
ls verification/*.pdf >/dev/null 2>&1 && echo "  ok      $(ls verification/*.pdf | wc -l | tr -d ' ') rendered PDF(s) - LOOK AT EVERY PAGE before reporting back"
[ "$ok" = 1 ] || exit 1
echo
echo "  All gates passed. Fill the NOTES blocks, then hand over the zip."
echo "  IMPORTING IS A WRITE - the user imports it, not you."
