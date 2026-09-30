"""launch_inputs.py - Search Criteria from the builder, carried into the report without guessing.

What eSeries does with a report's inputs (proven, see the jasper-reports references and the
2026-09-25 binding dump):
  - the report's <parameter> name is BOTH the label on the launch form and the key that binds
    it to the rule's input of the same name - an exact-string match, and a mismatch is simply
    an empty input, no error;
  - every value reaches the rule as text - a String, a Collection for a multi-select, or null;
  - REQUIRED / OPTIONAL and a lookup list belong to the RULE's input registration, not the
    .jrxml; a <parameter> default is something else entirely (the logo), so a criterion's
    default is applied BY THE RULE when the input is left blank.

So a criterion becomes: one exact input name (two for a From/To date), a registered type,
required flag and lookup list, and one block of Groovy that reads the input by that name,
converts it, and adds the attested Where call. This module makes all of that from spec.json:

  validate(spec)        name / duplicate / type errors, in plain words
  inputs(spec)          the normalised launch inputs, in launch-form order
  gen_block(spec)       verification/launch_inputs.groovy - pasted at the top of the rule
  gen_check(spec)       verification/launch_inputs_check.groovy - rulecheck --assert: runs the
                        rule with realistic launch values and checks each criterion's filter
  registration(spec)    per-input lines for RULE_REGISTRATION.txt
  rule_inputs(spec)     {name: {"required": bool, "lookup": str}} for rule_zip.py

Attested Where calls only (references/criteria-api.md). A criterion with no attested call -
starts with / ends with - is read and left to the rule to apply; the check says so rather than
pretending to verify it.
"""
import json
import re

NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,59}$")
RESERVED = {"journalLogo", "data"}
JAVA = {"date": "java.util.Date", "number": "java.lang.Integer", "decimal": "java.lang.String",
        "yes/no": "java.lang.String", "text": "java.lang.String", "pick-list": "java.lang.String"}
WHERE = {"EQUALS": "addEquals", "IN": "addIn", "NOT_IN": "addNotIn", "CONTAINS": "addContains",
         "GREATER_THAN": "addGreaterThan", "RANGE": "addDateRange", "BLANK": "addIsNull",
         "NOT_BLANK": "addIsNotNull", "range": "addDateRange", "in": "addIn", "equals": "addEquals"}


def rel(path):
    """Case.parties[].person.lastName -> parties.person.lastName (the Where path)."""
    return ".".join(p.replace("[]", "") for p in (path or "").split(".")[1:])


def camel(name):
    s = re.sub(r"[^A-Za-z0-9]+", " ", name).strip().split()
    if not s:
        return "input"
    v = s[0][0].lower() + s[0][1:] + "".join(w[0].upper() + w[1:] for w in s[1:])
    return v if not v[0].isdigit() else "in" + v


def inputs(spec):
    """Every launch input in launch-form order: criteria first (as picked), then any plain
    param the spec lists that no criterion accounts for (typed by hand)."""
    crit = spec.get("criteria") or []
    out, seen = [], set()
    for c in crit:
        op = str(c.get("operator") or "EQUALS")
        names = [str(n) for n in (c.get("params") or [])]
        dtype = c.get("type") or "text"
        out.append({"names": names, "label": c.get("label") or (names[0] if names else ""),
                    "path": c.get("path") or "", "rel": rel(c.get("path")), "operator": op,
                    "dtype": dtype, "lookup": c.get("lookup"), "multi": bool(c.get("multi")),
                    "required": bool(c.get("required")), "hidden": bool(c.get("hidden")),
                    "default": c.get("default") or "",
                    # where: False - a computed (not stored) property: read the input, but the
                    # rule matches it after find(); a Where on it cannot run in the query
                    "where": c.get("where", True) is not False})
        seen |= set(names)
    classes = {n: cls for n, cls in (spec.get("params") or [])}
    for n, cls in (spec.get("params") or []):
        if n not in seen:
            out.append({"names": [n], "label": n, "path": "", "rel": "", "operator": "EQUALS",
                        "dtype": "date" if cls == "java.util.Date" else "text", "lookup": None,
                        "multi": False, "required": False, "hidden": False, "default": "",
                        "where": True, "plain": True})
    for i in out:
        i["classes"] = [classes.get(n, JAVA.get(i["dtype"], "java.lang.String")) for n in i["names"]]
    return out


def validate(spec):
    errs, seen = [], {}
    root = (spec.get("root") or "").strip()
    for i in inputs(spec):
        # A path is a traversal FROM the report's root: "Person.fml" on a Case report would
        # become a Case filter on `fml` - silently wrong. Reach it from the root instead.
        if root and i["path"] and i["path"].split(".")[0] != root:
            errs.append(f"{i['label']!r} filters {i['path']}, but the report is a list of {root} - "
                        f"give the path from {root} (e.g. {root}.parties[].person."
                        f"{i['path'].split('.', 1)[-1]})")
        for n in i["names"]:
            if not NAME_OK.match(n):
                errs.append(f"launch input {n!r}: use letters, digits and underscores, starting "
                            f"with a letter - it is the label on the launch form and the name "
                            f"the rule reads")
            elif n in RESERVED:
                errs.append(f"launch input {n!r} is a name the report already uses - pick another")
            elif n in seen:
                errs.append(f"two launch inputs are both named {n!r} - eSeries would bind them "
                            f"to the same value; rename one")
            seen[n] = True
        if i["hidden"] and not i["default"] and i["operator"] not in ("BLANK", "NOT_BLANK"):
            errs.append(f"{i['label']!r} is hidden but has no default - a hidden criterion is "
                        f"always applied, so it needs the value to apply")
    return errs


def _how(i):
    if i["hidden"]:
        return f"not shown - always applied with {i['default'] or i['operator'].lower()}"
    if i["operator"] in ("BLANK", "NOT_BLANK"):
        return "not shown - always applied (" + ("blank" if i["operator"] == "BLANK" else "not blank") + ")"
    if i["dtype"] == "date":
        return "a date (MM/dd/yyyy); leave blank for no limit" if i["operator"] == "RANGE" else "a date (MM/dd/yyyy)"
    if i["dtype"] == "pick-list":
        return (f"one or more {i['lookup']} codes" if i["multi"] else f"one {i['lookup']} code") + \
               (" - the input is registered with that lookup list" if i["lookup"] else "")
    if i["operator"] in ("IN", "NOT_IN"):
        return "one or more values, separated by commas"
    if i["dtype"] in ("number", "decimal"):
        return "a number"
    return "text"


def registration(spec):
    lines = []
    for i in inputs(spec):
        if not i["names"]:
            continue
        what = (f"filters {i['path']} ({i['operator'].replace('_', ' ').lower()})" if i["path"]
                else "typed by hand - see the rule for what it filters")
        flag = "REQUIRED" if i["required"] else "optional"
        dflt = f"; blank means {i['default']}" if i["default"] and not i["hidden"] else ""
        if len(i["names"]) == 2:
            lines.append(f"  - {i['names'][0]} / {i['names'][1]} ({i['classes'][0]}, {flag}) - {what}; "
                         f"enter {_how(i)}{dflt}")
        else:
            lines.append(f"  - {i['names'][0]} ({i['classes'][0]}, {flag}"
                         + (f", lookup {i['lookup']}" if i["lookup"] else "") + f") - {what}; "
                         f"enter {_how(i)}{dflt}")
    for i in inputs(spec):
        if not i["names"] and (i["hidden"] or i["operator"] in ("BLANK", "NOT_BLANK")):
            lines.append(f"  - (no input) {i['label']} - {_how(i)}; filters {i['path']}")
    return lines


def rule_inputs(spec):
    out = {}
    for i in inputs(spec):
        for n in i["names"]:
            out[n] = {"required": i["required"], "lookup": i["lookup"] if i["dtype"] == "pick-list" else ""}
    return out


# ── the Groovy block pasted at the top of the rule ──────────────────────────────────────
HELPERS = r'''// Every launch value arrives as text - a String, a list for a multi-select, or nothing.
// These turn it into what the filter needs, and treat blank as "not filtering".
def launchInput = { String n -> binding.hasVariable(n) ? binding.getVariable(n) : null }
def inText = { v ->
    if (v == null) return null
    def s = (v instanceof Collection) ? v.collect { it?.toString()?.trim() }.findAll { it }.join(',') : v.toString().trim()
    s ?: null
}
def inList = { v ->
    if (v == null) return []
    ((v instanceof Collection) ? v : v.toString().split(',')).collect { it?.toString()?.trim() }.findAll { it }
}
def inDate = { v ->
    if (v == null) return null
    if (v instanceof Date) return v
    def s = v.toString().trim()
    if (!s) return null
    for (f in ['MM/dd/yyyy', 'M/d/yyyy', 'yyyy-MM-dd', "yyyy-MM-dd'T'HH:mm:ss", 'yyyy-MM-dd HH:mm:ss']) {
        try { def p = new java.text.SimpleDateFormat(f); p.lenient = false; return p.parse(s) } catch (ignored) { }
    }
    null
}
def dayStart = { Date d -> if (d == null) return null; def c = Calendar.getInstance(); c.time = d
    [Calendar.HOUR_OF_DAY, Calendar.MINUTE, Calendar.SECOND, Calendar.MILLISECOND].each { c.set(it, 0) }; c.time }
def dayEnd = { Date d -> d == null ? null : new Date(dayStart(d).time + 86399999L) }   // a To date includes its whole day
def macroDate = { String m ->
    if (m == '@TODAY') return dayStart(new Date())
    if (m == '@THIS_WEEK') { def c = Calendar.getInstance(); c.time = dayStart(new Date())
        c.set(Calendar.DAY_OF_WEEK, c.firstDayOfWeek); return c.time }
    inDate(m)
}
def inNumber = { v -> def s = inText(v); (s && s.isNumber()) ? new BigDecimal(s) : null }
'''


def _lit(v):
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def gen_block(spec):
    ins = inputs(spec)
    if not ins:
        return None
    L = ["// ==== LAUNCH INPUTS =====================================================================",
         "// Generated by scaffold.py from spec.json (the Search Criteria picked in the builder).",
         "// Paste it at the top of the rule UNCHANGED, then filter with:",
         "//     def w = applyLaunchInputs(new Where())",
         "// Each input is read by its EXACT launch-form name: that name is also how eSeries binds",
         "// the value, and a different spelling is silently empty.",
         HELPERS.rstrip(), ""]
    body, post = [], []
    for i in ins:
        v = camel(i["names"][0] if i["names"] else i["label"])
        n = i["names"]
        p, op, dt = i["rel"], i["operator"], i["dtype"]
        if not i["where"] and p:
            post.append(f"// {n[0] if n else i['label']}: {i['path']} is computed, not stored - no Where "
                        f"call can use it. Keep only records whose {i['path']} "
                        f"{'contains' if op == 'CONTAINS' else 'matches'} `{v}` (when set), after find().")
            p = ""
        note = f"// {i['path'] or '(typed by hand)'} - {op.replace('_', ' ').lower()}" + \
               (f", pick-list {i['lookup']}" if i["lookup"] else "") + (", REQUIRED" if i["required"] else "")
        L.append(note)
        if dt == "date" and op in ("RANGE", "range") and len(n) == 2:
            L.append(f"def {v} = inDate(launchInput('_{n[0]}'))")
            L.append(f"def {camel(n[1])} = dayEnd(inDate(launchInput('_{n[1]}')))")
            if i["default"]:
                L.append(f"if ({v} == null && {camel(n[1])} == null) {v} = macroDate({_lit(i['default'])})")
            if p:
                # Only a both-ends addDateRange is attested, so one end entered uses the
                # attested one-sided comparison rather than passing a null bound.
                t = camel(n[1])
                body.append(f"    if ({v} != null && {t} != null) w.addDateRange('{p}', {v}, {t})")
                body.append(f"    else if ({v} != null) w.addGreaterThanOrEquals('{p}', {v})")
                body.append(f"    else if ({t} != null) w.addLessThanOrEquals('{p}', {t})")
            continue
        src = f"launchInput('_{n[0]}')" if n else "null"
        if i["hidden"]:
            src = _lit(i["default"])
        if dt == "date":
            L.append(f"def {v} = {'macroDate(' + _lit(i['default']) + ')' if i['hidden'] else 'inDate(' + src + ')'}")
            if i["default"] and not i["hidden"]:
                L.append(f"if ({v} == null) {v} = macroDate({_lit(i['default'])})")
            if p and op in ("EQUALS", "equals"):
                body.append(f"    if ({v} != null) w.addDateRange('{p}', dayStart({v}), dayEnd({v}))")
        elif op in ("IN", "NOT_IN", "in"):
            L.append(f"def {v} = inList({src})")
            if i["default"] and not i["hidden"]:
                L.append(f"if (!{v}) {v} = inList({_lit(i['default'])})")
            if p:
                body.append(f"    if ({v}) w.{WHERE[op]}('{p}', {v})")
        elif dt in ("number", "decimal"):
            L.append(f"def {v} = inNumber({src})")
            if i["default"] and not i["hidden"]:
                L.append(f"if ({v} == null) {v} = inNumber({_lit(i['default'])})")
            if p and op in WHERE and op not in ("BLANK", "NOT_BLANK"):
                body.append(f"    if ({v} != null) w.{WHERE[op]}('{p}', {v})")
        else:
            L.append(f"def {v} = inText({src})")
            if i["default"] and not i["hidden"]:
                L.append(f"if ({v} == null) {v} = inText({_lit(i['default'])})")
            if p and op in ("EQUALS", "CONTAINS", "equals"):
                body.append(f"    if ({v} != null) w.{WHERE[op]}('{p}', {v})")
            elif p and op in ("STARTS_WITH", "ENDS_WITH"):
                post.append(f"// {n[0] if n else i['label']}: no attested Where call for "
                            f"{op.replace('_', ' ').lower()} - keep only records whose {p} "
                            f"{'starts' if op == 'STARTS_WITH' else 'ends'} with {v}, after find().")
        if p and op in ("BLANK", "NOT_BLANK"):
            body.append(f"    w.{WHERE[op]}('{p}')")
    L.append("")
    L.append("def applyLaunchInputs = { w ->")
    L += body or ["    // (no criterion maps to a Where call)"]
    L.append("    w")
    L.append("}")
    L += post
    L.append("// ==== END LAUNCH INPUTS =================================================================")
    return "\n".join(L) + "\n"


def gen_check(spec):
    """rulecheck --assert: run the rule with realistic launch values and check each filter."""
    ins = [i for i in inputs(spec) if i["path"] and not i.get("plain")]
    if not ins:
        return None
    cases = []
    for i in ins:
        op, dt, n = i["operator"], i["dtype"], i["names"]
        if not i["where"]:
            cases.append({"what": i["label"], "skip": f"{i['path']} is computed - the rule matches it "
                                                      f"after find(); not a query filter, not checked here"})
            continue
        if dt == "date" and op in ("RANGE", "range") and len(n) == 2:
            cases.append({"what": i["label"], "set": {n[0]: "01/15/2026", n[1]: "02/15/2026"},
                          "alt": {n[0]: "2026-01-15", n[1]: "2026-02-15"},
                          "expect": {"op": "addDateRange", "path": i["rel"], "from": "2026-01-15", "to": "2026-02-15"},
                          "sides": [{"set": {n[0]: "01/15/2026"}, "what": "only " + n[0],
                                     "expect": {"op": "addGreaterThanOrEquals", "path": i["rel"], "on": "2026-01-15"}},
                                    {"set": {n[1]: "02/15/2026"}, "what": "only " + n[1],
                                     "expect": {"op": "addLessThanOrEquals", "path": i["rel"], "on": "2026-02-15"}}]})
        elif op in ("IN", "NOT_IN", "in") and n and not i["hidden"]:
            cases.append({"what": i["label"], "set": {n[0]: ["V1", "V2"]}, "alt": {n[0]: "V1, V2"},
                          "single": {n[0]: "V1"},
                          "expect": {"op": WHERE[op], "path": i["rel"], "list": ["V1", "V2"]}})
        elif op in ("EQUALS", "CONTAINS", "equals") and n and dt not in ("date", "number", "decimal") and not i["hidden"]:
            cases.append({"what": i["label"], "set": {n[0]: "  Sample value  "},
                          "expect": {"op": WHERE[op], "path": i["rel"], "value": "Sample value"}})
        elif op in ("EQUALS", "GREATER_THAN") and n and dt in ("number", "decimal") and not i["hidden"]:
            cases.append({"what": i["label"], "set": {n[0]: "42"},
                          "expect": {"op": WHERE[op], "path": i["rel"], "number": 42}})
        elif op in ("BLANK", "NOT_BLANK"):
            cases.append({"what": i["label"], "set": {}, "expect": {"op": WHERE[op], "path": i["rel"], "always": True}})
        elif i["hidden"]:
            cases.append({"what": i["label"], "set": {}, "expect": {"path": i["rel"], "always": True}})
        else:
            cases.append({"what": i["label"], "skip": f"{op.replace('_', ' ').lower()} has no attested Where call - "
                                                      f"the rule applies it after find(); not checked here"})
    for cs, i in zip(cases, ins):
        cs["default"] = bool(i["default"]) and not i["hidden"]
    names = sorted({n for i in inputs(spec) for n in i["names"]})
    return ("// Generated by scaffold.py from spec.json. Run by rulecheck.groovy (--assert): the rule\n"
            "// is run with realistic launch values, and each Search Criterion must reach its filter.\n"
            "def CASES = new groovy.json.JsonSlurper().parseText('''" + json.dumps(cases) + "''')\n"
            "def NAMES = " + json.dumps(names) + "\n" + CHECK_BODY)


CHECK_BODY = r'''
def conds = { -> queries().collectMany { q -> q.findAll { it != null && it.getClass().getName() == 'Where' }.collectMany { it.conditions } } }
def blank = NAMES.collectEntries { ["_" + it, ""] }
def withIds = { Map m -> def p = [:]; p.putAll(ID_PARAMS); p.putAll(m); p }
def day = { String s -> new java.text.SimpleDateFormat('yyyy-MM-dd').parse(s) }
def matches = { c, e ->
    if (e.op && c.op != e.op) return false
    if (e.path && (c.args[0]?.toString() != e.path)) return false
    if (e.list != null) return (c.args[1] instanceof Collection) && c.args[1].collect { it.toString() } == e.list
    if (e.value != null) return c.args[1]?.toString() == e.value
    if (e.number != null) return c.args[1] != null && (c.args[1] as BigDecimal) == (e.number as BigDecimal)
    if (e.on) return (c.args[1] instanceof Date) && c.args[1].format('yyyy-MM-dd') == e.on
    if (e.from) return (c.args[1] instanceof Date) && c.args[1].format('yyyy-MM-dd') == e.from &&
                       (c.args[2] instanceof Date) && c.args[2].format('yyyy-MM-dd') == e.to && c.args[2] > day(e.to)
    true
}
def found = { e -> conds().find { matches(it, e) } }

def r0 = run(withIds(blank))
ck("launch inputs: with every search criterion blank the report still runs", r0 != null && !r0.isEmpty())
CASES.findAll { !it.skip && !it.expect.always }.each { cs ->
    run(withIds(blank))
    def onPath = conds().find { it.args && it.args[0]?.toString() == cs.expect.path }
    if (cs.default) ck("launch inputs: '${cs.what}' left blank applies its default", onPath != null)
    else ck("launch inputs: '${cs.what}' left blank adds no filter", onPath == null, "found ${onPath}")
}
CASES.each { cs ->
    if (cs.skip) { println "  NOTE  launch inputs: '${cs.what}' - ${cs.skip}"; return }
    run(withIds(blank + cs.set.collectEntries { k, v -> ["_" + k, v] }))
    ck("launch inputs: '${cs.what}' reaches ${cs.expect.op ?: 'its filter'}('${cs.expect.path}') with the value entered",
       found(cs.expect) != null, "conditions: ${conds().collect { it.op + it.args }}")
    ['alt', 'single'].each { k ->
        if (!cs[k]) return
        run(withIds(blank + cs[k].collectEntries { kk, v -> ["_" + kk, v] }))
        def e = k == 'single' ? (cs.expect + [list: ['V1']]) : cs.expect
        ck("launch inputs: '${cs.what}' also understands ${k == 'alt' ? 'the other way it can arrive (' + cs[k].values().join(' / ') + ')' : 'a single value'}",
           found(e) != null, "conditions: ${conds().collect { it.op + it.args }}")
    }
    (cs.sides ?: []).each { sd ->
        run(withIds(blank + sd.set.collectEntries { k, v -> ["_" + k, v] }))
        ck("launch inputs: '${cs.what}' with ${sd.what} filled uses ${sd.expect.op}('${sd.expect.path}')",
           found(sd.expect) != null, "conditions: ${conds().collect { it.op + it.args }}")
    }
}
'''
