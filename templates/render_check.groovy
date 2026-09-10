// Compile a generated .jrxml and fill it from .tsv fixtures.
//
// LEGACY FORM - one variant, one JVM. Still supported; existing reports use it.
//   render_check.groovy <jrxml> <tsv> [empty]
//
// BATCH FORM - compile ONCE, fill every variant in the same JVM.
//   render_check.groovy <jrxml> --out DIR --variant full=fx_full.tsv --variant none=fx_none.tsv:empty
//
// Why the batch form exists: measured 2026-09-04, each invocation pays ~5.8s of JVM start
// plus JasperReports class init before it does any work, and a warm second compileReport of
// the same file costs 256ms against 3.0s cold. Rendering two variants as two processes pays
// that twice for nothing. The batch form writes DIR/<variant>_sample.pdf and its page PNGs
// directly, so the caller needs no mv step.
//
// TSV rather than JSON so this needs nothing beyond the core Groovy jar.
import net.sf.jasperreports.engine.*
import net.sf.jasperreports.engine.data.JRMapCollectionDataSource
import net.sf.jasperreports.engine.export.JRPdfExporter
import net.sf.jasperreports.export.*
import javax.imageio.ImageIO
import java.awt.image.BufferedImage

def jrxml = new File(args[0])

// ---- argument parsing: batch form iff at least one --variant is present ----------
def variants = []      // [name, tsvFile, emptyFlag]
def outDir = null
for (int i = 1; i < args.length; i++) {
    if (args[i] == "--out") { outDir = new File(args[++i]) }
    else if (args[i] == "--variant") {
        def spec = args[++i]
        def eq = spec.indexOf('=')
        def name = spec.substring(0, eq)
        def rest = spec.substring(eq + 1)
        def isEmpty = rest.endsWith(":empty")
        if (isEmpty) rest = rest.substring(0, rest.length() - ":empty".length())
        variants << [name, new File(rest), isEmpty]
    }
}
def legacy = variants.isEmpty()
if (legacy) {
    def isEmpty = args.length > 2 && args[2] == "empty"
    variants << [isEmpty ? "empty" : "sample", new File(args[1]), isEmpty]
}
if (outDir == null) outDir = jrxml.parentFile
outDir.mkdirs()

// ---- compile ONCE ---------------------------------------------------------------
def report = JasperCompileManager.compileReport(jrxml.absolutePath)
def declared = report.fields*.name as Set
def kind = report.fields.collectEntries { [(it.name): it.valueClassName] }
def df = new java.text.SimpleDateFormat("MM/dd/yyyy")
println "compiled  ${jrxml.name}  (${declared.size()} fields, " +
        "${report.parameters.findAll{!it.isSystemDefined()}.size()} params)"

// ---- fill each variant ----------------------------------------------------------
variants.each { v ->
    def (String name, File tsv, boolean isEmpty) = v
    def lines = tsv.readLines().findAll { it.trim() }
    def head = lines[0].split("\t", -1)
    def rows = isEmpty ? [] : lines.tail().collect { l ->
        def vals = l.split("\t", -1)
        def m = [:]
        head.eachWithIndex { k, i -> m[k] = (i < vals.size() ? vals[i].replace("\\n", "\n") : "") }
        m
    }

    def supplied = head as Set
    def missing = declared - supplied
    if (missing) {
        // The contract check: a declared field with no key in the row map prints an
        // empty column and NOTHING reports an error. Fail loudly instead.
        System.err.println "CONTRACT FAIL [${name}] - fields declared in jrxml with no key in the rows: ${missing.sort()}"
        System.exit(3)
    }
    def unused = supplied - declared
    if (unused) {
        // A key the rows carry that the jrxml does not declare usually means the column
        // list changed and the fixture did not - which shifts every later column one
        // place left while the page still looks entirely plausible.
        System.err.println "WARNING [${name}] - fixture keys not declared in the jrxml: ${unused.sort()}"
        System.err.println "          if the column list just changed, the fixture is stale and columns will be MISALIGNED"
    }

    // Coerce each value to the class the jrxml declares. A String handed to a
    // java.util.Date field throws at fill time; in eSeries the rule emits the real type,
    // so the fixture has to as well or the harness tests a different contract.
    rows.each { m ->
        m.each { k, val ->
            if (kind[k] == "java.util.Date" && val instanceof String)
                m[k] = (val?.trim()) ? df.parse(val) : null
        }
    }

    def print_ = JasperFillManager.fillReport(report, [:], new JRMapCollectionDataSource(rows))
    def out = legacy
        ? new File(outDir, jrxml.name.replace(".jrxml", isEmpty ? "_empty.pdf" : "_sample.pdf"))
        : new File(outDir, "${name}.pdf")
    def ex = new JRPdfExporter()
    ex.exporterInput = new SimpleExporterInput(print_)
    ex.exporterOutput = new SimpleOutputStreamExporterOutput(out)
    ex.exportReport()

    // Raster EVERY page, not just the first. A geometry check answers "do cells collide";
    // it never answers "does this read right", and an unexamined page is worth nothing.
    //
    // These PNGs come from AWT and will show glyphs the PDF drops (see jti_style._winansi).
    // The callers re-raster from the PDF afterwards with pdfraster.py, overwriting these
    // under the same names. Do not treat these as the page that ships.
    def stem = out.name.replace(".pdf", "")
    print_.pages.size().times { i ->
        def img = JasperPrintManager.printPageToImage(print_, i, 1.0f)
        def buf = new BufferedImage(img.getWidth(null), img.getHeight(null), BufferedImage.TYPE_INT_RGB)
        def g = buf.createGraphics(); g.drawImage(img, 0, 0, null); g.dispose()
        ImageIO.write(buf, "png", new File(out.parentFile, "${stem}_p${i + 1}.png"))
    }
    println "rendered  ${out.name}  ${print_.pages.size()} page(s), ${rows.size()} row(s)" +
            "  -> ${stem}_p1..p${print_.pages.size()}.png"
}
