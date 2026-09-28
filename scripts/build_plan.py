#!/usr/bin/env python3
"""build_plan.py - one command for everything mechanical in a build, driven by build-plan.json.

    build_plan.py validate  <build-plan.json>   schema + lane; exit 0 fast, 20 expert, 2 invalid
    build_plan.py resolve   <build-plan.json>   batch-check every traversal against the SDK
    build_plan.py run       <build-plan.json>   validate, resolve, scaffold, fill the fixtures,
                                                verify, fill the notes, inventory - one call
    build_plan.py --example                     a complete plan to start from

The builder still writes spec.json. Claude reads it and writes build-plan.json, which adds
ONLY the decisions that need professional judgment: the root entity and strategy, which
entity each path lands on, awkward fixture rows, the assumptions made and what is not
proven. Claude also writes the rule - every line of it is a decision, and this does NOT
generate rules. Everything else is deterministic and runs here, in one call, instead of as
a dozen tool calls each re-sending the whole conversation.

TWO LANES, and `validate` decides which in code:
  fast    a scaffoldable house template, a direct-record or query-list strategy, a current
          readable SDK, a root entity model-facts or a precedent already knows, every
          traversal resolving in the SDK, and none of: computed money, custom layout,
          conflicting sources, unusual grouping.
  expert  anything else. `run` REFUSES an expert-lane plan (exit 20) and prints why: the
          existing process applies, with the full model discovery it involves. Nothing here
          approximates logic it cannot represent.

EVERY FIELD HAS DECLARED PROVENANCE. `provenance` names, for every field a section shows,
where its value comes from - {"kind": "sdk"} (and then `traversals` gives its path),
{"kind": "computed", "reason": ...} or {"kind": "constant", "reason": ...}. Only sdk fields
are resolved against the jar; computed and constant ones are never counted as resolved paths.
`outputs`, `traversals`, `provenance` and every fixture row are cross-checked against the
section fields; a row that omits a field is an error unless `fixture.intentional_blanks`
names it. The masthead fields (rptTitle, rptSubtitle, rptSlug) are constants taken from
`report`, and the generated .jrxml is checked to declare nothing else. Before verifying, each
sdk path is looked for as a property chain in the rule; one that cannot be found sends the
plan to the expert lane, because the plan can then not be shown to describe the rule.

EXIT CODES  0 built and every gate passed    1 a gate failed (diagnostics say which)
            2 invalid plan    3 a judgment file is missing (the rule, or TODO fixture rows)
            4 not enabled (JTI_BUILD_PLAN=opt-in)    20 expert lane
            (the last line is always BUILD-RESULT {json})
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "templates"))

FAST_TEMPLATES = ("record_summary", "eseries_summary", "tabular_list")   # scaffoldable today
STRATEGIES = ("direct-record", "query-list")
FLAGS = ("financial_calc", "custom_layout", "conflicting_sources", "unusual_grouping")
KINDS = ("sdk", "computed", "constant")
MASTHEAD = ("rptTitle", "rptSubtitle", "rptSlug")      # filled from `report`, not from a row
MAX_DEPTH = 8                                          # property hops the resolver will follow
PATH_RE = re.compile(r"^[A-Za-z_$][\w$]*(?:\[\])?(?:\.[A-Za-z_$][\w$]*(?:\[\])?)*$")
SCALAR = (str, int, float, bool)
PRIMITIVE = re.compile(r"^(java\.lang\.|java\.util\.Date$|java\.math\.|java\.sql\.|"
                       r"int$|long$|double$|float$|boolean$|short$|byte$|char$)")

EXAMPLE = {
    "plan_version": 1,
    "lane": "fast",
    "report": {"folder": "Test Builds/Cases By Type", "name": "Cases_By_Type",
               "title": "Cases By Type", "code": "Cases_By_Type",
               "subtitle": "filed in a date range", "slug": "cases-by-type"},
    "template": "tabular_list",
    "root": "Case",
    "rule": "Cases_By_Type_V1.groovy",
    "strategy": {"kind": "query-list", "entity": "Case",
                 "filters": [{"param": "CaseType", "path": "caseType", "op": "addIn"},
                             {"param": "StartDate", "path": "filingDate", "op": "addDateRange"}],
                 "sort": [{"key": "filingDate", "dir": "desc"}]},
    "params": [{"name": "CaseType", "class": "java.lang.String", "coerce": "csv-list"},
               {"name": "StartDate", "class": "java.util.Date", "coerce": "date"}],
    "sections": [{"key": "ROWS", "title": "Cases",
                  "cols": [["Case Number", 20, "Left", "caseNumber"],
                           ["Type", 20, "Left", "caseType"]]}],
    "outputs": {"caseNumber": "str(c?.caseNumber)", "caseType": "str(c?.caseTypeLabel)"},
    "traversals": {"caseNumber": "Case.caseNumber", "caseType": "Case.caseTypeLabel"},
    "provenance": {"caseNumber": {"kind": "sdk"}, "caseType": {"kind": "sdk"}},
    "grouping": None,
    "empty": "one row, 'No rows matched' in caseNumber",
    "missing": "n/a - query-list",
    "fixture": {"rows": [{"caseNumber": "CF-2026-00184", "caseType": "Felony"},
                         {"caseNumber": "JV-2026-00042",
                          "caseType": "Juvenile Delinquent Proceeding Certified As Adult"}],
                "intentional_blanks": [],
                "graph": None},
    "verification": {"variants": ["full", "none"]},
    "assumptions": ["one row per case", "the date range filters filingDate"],
    "unverified": ["caseTypeLabel resolves on the target environment"],
    "specialist": [],
    "flags": {f: False for f in FLAGS},
}


# ── result plumbing ─────────────────────────────────────────────────────────────────────
class Result:
    def __init__(self):
        self.t0 = time.time()
        self.d = {"ok": False, "lane": None, "stage": None, "errors": [], "reasons": [],
                  "resolved": [], "unresolved": [], "artifacts": {}, "gates": None,
                  "perf": {}, "unverified": [], "stages": {}}
        self._stage, self._ts = None, time.time()

    def stage(self, name):
        now = time.time()
        if self._stage:
            self.d["stages"][self._stage] = round(now - self._ts, 3)
        self._stage, self._ts = name, now
        self.d["stage"] = name

    def finish(self, rc):
        last = self._stage
        self.stage(None)
        self.d["stage"] = last               # where it ended - on a failure, where it STOPPED
        self.d["ok"] = rc == 0
        self.d["wall"] = round(time.time() - self.t0, 3)
        print("BUILD-RESULT " + json.dumps(self.d))
        sys.exit(rc)


# ── validation and lane ─────────────────────────────────────────────────────────────────
def validate_schema(p):
    e = []
    need = {"plan_version": int, "lane": str, "report": dict, "template": str, "root": str,
            "rule": str, "strategy": dict, "params": list, "sections": list,
            "traversals": dict, "outputs": dict, "provenance": dict, "fixture": dict,
            "assumptions": list, "unverified": list, "flags": dict}
    for k, t in need.items():
        if k not in p:
            e.append(f"missing '{k}'")
        elif not isinstance(p[k], t):
            e.append(f"'{k}' must be {t.__name__}")
    if e:
        return e
    if p["plan_version"] != 1:
        e.append("plan_version must be 1")
    if p["lane"] not in ("fast", "expert"):
        e.append("lane must be 'fast' or 'expert'")
    for k in ("folder", "name", "title", "code"):
        if not p["report"].get(k):
            e.append(f"report.{k} is required")
        elif not isinstance(p["report"][k], str):
            e.append(f"report.{k} must be a string")
    for k in ("subtitle", "slug"):
        if k in p["report"] and not isinstance(p["report"][k], str):
            e.append(f"report.{k} must be a string")
    for k in ("template", "root", "rule"):
        if not p[k].strip():
            e.append(f"'{k}' must not be empty")
    if p["report"].get("name") and not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,60}$", p["report"]["name"]):
        e.append("report.name must start with a letter and use letters, digits, underscores")
    if not p["sections"]:
        e.append("sections must list at least one section")
    for s in p["sections"]:
        if not isinstance(s, dict) or not s.get("cols"):
            e.append(f"section {s.get('key') if isinstance(s, dict) else s!r} has no cols")
            continue
        for c in s["cols"]:
            if not (isinstance(c, list) and len(c) == 4):
                e.append(f"section {s.get('key')}: a col must be [header, width, align, field]")
            elif not (isinstance(c[3], str) and c[3].strip()):
                e.append(f"section {s.get('key')}: column {c[0]!r} has no field name")
    for prm in p["params"]:
        if not (isinstance(prm, dict) and prm.get("name") and prm.get("class")):
            e.append("each param needs name and class")
    if not isinstance(p["fixture"].get("rows"), list) or not p["fixture"]["rows"]:
        e.append("fixture.rows must list at least one row - awkward ones")
    for f in FLAGS:
        if not isinstance(p["flags"].get(f), bool):
            e.append(f"flags.{f} must be true or false")
    if e:
        return e
    return e + validate_fields(p)


def section_fields(p):
    return [c[3] for s in p["sections"] for c in s["cols"]]


def validate_fields(p):
    """Every field a section shows has exactly one declared source, and outputs, traversals,
    provenance and the fixture rows all describe the SAME set of fields. A field with no
    path used to pass every gate - the fixture answered it - and ship as a blank column."""
    e = []
    fields = section_fields(p)
    seen = set()
    for f in fields:
        if f in seen:
            e.append(f"field '{f}' is shown by more than one column")
        seen.add(f)
    want = set(fields)
    prov, trav, outs = p["provenance"], p["traversals"], p["outputs"]

    for f in fields:
        if f not in prov:
            e.append(f"field '{f}' has no provenance - declare it sdk, computed or constant")
    for f, v in prov.items():
        if f not in want:
            if f in MASTHEAD:
                if not (isinstance(v, dict) and v.get("kind") == "constant"):
                    e.append(f"provenance '{f}': a masthead field is a constant from `report`")
                continue
            e.append(f"provenance for '{f}', which no section shows")
            continue
        if not isinstance(v, dict):
            e.append(f"provenance '{f}' must be an object like {{\"kind\": \"sdk\"}}")
            continue
        kind = v.get("kind")
        if not isinstance(kind, str) or kind not in KINDS:
            e.append(f"provenance '{f}': kind must be one of {', '.join(KINDS)}, not {kind!r}")
            continue
        extra = set(v) - {"kind", "reason"}
        if extra:
            e.append(f"provenance '{f}': unexpected key(s) {', '.join(sorted(extra))}")
        reason = v.get("reason")
        if kind == "sdk":
            if "reason" in v and not isinstance(reason, str):
                e.append(f"provenance '{f}': reason must be a string")
            if f not in trav:
                e.append(f"field '{f}' is declared sdk but has no traversal")
        else:
            if not (isinstance(reason, str) and reason.strip()):
                e.append(f"provenance '{f}' is {kind} - it needs a reason a person can read")
            if f in trav:
                e.append(f"field '{f}' is {kind} but also has a traversal - it would be counted"
                         f" as a resolved SDK path")

    for f, path in trav.items():
        if f not in want:
            e.append(f"traversal for '{f}', which no section shows")
            continue
        if not isinstance(path, str) or not path.strip():
            e.append(f"traversal '{f}' must be a non-empty string path like Case.caseNumber")
            continue
        if not PATH_RE.match(path):
            e.append(f"traversal '{f}': malformed path {path!r} (Entity.property.property)")
            continue
        if len(path.split(".")) < 2:
            e.append(f"traversal '{f}': {path!r} is only the root entity - name the property")
            continue

    for f in fields:
        if f not in outs:
            e.append(f"field '{f}' has no entry in outputs")
    for f, v in outs.items():
        if f not in want:
            e.append(f"output '{f}', which no section shows")
        elif not (isinstance(v, str) and v.strip()):
            e.append(f"output '{f}' must be a non-empty string")

    blanks = p["fixture"].get("intentional_blanks", [])
    if not isinstance(blanks, list) or not all(isinstance(b, str) for b in blanks):
        e.append("fixture.intentional_blanks must be a list of field names")
        blanks = []
    for b in blanks:
        if b not in want:
            e.append(f"fixture.intentional_blanks names '{b}', which no section shows")
    for i, r in enumerate(p["fixture"]["rows"], 1):
        if isinstance(r, dict):
            for k in r:
                if k not in want:
                    e.append(f"fixture row {i}: '{k}' is not a field any section shows")
            for f in fields:
                if f not in r and f not in blanks:
                    e.append(f"fixture row {i} omits '{f}' - give a value, or list it in"
                             f" fixture.intentional_blanks if the blank is the point")
            bad = [k for k, v in r.items() if k in want and not isinstance(v, SCALAR)]
        elif isinstance(r, list):
            if len(r) != len(fields):
                e.append(f"fixture row {i} has {len(r)} values for {len(fields)} fields")
            bad = [fields[j] for j, v in enumerate(r[:len(fields)]) if not isinstance(v, SCALAR)]
        else:
            e.append(f"fixture row {i} must be an object or a list")
            continue
        for k in bad:
            e.append(f"fixture row {i}: '{k}' must be text or a number")
    return e


def project_of(folder):
    """The project a report folder belongs to - its parent - as an ABSOLUTE path under the
    workspace root. Plan folders are relative to the workspace, not to wherever this runs:
    resolving them against the cwd (the plugin, usually) looked outside the workspace and
    the SDK check refused."""
    import project as P
    return str(P.ROOT / (os.path.dirname(folder.rstrip("/")) or "."))


def sdk_decision(p):
    r = subprocess.run([sys.executable, os.path.join(HERE, "project.py"), "sdk-decide",
                        project_of(p["report"]["folder"])], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def known_entity(root):
    """Does model-facts or a precedent already know this root? Novel entities go expert."""
    import facts as F
    text = open(F.FACTS, encoding="utf8").read()
    secs = F.sections(text)
    vocab = F.vocabulary(text)
    if any(F.hit_entity(root, s, F.tags(s, vocab)) for s in secs):
        return "model-facts"
    import precedents as PR
    import project as P
    for d in PR.report_dirs(str(P.ROOT)):
        if PR.describe(d)["root"].lower() == root.lower():
            return "precedent " + os.path.basename(d)
    return None


def lane_reasons(p, sdk_rc, sdk_line):
    """Every reason the plan cannot take the fast lane. Empty list = fast."""
    r = []
    if p["template"] not in FAST_TEMPLATES:
        r.append(f"template {p['template']!r} is not scaffoldable "
                 f"(fast lane: {', '.join(FAST_TEMPLATES)})")
    if p["strategy"].get("kind") not in STRATEGIES:
        r.append(f"strategy {p['strategy'].get('kind')!r} is not an established pattern "
                 f"({' or '.join(STRATEGIES)})")
    if sdk_rc != 0:
        r.append(f"SDK: {sdk_line}")
    for f in FLAGS:
        if p["flags"].get(f):
            r.append(f"flagged {f}")
    for f, path in p["traversals"].items():
        head = path.split(".")[0].replace("[]", "")
        if head.rsplit(".", 1)[-1] != p["root"]:
            r.append(f"traversal '{f}' starts at {head}, not the root {p['root']}")
    if not known_entity(p["root"]):
        r.append(f"root entity {p['root']!r} is in neither model-facts.md nor any precedent")
    return r


# ── batched field resolution against the SDK ───────────────────────────────────────────
def jrs():
    return os.environ.get("JRS", "/Applications/jasperreports-server-9.0.0")


def sdk_jar(p):
    import project as P
    folder = P._under_root(project_of(p["report"]["folder"]))
    if folder is None:
        return None
    sdk = P._meta(folder).get("sdk")
    if not sdk:
        return None
    path = folder / sdk["stored"]
    return str(path) if path.exists() else None


class Model:
    """Class members from the SDK jar, loaded in ROUNDS: every class needed at this depth,
    across every path, in ONE javap run. sdk_fields.py pays a JVM per class in the chain."""

    def __init__(self, jar):
        self.jar, self.cache, self.javap_runs = jar, {}, 0
        with zipfile.ZipFile(jar) as z:
            self.names = [n[:-6].replace("/", ".") for n in z.namelist() if n.endswith(".class")]

    def fqcn(self, short):
        if "." in short:
            return short, None
        hits = [n for n in self.names if n.endswith("." + short)]
        if len(hits) == 1:
            return hits[0], None
        return None, ("ambiguous: " + ", ".join(sorted(hits)[:4])) if hits else "not in the jar"

    def load(self, classes):
        want = {c for c in classes if c and c not in self.cache}
        while want:
            self.javap_runs += 1
            r = subprocess.run([os.path.join(jrs(), "java", "bin", "javap"),
                                "-J-XX:TieredStopAtLevel=1", "-p", "-classpath", self.jar,
                                *sorted(want)], capture_output=True, text=True)
            chunk, cls = [], None
            got = {}
            for ln in r.stdout.splitlines():
                m = re.match(r"^(?:public |protected |private |abstract |final |static )*"
                             r"(?:class|interface|enum)\s+([\w.$]+)(?:<[^>]*>)?"
                             r"(?:\s+extends\s+([\w.$]+))?", ln)
                if m:
                    if cls:
                        got[cls] = (chunk, sup)
                    cls, sup, chunk = m.group(1), m.group(2), []
                elif cls:
                    chunk.append(ln)
            if cls:
                got[cls] = (chunk, sup)
            nxt = set()
            for c in want:
                if c not in got:
                    self.cache[c] = None                     # javap could not read it
                    continue
                lines, sup = got[c]
                members = {}
                for ln in lines:
                    f = re.match(r"\s+(?:private|public|protected)?\s*(?:static\s+)?(?:final\s+)?"
                                 r"([\w.$<>\[\], ?]+?)\s+(\w+);\s*$", ln)
                    if f and "(" not in ln:
                        members.setdefault(f.group(2), ("field", f.group(1).strip()))
                        continue
                    g = re.match(r"\s+public\s+([\w.$<>\[\], ?]+?)\s+(get|is)(\w+)\(\);\s*$", ln)
                    if g:
                        prop = g.group(3)[0].lower() + g.group(3)[1:]
                        members.setdefault(prop, ("getter", g.group(1).strip()))
                self.cache[c] = {"super": sup, "members": members}
                if sup and sup != "java.lang.Object" and sup not in self.cache:
                    nxt.add(sup)
            want = nxt

    def member(self, cls, name):
        seen = 0
        while cls and cls != "java.lang.Object" and seen < 12:
            info = self.cache.get(cls)
            if not info:
                return None
            if name in info["members"]:
                return info["members"][name] + (cls,)
            cls, seen = info["super"], seen + 1
        return None


def element(t):
    """A field's type -> the class a traversal continues into (collections unwrapped)."""
    m = re.match(r"^[\w.$]+<\s*([\w.$]+)\s*>$", t)
    if m:
        return m.group(1)
    return t if "<" not in t and "[" not in t else None


def resolve(p, res):
    jar = sdk_jar(p)
    if not jar:
        res.d["errors"].append("no readable SDK jar registered for this project")
        return None
    model = Model(jar)
    todo = []          # (key, segments, current class)
    for key, path in p["traversals"].items():
        segs = [s.replace("[]", "") for s in path.split(".") if s]
        start, err = model.fqcn(segs[0])
        if not start:
            res.d["unresolved"].append({"field": key, "path": path, "at": segs[0], "why": err})
            continue
        todo.append((key, path, segs[1:], start))
    depth = 0
    while todo and depth < MAX_DEPTH:
        depth += 1
        model.load({c for _, _, _, c in todo})
        # the chains of every class needed this round, loaded in the same pass
        nxt = []
        for key, path, segs, cls in todo:
            m = model.member(cls, segs[0])
            if not m:
                why = "class not readable in the SDK" if model.cache.get(cls) is None else \
                      f"no field or getter '{segs[0]}' on {cls.rsplit('.', 1)[-1]} or its supers"
                res.d["unresolved"].append({"field": key, "path": path, "at": segs[0], "why": why})
                continue
            kind, typ, owner = m
            if len(segs) == 1:
                res.d["resolved"].append({"field": key, "path": path, "kind": kind, "type": typ,
                                          "on": owner.rsplit(".", 1)[-1]})
                continue
            el = element(typ)
            if not el or PRIMITIVE.match(el):
                res.d["unresolved"].append({"field": key, "path": path, "at": segs[1],
                                            "why": f"cannot follow '{segs[0]}' ({typ})"})
                continue
            nxt.append((key, path, segs[1:], el))
        todo = nxt
    # Anything still walking when the limit is reached is NOT proven - it used to vanish
    # from both lists, so a deep path counted as neither resolved nor unresolved.
    for key, path, segs, cls in todo:
        res.d["unresolved"].append({"field": key, "path": path, "at": segs[0],
                                    "why": f"depth limit ({MAX_DEPTH} hops) reached - not proven"})
    res.d["perf"]["javap_runs"] = model.javap_runs
    return model


# ── cross-checks against the files the plan describes ─────────────────────────────────
def rule_misses(p, rule_text):
    """sdk paths that cannot be found as a property chain in the rule. Only the direction
    that can be shown safely is checked - that the rule READS what the plan says; property
    reads in the rule that the plan does not list are not reported. A path read another way
    (a collect over a collection, a helper, a variable in between) is not recognised, and
    the plan then goes to the expert lane rather than being trusted."""
    t = re.sub(r"//[^\n]*|/\*.*?\*/", " ", rule_text, flags=re.S).replace("?.", ".")
    miss = []
    for f, path in p["traversals"].items():
        segs = [x.replace("[]", "") for x in path.split(".")[1:]]
        if not re.search(r"\." + r"\s*\.\s*".join(map(re.escape, segs)) + r"\b", t):
            miss.append((f, path, "." + ".".join(segs)))
    return miss


def jrxml_extras(p, jrxml_path):
    """Fields the generated .jrxml declares that the plan gives no provenance for."""
    t = open(jrxml_path, encoding="utf8").read()
    declared = re.findall(r'<field\s+name="([^"]+)"', t)
    known = set(section_fields(p)) | set(MASTHEAD)
    return [f for f in declared if f not in known]


# ── mechanical steps ────────────────────────────────────────────────────────────────────
def write_spec(p, folder):
    spec = {"name": p["report"]["name"], "title": p["report"]["title"],
            "template": p["template"], "sections": p["sections"],
            "params": [[x["name"], x["class"]] for x in p["params"]],
            "root": p["root"], "variants": (p.get("verification") or {}).get("variants")
            or ["full", "none"], "intent": p.get("intent", ""), "meta": [], "tiles": []}
    path = os.path.join(folder, "spec.json")
    old = {}
    if os.path.exists(path):
        try:
            old = json.load(open(path))
        except ValueError:
            old = {}
    old.update(spec)
    old["build_plan"] = "build-plan.json"
    json.dump(old, open(path, "w"), indent=2)
    return path


def fill_fixture_py(p, folder):
    """Put the plan's rows and masthead values into the scaffold's fixture.py - only where
    the scaffold left its TODOs. Hand-written rows are never overwritten."""
    fx = os.path.join(folder, "verification", "fixture.py")
    t = open(fx, encoding="utf8").read()
    changed = False
    m = re.search(r"(?m)^# TODO: real, awkward rows\. Columns: (.+)$", t)
    if m and "TODO " in t[m.end():t.find("]", m.end())]:
        cols = [c.strip() for c in m.group(1).split(",")]
        if set(cols) != set(section_fields(p)):
            return None, [f"the scaffold's fixture columns ({', '.join(cols)}) are not the"
                          f" plan's fields ({', '.join(section_fields(p))})"]
        rows = []
        for r in p["fixture"]["rows"]:
            # validate_fields guarantees every field is present or declared blank
            vals = ([str(r[c]) if c in r else "" for c in cols] if isinstance(r, dict)
                    else [str(r[section_fields(p).index(c)]) for c in cols])
            rows.append("    (" + ", ".join(json.dumps(v) for v in vals) + ("," if len(vals) == 1 else "") + "),")
        start = t.index("ROWS = [", m.start())
        end = t.index("\n]", start) + 2
        t = t[:start] + "ROWS = [\n" + "\n".join(rows) + "\n]" + t[end:]
        changed = True
    for k, v in (("rptSubtitle", p["report"].get("subtitle")), ("rptSlug", p["report"].get("slug"))):
        if v and f'"{k}": "TODO {k}"' in t:
            t = t.replace(f'"{k}": "TODO {k}"', f'"{k}": {json.dumps(v)}')
            changed = True
    if changed:
        open(fx, "w", encoding="utf8").write(t)
    left = [ln.strip() for ln in t.splitlines() if re.search(r'"TODO |\("TODO', ln)]
    return changed, left


def groovy_literal(v):
    if isinstance(v, dict):
        return "[" + (", ".join(f"{k}: {groovy_literal(x)}" for k, x in v.items()) or ":") + "]"
    if isinstance(v, list):
        return "[" + ", ".join(groovy_literal(x) for x in v) + "]"
    if v is None:
        return "null"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def fill_fixture_groovy(p, folder):
    """The plan's object graph, when it gives one, replaces the scaffold's two-key default."""
    g = (p.get("fixture") or {}).get("graph")
    if not g:
        return False
    fx = os.path.join(folder, "verification", "Fixture.groovy")
    t = open(fx, encoding="utf8").read() if os.path.exists(fx) else ""
    if t and not re.search(r"(?m)^ROOT_FIXTURE = \[id: '19', \w+: '[^']*'\]$", t):
        return False                                  # hand-edited - leave it alone
    body = ("// Object graph for " + p["report"]["title"] + " - written by build_plan.py from\n"
            "// build-plan.json. Drives rulecheck.groovy, NOT the page render.\n"
            f"ROOT_FIXTURE = {groovy_literal(g.get('root') or {})}\n\n"
            f"SEARCH_RESULTS = {groovy_literal(g['search_results']) if g.get('search_results') else '[ROOT_FIXTURE]'}\n")
    open(fx, "w", encoding="utf8").write(body)
    return True


def fill_notes(p, folder, res):
    """Replace a NOTES block ONLY while it still holds contract_docs' untouched seed."""
    import contract_docs as CD
    wrote = []
    derived = p.get("derived")
    con = ["SECTION ORDER and FIELDS BY SECTION - from build-plan.json:"]
    for s in p["sections"]:
        con.append(f"    {s.get('key', 'ROWS'):<12} {s.get('title', '')}: "
                   + ", ".join(c[3] for c in s["cols"]))
    con.append("")
    con.append("TRAVERSALS, checked against the SDK jar (resolving is NOT proof of a value):")
    for r in res.d["resolved"]:
        con.append(f"    {r['field']:<18} {r['path']:<40} {r['kind']} on {r['on']}")
    for r in res.d["unresolved"]:
        con.append(f"    {r['field']:<18} {r['path']:<40} UNRESOLVED at {r['at']}: {r['why']}")
    notsdk = [(f, v) for f, v in p["provenance"].items() if f not in MASTHEAD and v["kind"] != "sdk"]
    if notsdk:
        con += ["", "NOT FROM THE SDK (never counted as a resolved path):"]
        con += [f"    {f:<18} {v['kind']}: {v['reason']}" for f, v in notsdk]
    con.append(f"    {'rptTitle/Subtitle/Slug':<18} constant: the masthead, from build-plan.json report")
    if p["assumptions"]:
        con += ["", "ASSUMPTIONS - decisions made without asking:"] + [f"  - {a}" for a in p["assumptions"]]
    if derived:
        con += ["", "COLUMNS DERIVED FROM THE BRIEF:"] + [f"  - {c}" for c in derived.get("columns", [])]
    con += ["", "WHAT IS NOT PROVEN:",
            "  - every traversal: the fixture answers every property, so a green render proves"
            " the page, not that a path resolves in the target environment"]
    con += [f"  - {u}" for u in p["unverified"]]
    reg = ["From build-plan.json:"]
    for prm in p["params"]:
        req = "REQUIRED" if prm.get("required") else "OPTIONAL"
        reg.append(f"  - {prm['name']} ({prm['class']}) {req}"
                   + (f"; coerced as {prm['coerce']}" if prm.get("coerce") else ""))
    reg.append(f"  - strategy: {p['strategy'].get('kind')}; empty result: {p.get('empty') or 'n/a'};"
               f" unresolvable id: {p.get('missing') or 'n/a'}")
    if any(prm.get("required") for prm in p["params"]):
        reg.append("  - rule_zip.py emits every input OPTIONAL: set the REQUIRED ones by hand after"
                   " importing, or build the zip with rule_import.py --input name:type::REQUIRED")
    for fn, block in (("JRXML_CONTRACT.txt", con), ("RULE_REGISTRATION.txt", reg)):
        path = os.path.join(folder, fn)
        if not os.path.exists(path):
            continue
        t = open(path, encoding="utf8").read()
        m = re.search(re.escape(CD.BEGIN) + r"\n(.*?)\n" + re.escape(CD.END), t, re.S)
        if m and m.group(1).startswith("TODO before this ships"):
            t = t[:m.start(1)] + "\n".join(block) + t[m.end(1):]
            open(path, "w", encoding="utf8").write(t)
            wrote.append(fn)
    return wrote


def inventory(p, folder):
    names = os.listdir(folder)
    vdir = os.path.join(folder, "verification")
    v = os.listdir(vdir) if os.path.isdir(vdir) else []
    return {"rule": p["rule"] if p["rule"] in names else None,
            "jrxml": next((n for n in names if n.endswith(".jrxml")), None),
            "zip": next((n for n in names if n.startswith("RULE-") and n.endswith(".zip")), None),
            "registration": "RULE_REGISTRATION.txt" in names,
            "contract": "JRXML_CONTRACT.txt" in names,
            "pdfs": sorted(n for n in v if n.endswith(".pdf")),
            "pages": sorted(n for n in v if n.endswith(".png"))}


# ── commands ────────────────────────────────────────────────────────────────────────────
def load(path, res):
    dups = []

    def pairs(kv):
        # json.load keeps the LAST of two equal keys and says nothing - a field declared
        # twice would silently lose one of its declarations.
        d = {}
        for k, v in kv:
            if k in d:
                dups.append(k)
            d[k] = v
        return d
    try:
        p = json.load(open(path, encoding="utf8"), object_pairs_hook=pairs)
    except (OSError, ValueError) as e:
        res.d["errors"].append(f"cannot read the plan: {e}")
        res.finish(2)
    if not isinstance(p, dict):
        res.d["errors"].append("the plan must be a JSON object")
        res.finish(2)
    errs = [f"key '{k}' is given more than once" for k in dict.fromkeys(dups)]
    errs += validate_schema(p)
    if errs:
        res.d["errors"] += errs
        for e in errs:
            print(f"  PLAN  {e}")
        res.finish(2)
    return p


def cmd_validate(path, res, quiet=False):
    res.stage("validate")
    p = load(path, res)
    rc, line = sdk_decision(p)
    reasons = lane_reasons(p, rc, line)
    res.d["provenance"] = {f: p["provenance"][f]["kind"] for f in section_fields(p)}
    res.d["provenance"].update({m: "constant" for m in MASTHEAD})
    res.d["lane"] = "expert" if (reasons or p["lane"] == "expert") else "fast"
    res.d["reasons"] = reasons
    res.d["sdk"] = line
    if not quiet:
        print(f"  plan    {p['report']['name']} ({p['template']}, {p['strategy'].get('kind')}, root {p['root']})")
        print(f"  {line}")
        if reasons:
            print("  EXPERT LANE - the fast path cannot represent this safely:")
            for r in reasons:
                print(f"    - {r}")
        else:
            print("  FAST LANE - eligible")
    return p


def cmd_resolve(path, res, quiet=False):
    p = cmd_validate(path, res, quiet=True)
    res.stage("resolve")
    resolve(p, res)
    if not quiet:
        for e in res.d["errors"]:
            print(f"  ERROR   {e}")
        for r in res.d["resolved"]:
            print(f"  ok      {r['field']:<18} {r['path']:<40} {r['kind']} on {r['on']} ({r['type']})")
        for r in res.d["unresolved"]:
            print(f"  MISSING {r['field']:<18} {r['path']:<40} at '{r['at']}': {r['why']}")
        print(f"  {len(res.d['resolved'])} resolved, {len(res.d['unresolved'])} unresolved, "
              f"{res.d['perf'].get('javap_runs', 0)} javap run(s)")
    return p


def cmd_run(path, res):
    p = cmd_validate(path, res)
    if res.d["lane"] == "expert":
        print("  -> use the existing build process (it still gets the fast verifier).")
        res.d["stage"] = "lane"
        res.finish(20)
    res.stage("resolve")
    resolve(p, res)
    if res.d["errors"] or res.d["unresolved"]:
        for r in res.d["unresolved"]:
            print(f"  UNRESOLVED {r['field']}: {r['path']} at '{r['at']}' - {r['why']}")
        for e in res.d["errors"]:
            print(f"  ERROR {e}")
        print("  A path the SDK cannot resolve prints a BLANK COLUMN with no error. Fix the path,"
              " or take the expert lane.")
        res.d["lane"] = "expert"
        res.d["reasons"].append("a traversal does not resolve in the SDK")
        res.finish(20)
    import project as P
    folder = str(P.ROOT / p["report"]["folder"])
    os.makedirs(folder, exist_ok=True)

    res.stage("scaffold")
    spec = write_spec(p, folder)
    s = subprocess.run([sys.executable, os.path.join(HERE, "scaffold.py"), spec, "--out", folder],
                       capture_output=True, text=True)
    if s.returncode != 0:
        print(s.stdout + s.stderr)
        res.d["errors"].append("scaffold.py refused the plan")
        res.finish(2)

    res.stage("fields")
    jrp = os.path.join(folder, f"{p['report']['name']}.jrxml")   # scaffold.py ran gen_jrxml.py
    if not os.path.exists(jrp):
        res.d["errors"].append(f"scaffold.py did not produce {os.path.basename(jrp)}")
        res.finish(2)
    extras = jrxml_extras(p, jrp)
    if extras:
        res.d["errors"].append("the .jrxml declares field(s) with no provenance: " + ", ".join(extras))
        print("  the generated .jrxml declares fields the plan does not account for:"
              f" {', '.join(extras)}")
        res.finish(2)

    res.stage("fixtures")
    changed, left = fill_fixture_py(p, folder)
    if changed is None:
        res.d["errors"] += left
        print("  " + left[0])
        res.finish(2)
    graph = fill_fixture_groovy(p, folder)
    print(f"  fixtures  fixture.py {'filled from the plan' if changed else 'kept'}; "
          f"Fixture.groovy {'written from the plan' if graph else 'kept'}")
    if left:
        res.d["errors"].append("fixture.py still has TODO values: " + "; ".join(left[:3]))
        print("  fixture.py still holds TODOs - give the plan real, awkward rows")
        res.finish(3)

    res.stage("rule")
    if not os.path.exists(os.path.join(folder, p["rule"])):
        res.d["errors"].append(f"{p['rule']} is not written yet - it is the judgment file")
        print(f"  write {p['rule']} (the rule is never generated), then run this again")
        res.finish(3)
    miss = rule_misses(p, open(os.path.join(folder, p["rule"]), encoding="utf8").read())
    if miss:
        for f, path, chain in miss:
            print(f"  RULE    {f}: the plan says {path}, but the rule never reads '{chain}'")
            res.d["reasons"].append(f"the rule does not visibly read {path} ({f}) - the plan"
                                    f" cannot be shown to describe the rule")
        print("  -> expert lane: fix the plan or the rule so they agree, or build it the"
              " existing way.")
        res.d["lane"] = "expert"
        res.finish(20)
    res.d["unverified"].append("property reads in the rule that the plan does not list"
                               " are not checked")

    res.stage("verify")
    jr = f"{p['report']['name']}.jrxml"
    # The verifier is its OWN switch: the plan runs whichever one JTI_VERIFIER selects.
    env = dict(os.environ)
    v = subprocess.run([os.path.join(HERE, "finish.sh"), p["rule"], jr, "--code",
                        p["report"]["code"], "--name", p["report"]["title"],
                        "--template", p["template"]], cwd=folder, env=env,
                       capture_output=True, text=True)
    out = v.stdout + v.stderr
    print(out.rstrip())
    st = re.search(r"^VERIFY-STATS (\{.*\})$", out, re.M)
    gate = re.search(r"GATE ([\d.]+) FAILED - (.+)", out)
    res.d["gates"] = {"rc": v.returncode, "failed_gate": gate.group(1) if gate else None,
                      "why": gate.group(2).strip() if gate else None}
    if st:
        res.d["perf"].update(json.loads(st.group(1)))
    if v.returncode != 0:
        res.finish(1)

    res.stage("notes")
    wrote = fill_notes(p, folder, res)
    if wrote:
        print(f"  notes     filled from the plan: {', '.join(wrote)} (review them)")

    res.stage("inventory")
    inv = inventory(p, folder)
    res.d["artifacts"] = inv
    res.d["unverified"] = p["unverified"]
    missing = [k for k in ("rule", "jrxml", "zip") if not inv[k]] + \
              [k for k in ("registration", "contract") if not inv[k]]
    if missing:
        res.d["errors"].append("missing artifacts: " + ", ".join(missing))
        res.finish(1)
    print(f"  delivered {inv['rule']}, {inv['jrxml']}, {inv['zip']} + both docs; "
          f"{len(inv['pdfs'])} PDF(s), {len(inv['pages'])} page image(s) - LOOK AT EVERY PAGE")
    res.finish(0)


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?")
    ap.add_argument("plan", nargs="?")
    ap.add_argument("--example", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.example:
        print(json.dumps(EXAMPLE, indent=2)); return 0
    if a.help or a.cmd not in ("validate", "resolve", "run") or not a.plan:
        print(__doc__); return 0 if a.help else 2
    res = Result()
    # OPT-IN for the initial release, independently of every other switch.
    import build_mode
    if build_mode.resolve()[0]["build_plan"] != "opt-in":
        print("  build_plan.py is OFF. It is opt-in for this release: set JTI_BUILD_PLAN=opt-in.")
        print("  (JTI_REPORT_BUILD_MODE=fast does not enable it.)")
        res.d["errors"].append("build plan not enabled (JTI_BUILD_PLAN=opt-in)")
        res.stage("switch")
        res.finish(4)
    if a.cmd == "validate":
        cmd_validate(a.plan, res)
        res.finish(0 if res.d["lane"] == "fast" else 20)
    if a.cmd == "resolve":
        cmd_resolve(a.plan, res)
        res.finish(0 if not res.d["unresolved"] and not res.d["errors"] else 1)
    cmd_run(a.plan, res)


if __name__ == "__main__":
    main()
