// The rule body after the generated launch-input block (verification/launch_inputs.groovy,
// prepended by the suite). It filters ONLY through applyLaunchInputs, as the build commands say.

def str = { v -> v == null ? "" : v.toString().trim() }
def head = [rptTitle: "Crit Probe", rptSubtitle: "criteria", rptSlug: "probe"]
def w = applyLaunchInputs(new Where())
def rows = (DomainObject.find(Case.class, w) ?: []).collect { c ->
    def m = [:]; m.putAll(head)
    m.caseNumber = str(c?.caseNumber); m.caseType = str(c?.caseType); m
}
if (!rows) { def m = [:]; m.putAll(head); m.caseNumber = "No rows matched"; m.caseType = ""; rows = [m] }
_data = rows
