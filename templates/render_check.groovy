// Compile a generated .jrxml and fill it from a sibling .tsv fixture.
//   render.sh <template.py> [empty]
// TSV rather than JSON so this needs nothing beyond the core Groovy jar.
import net.sf.jasperreports.engine.*
import net.sf.jasperreports.engine.data.JRMapCollectionDataSource
import net.sf.jasperreports.engine.export.JRPdfExporter
import net.sf.jasperreports.export.*
import javax.imageio.ImageIO
import java.awt.image.BufferedImage

def jrxml = new File(args[0])
def tsv = new File(args[1])
def empty = args.length > 2 && args[2] == "empty"

def lines = tsv.readLines().findAll { it.trim() }
def head = lines[0].split("\t", -1)
def rows = empty ? [] : lines.tail().collect { l ->
    def v = l.split("\t", -1)
    def m = [:]
    head.eachWithIndex { k, i -> m[k] = (i < v.size() ? v[i].replace("\\n", "\n") : "") }
    m
}

def report = JasperCompileManager.compileReport(jrxml.absolutePath)
def declared = report.fields*.name as Set
def supplied = head as Set
def missing = declared - supplied
if (missing) {
    // The contract check: a declared field with no key in the row map prints an
    // empty column and NOTHING reports an error. Fail loudly instead.
    System.err.println "CONTRACT FAIL - fields declared in jrxml with no key in the rows: ${missing.sort()}"
    System.exit(3)
}
def unused = supplied - declared
println "compiled  ${jrxml.name}  (${declared.size()} fields, ${report.parameters.findAll{!it.isSystemDefined()}.size()} params)" +
        (unused ? "" : "")
if (unused) {
    // A key the rows carry that the jrxml does not declare usually means the column
    // list changed and the fixture did not - which shifts every later column one
    // place left while the page still looks entirely plausible.
    System.err.println "WARNING - fixture keys not declared in the jrxml: ${unused.sort()}"
    System.err.println "          if the column list just changed, the fixture is stale and columns will be MISALIGNED"
}

// Coerce each value to the class the jrxml declares. A String handed to a
// java.util.Date field throws at fill time; in eSeries the rule emits the real type,
// so the fixture has to as well or the harness tests a different contract.
def kind = report.fields.collectEntries { [(it.name): it.valueClassName] }
def df = new java.text.SimpleDateFormat("MM/dd/yyyy")
rows.each { m ->
    m.each { k, v ->
        if (kind[k] == "java.util.Date" && v instanceof String)
            m[k] = (v?.trim()) ? df.parse(v) : null
    }
}
def print_ = JasperFillManager.fillReport(report, [:], new JRMapCollectionDataSource(rows))
def out = new File(jrxml.parentFile, jrxml.name.replace(".jrxml", empty ? "_empty.pdf" : "_sample.pdf"))
def ex = new JRPdfExporter()
ex.exporterInput = new SimpleExporterInput(print_)
ex.exporterOutput = new SimpleOutputStreamExporterOutput(out)
ex.exportReport()
// Raster EVERY page, not just the first. A geometry check answers "do cells
// collide"; it never answers "does this read right", and an unexamined page is
// worth nothing. sips only ever converts page 1, which is how a defect on page 2
// survives a green run.
def stem = out.name.replace(".pdf", "")
print_.pages.size().times { i ->
    def img = JasperPrintManager.printPageToImage(print_, i, 1.0f)
    def buf = new BufferedImage(img.getWidth(null), img.getHeight(null), BufferedImage.TYPE_INT_RGB)
    def g = buf.createGraphics(); g.drawImage(img, 0, 0, null); g.dispose()
    ImageIO.write(buf, "png", new File(out.parentFile, "${stem}_p${i + 1}.png"))
}
println "rendered  ${out.name}  ${print_.pages.size()} page(s), ${rows.size()} row(s)" +
        "  -> ${stem}_p1..p${print_.pages.size()}.png"
