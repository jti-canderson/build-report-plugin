// Groovy syntax/AST gate for eSeries business rules.
// Parses to Phases.CONVERSION -- no class resolution, so eSeries types (PMInstrument,
// DirOrgUnit, logger, ...) need NOT be on the classpath. Proves the script parses; proves
// nothing about behaviour.
//
// Usage (no Groovy install needed -- runtime comes from the VS Code gradle extension):
//   JAR="$HOME/.vscode/extensions/vscjava.vscode-gradle-3.18.0/lib/groovy-eclipse-batch-4.0.16-03.jar"
//   JAVA="$HOME/.vscode/extensions/redhat.java-1.55.0-darwin-arm64/jre/21.0.11-macosx-aarch64/bin/java"
//   "$JAVA" -cp "$JAR" groovy.ui.GroovyMain parsecheck.groovy <rule>.groovy
//
// Verified 2026-09-01 with a negative control: removing one quote fails at the right line.

import org.codehaus.groovy.control.CompilationUnit
import org.codehaus.groovy.control.Phases

if (!args) { println "usage: parsecheck.groovy <file.groovy> [more.groovy ...]"; System.exit(2) }

int failed = 0
args.each { a ->
    def f = new File(a)
    if (!f.exists()) { println "MISSING: ${a}"; failed++; return }
    def cu = new CompilationUnit()
    cu.addSource(f)
    try {
        cu.compile(Phases.CONVERSION)
        println "PARSE OK: ${f.name} (${f.readLines().size()} lines)"
    } catch (Throwable t) {
        println "PARSE FAILED: ${f.name}"
        println t.message
        failed++
    }
}
System.exit(failed ? 1 : 0)
