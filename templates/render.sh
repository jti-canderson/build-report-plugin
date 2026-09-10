#!/bin/sh
# Generate, compile, fill, export and raster one template.
#   ./render.sh templates/record_summary.py
# Renders BOTH the populated and the empty variant every time: an empty result is a
# page a client eventually sees, and it must still be branded.
set -e
JRS=${JRS:-/Applications/jasperreports-server-9.0.0}
JAVA="$JRS/java/bin/java"
CP="$JRS/buildomatic/lib/groovy-3.0.13.jar:$JRS/apache-tomcat/webapps/jasperserver-pro/WEB-INF/lib/*"
[ -x "$JAVA" ] || { echo "no JVM at $JAVA - set JRS to your JasperReports Server install"; exit 2; }
cd "$(dirname "$0")"
mkdir -p out
T="$1"; [ -n "$T" ] || { echo "usage: ./render.sh templates/<name>.py"; exit 1; }

NAME=$(python3 -c "import re,sys;print(re.search(r'^NAME = \"(.+)\"',open(sys.argv[1]).read(),re.M).group(1))" "$T")
rm -f "out/${NAME}"_*_p*.png 2>/dev/null || true
python3 "$T"
python3 fixtures.py "$NAME"

# ONE JVM for both variants: the compile is done once and each fixture filled from it.
# Two processes paid ~5.8s of JVM and JasperReports startup twice for identical output.
# In a pipeline $? is GREP's status, not the render's, so a CONTRACT FAIL exit(3) is
# swallowed and the build reports success. Capture the status, THEN filter.
# `|| rc=$?` and not a bare call: under `set -e` a failing JVM aborts the script here,
# before the captured log is printed, so the failure arrives with no diagnostic.
log=$(mktemp); rc=0
"$JAVA" -Djava.awt.headless=true -cp "$CP" groovy.ui.GroovyMain render_check.groovy \
  "out/$NAME.jrxml" --out out \
  --variant "${NAME}_sample=out/$NAME.tsv" \
  --variant "${NAME}_empty=out/$NAME.tsv:empty" >"$log" 2>&1 || rc=$?
grep -vE '^\s+at |^\s+\.\.\. |log4j|SLF4J|Illegal reflective|font "Times"|^$' "$log" || true
rm -f "$log"
[ $rc -eq 0 ] || { echo "  render FAILED (exit $rc)"; exit $rc; }

# The PNGs render_check writes come from JasperPrintManager.printPageToImage, which draws
# through AWT and shows ANY glyph the JVM font has. The PDF is exported through WinAnsi and
# silently drops everything outside it. Re-rastering from the PDF here overwrites those PNGs
# with what the document ACTUALLY contains, so the page a human inspects is the page that
# ships. Same filenames, so nothing downstream changes.
for f in out/"$NAME"_sample.pdf out/"$NAME"_empty.pdf; do
  [ -f "$f" ] && python3 ../skills/jasper-reports/scripts/pdfraster.py "$f" >/dev/null
done
