/*
 * The KNOWN-GOOD rule the suite mutates. Every negative test is this file with one thing
 * broken, so a test failing means the gate changed - not that the fixture drifted.
 *
 * It deliberately satisfies all three rules the gates enforce: it assigns _data, it carries
 * no com.sustain imports (so it compiles off-platform), and every value is a real String.
 */
def str = { v -> v == null ? "" : v.toString().trim() }

def head = [rptTitle: "Probe Report", rptSubtitle: "every case type", rptSlug: "probe"]

def w = new Where()
if (str(_CaseType)) w.addIn("caseType", str(_CaseType).split(',').collect { it.trim() })

def rows = (DomainObject.find(Case.class, w) ?: []).collect { c ->
    def m = [:]
    m.putAll(head)
    m.caseNumber = str(c?.caseNumber)
    m.caseType = str(c?.caseType)
    m
}

// An id that resolves to nothing must still produce a page, not an empty collection.
if (!rows) {
    def m = [:]
    m.putAll(head)
    m.caseNumber = "No rows matched"
    m.caseType = ""
    rows = [m]
}

_data = rows
