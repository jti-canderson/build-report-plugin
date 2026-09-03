/*
 * render.groovy — compile a report .jrxml, fill it with the rule's OWN output, write a PDF.
 *
 *   groovy render.groovy --rule R_V1.groovy --jrxml R.jrxml --fixture Fixture.groovy
 *                        --out sample.pdf [--root Case] [--id 19]
 *
 * Needs the JasperReports jars; see verify.sh for the classpath. This is a real compile
 * and a real fill, so it catches overlapping elements, clipped columns, a logo that came
 * out blank, and pagination - the defects that otherwise surface only after a deploy.
 *
 * It still proves nothing about the live entity model: the rows come from the fixture.
 */
import net.sf.jasperreports.engine.*
import net.sf.jasperreports.engine.data.JRMapCollectionDataSource

def argv = [:]
for (int i = 0; i < args.size(); i++) {
    if (args[i].startsWith("--")) { argv[args[i].substring(2)] = args[i + 1]; i++ }
}
["rule", "jrxml", "fixture", "out"].each {
    if (!argv[it]) { System.err.println "missing --${it}"; System.exit(2) }
}
def ROOT = argv.root ?: "Case"
def ID   = argv.id ?: "19"

def gcl = new GroovyClassLoader(this.class.classLoader)
def rootClass = gcl.parseClass("""
class ${ROOT} {
    static Object FIXTURE
    static Long FIXTURE_ID
    static Object get(Long id) { id == FIXTURE_ID ? FIXTURE : null }
    static Object get(Object cls, Long id) { get(id) }
}
""", "${ROOT}.groovy")

def fb = new Binding()
new GroovyShell(gcl, fb).evaluate(new File(argv.fixture))
// --empty renders a root that resolves but holds nothing; --missing an id that resolves
// to nothing. Both are pages a user will eventually see, so both are worth looking at.
rootClass.FIXTURE = (argv.variant == "empty") ? [id: ID as Long] : fb.getVariable('ROOT_FIXTURE')
rootClass.FIXTURE_ID = ID as Long

def JRXML_TEXT = new File(argv.jrxml).text
def PARAMS = JRXML_TEXT.findAll(/<parameter name="([^"]+)"/) { m, n -> n }
// A parameter that declares its own <defaultValueExpression> supplies itself - an
// embedded logo, a title, a house constant. Overriding it with the launch id blanks it
// at best and throws a ClassCastException at worst, and neither failure is the report's.
// Only the parameters WITHOUT a default are launch inputs.
def SELF_SUPPLIED = JRXML_TEXT.findAll(
    /<parameter name="([^"]+)"[^>]*>\s*<defaultValueExpression/) { m, n -> n } as Set
def INPUTS = PARAMS.findAll { !(it in SELF_SUPPLIED) }
def value  = (argv.variant == "missing") ? "99999999" : ID

def b = new Binding()
INPUTS.each { b.setVariable("_${it}", value) }
new GroovyShell(gcl, b).evaluate(new File(argv.rule))
def rows = b.getVariable('_data')
println "rule produced ${rows.size()} rows"

def report = JasperCompileManager.compileReport(argv.jrxml)
println "compiled: ${report.name}, ${report.fields.length} fields"
def jasperParams = INPUTS.collectEntries { [it, value as Long] }
def print = JasperFillManager.fillReport(report, jasperParams,
                                         new JRMapCollectionDataSource(rows))
println "filled: ${print.pages.size()} page(s)"
JasperExportManager.exportReportToPdfFile(print, argv.out)
println "pdf: ${argv.out}  ${new File(argv.out).length()} bytes"
