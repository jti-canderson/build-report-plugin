#!/bin/bash
# <REPORT NAME> - local verification.
#
#   ./Verification/run.sh           assertions only, ~10s
#   ./Verification/run.sh render    + compile the jrxml, fill it three ways, geometry-check
#                                     and rasterise every page
#
# COPY THIS FILE for a new report. Change only the block marked PER-REPORT below. Everything
# generic lives in the jasper-reports skill's scripts/, so this file stays thin.
#
# What a green run proves: the rule executes, the row map matches the .jrxml field list key
# for key, every character survives PDF export, and the pages carry no geometric defect.
# What it does NOT prove: that any path exists on the real entity model. The fixture answers
# every property the rule asks for. Only an eSeries run settles that.
#
# IT ALSO DOES NOT REGENERATE THE .jrxml. This script verifies whatever .jrxml is on disk,
# so editing gen_jrxml.py and then running only this file verifies the OLD layout and calls
# it green. Run `python3 gen_jrxml.py <the jrxml>` first, every time. (Add that line to the
# PER-REPORT block if you would rather not remember it - nothing here depends on it being
# absent.)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FOLDER="$(dirname "$HERE")"

# Walk up for the skill rather than counting directory levels. A hard-coded ../../../..
# does not fail when it is wrong - it resolves to nothing, drops through to the $HOME
# fallback, and the harness keeps passing with a broken path. Report folders DO move
# (Case Summary Report moved clients on 2026-09-01), so never count levels.
if [ -z "${SKILL:-}" ]; then
    d="$FOLDER"
    while [ "$d" != "/" ]; do
        if [ -d "$d/System/Skills/jasper-reports" ]; then
            SKILL="$d/System/Skills/jasper-reports"; break
        fi
        d="$(dirname "$d")"
    done
fi
[ -d "${SKILL:-}" ] || SKILL="$HOME/.claude/skills/jasper-reports"
JRS="${JRS:-/Applications/jasperreports-server-9.0.0}"

# ---- PER-REPORT ---------------------------------------------------------------------
RULE="$FOLDER/Groovy/<Report_Name>_V1.groovy"
JRXML="$FOLDER/Jasper/<Report_Name>.jrxml"
FIXTURE="$HERE/Groovy/Fixture.groovy"
ASSERT="$HERE/Groovy/Assertions.groovy"
ROOT=Case          # the report's root entity
ID=19              # the fixture's id
VARIANTS="full empty missing"
# -------------------------------------------------------------------------------------

JAVA="$JRS/java/bin/java"
# The webapp lib directory, not buildomatic/lib: only it has JasperReports plus every
# transitive dependency (commons-codec for the logo, groovy-dateutil for Date.format)
# in one place.
CP="$JRS/buildomatic/lib/groovy-3.0.13.jar:$JRS/apache-tomcat/webapps/jasperserver-pro/WEB-INF/lib/*"

[ -x "$JAVA" ] || { echo "no JVM at $JAVA - set JRS to your JasperReports Server install"; exit 2; }

# JasperReports prints a wall of log4j/SLF4J noise on every invocation; drop it, or the
# real output scrolls away.
filter() { grep -vE 'log4j|SLF4J|Illegal reflective|WARNING: |^$' || true; }

groovy_run() { "$JAVA" -Djava.awt.headless=true -cp "$CP" groovy.ui.GroovyMain "$@"; }

echo "== rule contract =="
groovy_run "$SKILL/scripts/rulecheck.groovy" \
    --rule "$RULE" --jrxml "$JRXML" --fixture "$FIXTURE" \
    --root "$ROOT" --id "$ID" --assert "$ASSERT" 2>&1 | filter

if [ "${1:-}" = "render" ]; then
    OUT="$HERE/Out"
    mkdir -p "$OUT"
    # Render every variant a user eventually sees: the populated record, one that resolves
    # but holds nothing (empty panels must still say so), and an id resolving to nothing.
    for V in $VARIANTS; do
        echo ""
        echo "== render: $V =="
        ARGS=(--rule "$RULE" --jrxml "$JRXML" --fixture "$FIXTURE" --root "$ROOT" --id "$ID"
              --out "$OUT/sample_$V.pdf")
        [ "$V" = "full" ] || ARGS+=(--variant "$V")
        groovy_run "$SKILL/scripts/render.groovy" "${ARGS[@]}" 2>&1 | filter
        python3 "$SKILL/scripts/pdfcheck.py" "$OUT/sample_$V.pdf"
        # IF IT RENDERS, IT RASTERS. Never make this a step someone remembers: the PNGs are
        # the only artifact a human looks at, and when this was manual they fell silently
        # behind the PDFs - on 2026-09-01 a folder held rasters still showing two blank
        # columns three hours after that defect was fixed. A picture of a bug, looking
        # finished. Keep this line directly under pdfcheck.
        python3 "$SKILL/scripts/pdfraster.py" "$OUT/sample_$V.pdf"
    done
    echo ""
    echo "pages: $OUT/sample_*_p*.png  - LOOK AT THEM, and show them to the user."
fi
