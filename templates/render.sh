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

run() {
  "$JAVA" -Djava.awt.headless=true -cp "$CP" groovy.ui.GroovyMain render_check.groovy \
    "out/$NAME.jrxml" "out/$NAME.tsv" $1 2>&1 \
    | grep -vE '^\s+at |^\s+\.\.\. |log4j|SLF4J|Illegal reflective|font "Times"|^$'
}
run
run empty
