/*
 * verify.groovy - the rule gate and the render gate in ONE JVM.
 *
 *   verify.groovy --skill <skills/jasper-reports> --tpl <templates>
 *                 --rule R.groovy --jrxml R.jrxml [--fixture Fixture.groovy]
 *                 --out verification --variant full_sample=verification/fixture_full.tsv ...
 *
 * WHY: a JVM here costs ~2s before any work and JasperReports class init more on top, and
 * the build started TWO of them back to back - rulecheck.groovy for gate 1.5, then
 * render_check.groovy for gate 2. Measured 2026-09-28: 6.6s and 10.0s of a 17s gate run.
 *
 * HOW, AND WHY IT CANNOT DRIFT FROM THE LEGACY GATES: this does not re-implement a single
 * check. It RUNS the two existing scripts, unchanged, one after the other in this JVM:
 *
 *   1. rulecheck.groovy  with the exact arguments finish.sh passes it
 *   2. render_check.groovy with the exact arguments run.sh passes it, plus --no-raster
 *      (pdfraster.py redoes the pages from the PDF afterwards, as run.sh always did)
 *
 * Every PASS/FAIL line, every CONTRACT FAIL, every exception is theirs. Three things make
 * sharing one JVM safe:
 *
 *   - System.exit is TRAPPED. Both scripts end a failure with System.exit; unhandled, the
 *     first one would kill the JVM before the second ran. Groovy dispatches their calls
 *     through the metaclass, so System's static exit is replaced for the duration and the
 *     code is carried out as an ExitTrap.
 *   - rulecheck's one GLOBAL change is undone. When groovy-dateutil is absent it adds
 *     Date.format(String) to Date's metaclass. In the legacy layout render_check never saw
 *     that - separate JVM - so it is removed again before the render, to keep the render's
 *     world exactly what it was.
 *   - Everything rulecheck defines (the root-entity stub, Where, DomainObject...) lives in
 *     its own GroovyClassLoader, invisible to JasperReports' compiler.
 *
 * Output ends with two machine lines the orchestrator reads:
 *   VERIFY-RESULT {"gate":"rule"|"render"|null,"rc":n}
 *   VERIFY-STATS  {"jvms":1,"compiles":n,"rule_evals":n,"counts":"exact"|"derived",...}
 * Counts are EXACT - taken from the calls themselves - unless instrumenting them failed, in
 * which case they fall back to the scripts' known semantics and say "derived".
 */
import net.sf.jasperreports.engine.JasperCompileManager
import net.sf.jasperreports.engine.DefaultJasperReportsContext

class ExitTrap extends RuntimeException {
    int code
    ExitTrap(int c) { super("System.exit(" + c + ")"); code = c }
}

def argv = [:]; def variants = []
for (int i = 0; i < args.size(); i++) {
    if (args[i] == "--variant") { variants << args[++i]; continue }
    if (args[i].startsWith("--")) { argv[args[i].substring(2)] = args[i + 1]; i++ }
}
["skill", "tpl", "rule", "jrxml", "out"].each {
    if (!argv[it]) { System.err.println "verify.groovy: missing --${it}"; Runtime.getRuntime().exit(2) }
}
def ruleFile = new File(argv.rule).canonicalFile
def t = [start: System.nanoTime()]
def secs = { long a, long b -> Math.round((b - a) / 1e7) / 100.0 }
def stats = [jvms: 1, compiles: 0, rule_evals: 0, counts: "exact"]

// ---- instrumentation: exact counts, or honest fallback --------------------------------
try {
    JasperCompileManager.metaClass.static.compileReport = { String src ->
        stats.compiles++
        JasperCompileManager.getInstance(DefaultJasperReportsContext.getInstance()).compile(src)
    }
    GroovyShell.metaClass.evaluate = { File f ->
        if (f.canonicalFile == ruleFile) stats.rule_evals++
        delegate.parse(f).run()
    }
} catch (Throwable e) {
    stats.counts = "derived"
    System.err.println "verify.groovy: counting unavailable (${e.class.simpleName}) - counts are derived"
}
System.metaClass.static.exit = { int c -> throw new ExitTrap(c) }

def runScript = { File script, List a ->
    try {
        new GroovyShell(this.class.classLoader, new Binding()).run(script, a as String[])
        return 0
    } catch (ExitTrap x) {
        return x.code
    } catch (Throwable e) {
        // what GroovyMain would have printed before exiting 1: the error, not the stack wall
        System.err.println "Caught: ${e}"
        def cause = e
        while (cause.cause && cause.cause != cause) cause = cause.cause
        if (cause != e) System.err.println "  caused by: ${cause}"
        return 1
    }
}

def result = [gate: null, rc: 0]

// ---- gate 1.5: the rule executes (skipped, as in finish.sh, when there is no fixture) --
if (argv.fixture && new File(argv.fixture).exists()) {
    def dateHad = Date.metaClass.respondsTo(new Date(), 'format', String)
    t.ruleStart = System.nanoTime()
    def rc = runScript(new File(argv.skill, "scripts/rulecheck.groovy"),
                       ["--rule", argv.rule, "--jrxml", argv.jrxml, "--fixture", argv.fixture])
    t.ruleEnd = System.nanoTime()
    if (!dateHad) GroovySystem.metaClassRegistry.removeMetaClass(Date)
    if (rc != 0) result = [gate: "rule", rc: rc]
} else if (stats.counts == "exact") {
    // nothing ran, so nothing to count
}

// ---- gate 2: compile once, fill every variant ----------------------------------------
if (result.gate == null) {
    // Clear the previous render's pages NOW - after the rule gate passed, before the fill -
    // which is when run.sh used to. A failing rule leaves the last good pages in place,
    // exactly as before; a passing one cannot leave stale pages behind a shorter render.
    def od = new File(argv.out)
    od.listFiles()?.findAll { it.name.endsWith(".pdf") || it.name ==~ /.*_p\d+\.png/ }*.delete()
    // --awt-raster keeps render_check's own page images: the caller passes it when PyMuPDF
    // is missing and pdfraster.py therefore cannot draw them from the PDF afterwards.
    def ra = [new File(argv.jrxml).absolutePath, "--out", argv.out]
    if (!argv['awt-raster']) ra << "--no-raster"
    variants.each { ra += ["--variant", it] }
    t.renderStart = System.nanoTime()
    def rc = runScript(new File(argv.tpl, "render_check.groovy"), ra)
    t.renderEnd = System.nanoTime()
    if (rc != 0) result = [gate: "render", rc: rc]
}

if (stats.counts == "derived") {
    stats.compiles = (result.gate == "rule") ? 0 : 1
    stats.rule_evals = (argv.fixture && new File(argv.fixture).exists()) ? 2 : 0
}
stats.rule_secs = t.ruleEnd ? secs(t.ruleStart, t.ruleEnd) : 0
stats.render_secs = t.renderEnd ? secs(t.renderStart, t.renderEnd) : 0
stats.jvm_secs = secs(t.start, System.nanoTime())

def js = { m -> groovy.json.JsonOutput.toJson(m) }
println "VERIFY-RESULT " + js(result)
println "VERIFY-STATS " + js(stats)
System.out.flush()
Runtime.getRuntime().exit(result.rc == 0 ? 0 : result.rc)
