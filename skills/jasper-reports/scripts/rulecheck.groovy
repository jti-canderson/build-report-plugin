/*
 * rulecheck.groovy — run an eSeries report rule off-platform and assert its contract.
 *
 *   groovy rulecheck.groovy --rule R_V1.groovy --jrxml R.jrxml --fixture Fixture.groovy
 *                           [--root Case] [--id 19] [--assert Assertions.groovy]
 *
 * What it proves: the rule EXECUTES, and the row map it emits matches the field list the
 * .jrxml declares, key for key, all Strings, no literal "null".
 *
 * What it does NOT prove: that any path exists on the real entity model. The fixture
 * answers every property the rule asks for, so a green run says nothing about whether
 * `party.cf_preferredAddress` is real. Only eSeries settles that. Say so when reporting.
 *
 * The fixture is a plain Groovy script that sets ROOT_FIXTURE in its binding to a nested
 * Map graph. Maps, not Expandos: a missing key answers null, which is exactly how the
 * rule's guarded accessors expect an absent property to behave.
 */
import java.text.SimpleDateFormat

def argv = [:]
def extra = []
for (int i = 0; i < args.size(); i++) {
    if (args[i].startsWith("--")) { argv[args[i].substring(2)] = args[i + 1]; i++ }
    else extra << args[i]
}
["rule", "jrxml", "fixture"].each {
    if (!argv[it]) { System.err.println "missing --${it}"; System.exit(2) }
}
def ROOT = argv.root ?: "Case"
def ID   = argv.id ?: "19"

// groovy-dateutil carries Date.format(String) and is not always on a bare classpath;
// eSeries always has it. Emulate it rather than let the rule's date handling go untested.
if (!Date.metaClass.respondsTo(new Date(), 'format', String)) {
    Date.metaClass.format = { String f -> new SimpleDateFormat(f).format(delegate) }
}

def gcl = new GroovyClassLoader(this.class.classLoader)
// The rule calls e.g. Case.get(id). Define that class in the shell's own loader so the
// name resolves, without needing a stub file per root entity.
def rootClass = gcl.parseClass("""
class ${ROOT} {
    static Object FIXTURE
    static Long FIXTURE_ID
    static Object get(Long id) { id == FIXTURE_ID ? FIXTURE : null }
    static Object get(Object cls, Long id) { get(id) }   // the two-arg form some entities need
    // The platform hands ids over as Strings, and rules call Case.get(str(_CaseId)).
    static Object get(String id) { get(id?.isLong() ? id.toLong() : -1L) }
}
""", "\${ROOT}.groovy")

// The platform API a search rule reaches for. Without these the rule does not COMPILE
// off-platform, so nothing runs and the only gates left are text inspection - which is how
// a rule that never assigned _data shipped on 09/17.
//
// These are stubs with the real SHAPES, not the real behaviour: find() returns whatever the
// fixture put in SEARCH_RESULTS, getLabel() echoes the code. That is enough to prove the
// rule executes, produces _data, and survives an empty result - and it proves NOTHING about
// whether a traversal resolves. Only eSeries settles that; say so when reporting.
//
// The addX list is the one attested in production (references/criteria-api.md). A rule
// calling something absent here fails loudly, which is the right outcome: an unattested
// criteria method is a finding, not a convenience to paper over.
gcl.parseClass("""
class Where {
    List conditions = []
    private Where rec(String op, Object... a) { conditions << [op: op, args: a as List]; this }
    Where addEquals(Object... a)              { rec('addEquals', a) }
    Where addNotEquals(Object... a)           { rec('addNotEquals', a) }
    Where addIn(Object... a)                  { rec('addIn', a) }
    Where addNotIn(Object... a)               { rec('addNotIn', a) }
    Where addContains(Object... a)            { rec('addContains', a) }
    Where addLessThan(Object... a)            { rec('addLessThan', a) }
    Where addLessThanOrEquals(Object... a)    { rec('addLessThanOrEquals', a) }
    Where addGreaterThan(Object... a)         { rec('addGreaterThan', a) }
    Where addGreaterThanOrEquals(Object... a) { rec('addGreaterThanOrEquals', a) }
    Where addDateRange(Object... a)           { rec('addDateRange', a) }
    Where addDayRange(Object... a)            { rec('addDayRange', a) }
    Where addIsNull(Object... a)              { rec('addIsNull', a) }
    Where addIsNotNull(Object... a)           { rec('addIsNotNull', a) }
    Where addOrderBy(Object... a)             { rec('addOrderBy', a) }
    Where setMaxResults(Object... a)          { rec('setMaxResults', a) }
}
class DomainObject {
    static List SEARCH_RESULTS = []
    static List find(Object... a) { SEARCH_RESULTS }
    static Object get(Object... a) { SEARCH_RESULTS ? SEARCH_RESULTS[0] : null }
}
class LookupItem {
    // Echo the code. A label that differs from its code would make a fixture look right
    // for the wrong reason.
    static String getLabel(String list, String code) { code }
    static String getLabel(Object... a) { a ? a[-1]?.toString() : null }
}
class DateUtil {
    static Date addDays(Date d, int n) {
        if (d == null) return null
        def c = Calendar.getInstance(); c.setTime(d); c.add(Calendar.DATE, n); c.getTime()
    }
    static Date addDays(Object d, Object n) { addDays((Date) d, n as int) }
}
""", "PlatformStubs.groovy")

def fb = new Binding()
new GroovyShell(gcl, fb).evaluate(new File(argv.fixture))
def fixture = fb.getVariable('ROOT_FIXTURE')
// A search rule gets its rows from DomainObject.find. The fixture may set SEARCH_RESULTS;
// default to the root fixture itself so a single-record rule and a search rule both run.
def searchResults = fb.hasVariable('SEARCH_RESULTS') ? fb.getVariable('SEARCH_RESULTS')
                                                     : (fixture ? [fixture] : [])
gcl.loadClass('DomainObject').SEARCH_RESULTS = searchResults
rootClass.FIXTURE = fixture
rootClass.FIXTURE_ID = ID as Long

// The platform hands parameters over as Strings whatever class is declared, so the
// harness must too - passing a Long here would hide a missing coercion in the rule.
def run = { Map params ->
    def b = new Binding()
    params.each { k, v -> if (v != null) b.setVariable(k, v.toString()) }
    new GroovyShell(gcl, b).evaluate(new File(argv.rule))
    b.hasVariable('_data') ? b.getVariable('_data') : null
}

def FIELDS = new File(argv.jrxml).text.findAll(/<field name="([^"]+)"/) { m, n -> n } as Set
def PARAMS = new File(argv.jrxml).text.findAll(/<parameter name="([^"]+)"/) { m, n -> n }

def fail = []
def ck = { String what, boolean ok, Object detail = "" ->
    if (ok) println "  PASS  ${what}"
    else { println "  FAIL  ${what}  ${detail}"; fail << what }
}

// Every declared JRXML parameter, underscore-prefixed, is what the rule expects to find.
def params = PARAMS.collectEntries { ["_${it}", ID] }
def rows = run(params)

println "parameters: ${PARAMS.join(', ')}    fields: ${FIELDS.size()}    rows: ${rows?.size()}"

ck("the rule executed and returned rows", rows != null && !rows.isEmpty())
if (rows) {
    def keySets = rows.collect { it.keySet() as Set }.unique()
    ck("every row has an identical key set", keySets.size() == 1, "${keySets.size()} distinct")
    ck("row keys match the .jrxml field list exactly", keySets[0] == FIELDS,
       "rule-only=${keySets[0] - FIELDS}  jrxml-only=${FIELDS - keySets[0]}")
    // Groovy's `instanceof String` can treat a GString as String-compatible, while
    // Jasper's DirectFieldEvaluator casts to exact java.lang.String and rejects
    // GStringImpl. Check the runtime class, not Groovy's coercive type relation.
    def nonString = rows.collectMany { r ->
        r.findAll { k, v -> v == null || v.getClass() != String }.collect { k, v -> "${k}=${v?.class?.simpleName}" }
    }.unique()
    ck("every value is a String", nonString.isEmpty(), nonString)
    def nullish = rows.collectMany { r ->
        r.findAll { k, v -> v == "null" }.collect { k, v -> k } }.unique()
    ck("no field carries the literal \"null\"", nullish.isEmpty(), nullish)

    // A character outside WinAnsi is dropped SILENTLY at PDF export: no error, no
    // placeholder box, an empty cell - and the row map still holds the right value, so
    // every assertion above it passes. Unless a <font> carries pdfEncoding="Identity-H"
    // and isPdfEmbedded="true", JasperReports exports Helvetica in WinAnsi, and no report
    // in this corpus embeds a font. This cost the Case Summary Report two permanently
    // blank columns (a U+2713 tick), found only by reading the rendered page - 2026-09-01.
    // The check asks the real encoder rather than a hand-kept table of "safe" characters.
    def enc = java.nio.charset.Charset.forName("windows-1252").newEncoder()
    def unencodable = rows.collectMany { r ->
        r.findAll { k, v -> v instanceof String && !enc.canEncode(v) }.collect { k, v ->
            def bad = (v.toCharArray().findAll { !enc.canEncode(it) } as Set)
                          .collect { String.format("U+%04X '%s'", (int) it, it) }
            "${k}: ${bad.join(', ')}"
        }
    }.unique()
    ck("every character survives PDF export (WinAnsi)", unencodable.isEmpty(), unencodable)
}

// An id that resolves to nothing must still produce a page, not an exception and not an
// empty collection - an empty _data renders a blank sheet with no clue why.
def missing = run(PARAMS.collectEntries { ["_${it}", "99999999"] })
ck("an unresolvable id still returns at least one row", missing != null && !missing.isEmpty(),
   "${missing?.size()} rows")

// Report-specific assertions get the same ck/fail, so one summary covers both.
if (argv.assert) {
    println ""
    def ab = new Binding([rows: rows, ck: ck, fields: FIELDS, fixture: fixture,
                          run: run, rootClass: rootClass])
    new GroovyShell(gcl, ab).evaluate(new File(argv.assert))
}

println ""
if (fail) { println "${fail.size()} FAILED: ${fail}"; System.exit(1) }
println "ALL CHECKS PASSED"
