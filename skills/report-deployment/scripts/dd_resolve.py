#!/usr/bin/env python3
"""dd_resolve.py - resolve a search path against an eSeries Data Dictionary export.

    python3 dd_resolve.py <DataDictionary.xlsx> Case parties.person.lastName status receivedDate

For each path: does every hop exist, what is the terminal entityClass.field the FORM export
records, and what the field's type means for a search criterion (a lookup list -> a picker
with LABEL format; a Date -> a range). A path that does not resolve is REFUSED, loudly: in a
search, a wrong field name does not error - it silently matches nothing.

WHY THE DATA DICTIONARY, NOT THE SDK JAR. The jar is a stub: derived getters are stripped, so
`Party` has setPerson(Person) and no getPerson(), and `parties.person.lastName` cannot be
walked from it. The DD types every field directly - a to-one relation as the bare entity name
(`Person`), a to-many as `Collection (Party)`, a picker as `Lookup List (CASE_STATUS)` - and
carries the lookup-list NAME, which no FORM export ever does.

It is PER-ENVIRONMENT: cf_* fields and lookup lists differ between clients, so resolve against
the dictionary of the environment the search will be imported into.

Class names: the DD gives short entity names; the export wants the fully-qualified class.
Those are learned from the FORM exports' own <string> terminals where available, then from an
SDK jar's class list, and an ambiguous or unknown short name is refused rather than guessed.
"""
import glob
import os
import re
import sys
import zipfile

_DD = {}
JAR = None
JAVAP_GLOB = "/Applications/jasperreports-server-*/java/bin/javap"
_JP = {}


def _javap(jar, fqcn):
    """javap output for a class, cached. There is no system JVM on this host; the one bundled
    with JasperReports is used."""
    import subprocess
    key = (jar, fqcn)
    if key not in _JP:
        jp = sorted(glob.glob(JAVAP_GLOB))
        if not jp or not jar:
            _JP[key] = ""
        else:
            r = subprocess.run([jp[-1], "-cp", jar, fqcn], capture_output=True, text=True)
            _JP[key] = r.stdout
    return _JP[key]


def _sdk_getter(jar, fqcn, seg):
    """Return type of getSeg() on fqcn or any com.sustain superclass, from the SDK jar."""
    want = "get" + seg[0].upper() + seg[1:] + "("
    c = fqcn
    while c and c.startswith("com.sustain"):
        out = _javap(jar, c)
        for line in out.splitlines():
            if want in line:
                m = re.search(r"public\s+([\w.<>]+)\s+get", line)
                if m:
                    return m.group(1)
        m = re.search(r"extends ([\w.]+)", out)
        c = m.group(1) if m else None
    return None


def xlsx_rows(path):
    """Rows of the first sheet, as lists of strings - standard library only.

    An .xlsx is a zip of XML. Reading it directly keeps this command free of third-party
    packages: stock python3 on a Mac has no openpyxl, and the rest of this plugin runs on the
    standard library, so a teammate would otherwise hit an ImportError the first time they ran
    it. Verified to give the identical model as openpyxl on every dictionary on this machine.
    """
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheet = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))[0]
        root = ET.fromstring(z.read(sheet))
    col = lambda ref: sum((ord(ch) - 64) * 26 ** i
                          for i, ch in enumerate(reversed(re.match(r"[A-Z]+", ref).group()))) - 1
    for row in root.iter(f"{{{ns['m']}}}row"):
        vals = {}
        for c in row.findall("m:c", ns):
            t, v = c.get("t"), c.find("m:v", ns)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
            else:
                val = v.text if v is not None else ""
            vals[col(c.get("r"))] = val or ""
        width = max(vals) + 1 if vals else 0
        yield [vals.get(i, "") for i in range(width)]


def load_dd(path):
    """{entity: {field: type}} from the export. Entity rows have a name in column A; field
    rows have column A blank (whitespace) and the field in B, its type in C."""
    if path in _DD:
        return _DD[path]
    dd, cur = {}, None
    for r in xlsx_rows(path):
        c = [("" if v is None else str(v)) for v in r] + [""] * 4
        if c[0].strip():
            cur = c[0].strip()
            dd.setdefault(cur, {})
        elif cur and c[1].strip():
            dd[cur][c[1].strip()] = c[2].strip()
    _DD[path] = dd
    return dd


def learn_fqcn(form_zips=(), jars=()):
    """short entity name -> fully-qualified class, from exports first (authoritative: what
    the platform itself wrote) then from SDK jars. Ambiguous names map to None."""
    seen = {}

    def add(fq):
        short = fq.rsplit(".", 1)[-1]
        seen.setdefault(short, set()).add(fq)

    for z in form_zips:
        try:
            with zipfile.ZipFile(z) as zz:
                for n in zz.namelist():
                    for t in re.findall(r"&lt;string&gt;(com\.sustain\.[\w.]+)\.\w+&lt;/string&gt;",
                                        zz.read(n).decode("utf8", "replace")):
                        add(t)
        except (zipfile.BadZipFile, OSError):
            pass
    from_exports = {k: v for k, v in seen.items()}
    for j in jars:
        try:
            with zipfile.ZipFile(j) as zz:
                for n in zz.namelist():
                    m = re.fullmatch(r"(com/sustain/[\w/]+/model/\w+)\.class", n)
                    if m and "$" not in n:
                        fq = m.group(1).replace("/", ".")
                        short = fq.rsplit(".", 1)[-1]
                        if short not in from_exports:          # exports win
                            seen.setdefault(short, set()).add(fq)
        except (zipfile.BadZipFile, OSError):
            pass
    return {k: (next(iter(v)) if len(v) == 1 else None) for k, v in seen.items()}


SCALARS = {"boolean", "Boolean", "int", "Integer", "long", "Long", "double", "Double",
           "Date", "DateTime", "Timestamp", "Widget", ""}


def _is_entity_name(t):
    return bool(re.fullmatch(r"[A-Z]\w*", t)) and t not in SCALARS


def resolve(dd, fqcn, root, path, jar=None):
    """-> dict(ok, terminal, type, lookup, lookup_list, range, source, why).

    The Data Dictionary first. For a hop into an entity the DD has no section for - the DD
    export leaves the whole financial module out (TillDef, AssessmentGroup, PMInstrumentItem,
    Restitution, AgencyAccount, CreditAuthorization are in no dictionary on this machine) - the
    walk continues from the SDK jar's getters. In SDK mode a field's LOOKUP LIST cannot be
    known (a lookup getter just returns String), so `lookup` comes back None and the spec has
    to say it.
    """
    segs = path.replace("[]", "").split(".")
    cur, sdk = root, False
    if cur not in dd:
        if jar and fqcn.get(root):
            cur, sdk = fqcn[root], True          # a root the DD omits (e.g. CheckBatch)
        else:
            return {"ok": False, "why": f"root entity {root!r} is not in this data dictionary"
                                       + ("" if jar else "; pass an SDK jar")}
    for seg in segs[:-1]:
        if not sdk:
            t = dd[cur].get(seg)
            if t is None:
                if jar and fqcn.get(cur) and _sdk_getter(jar, fqcn[cur], seg):
                    sdk, cur = True, fqcn[cur]
                    rt = _sdk_getter(jar, cur, seg)
                    m = re.search(r"<([\w.]+)>", rt)
                    cur = m.group(1) if m else rt
                    if not cur.startswith("com.sustain"):
                        return {"ok": False, "why": f"{seg} is {rt}, not a relation"}
                    continue
                return {"ok": False, "why": f"{cur} has no field {seg!r}"}
            m = re.fullmatch(r"Collection \((\w+)\)", t)
            nxt = m.group(1) if m else (t if _is_entity_name(t) else None)
            if not nxt:
                return {"ok": False, "why": f"{cur}.{seg} is {t!r}, not a relation - cannot walk past it"}
            if nxt not in dd:
                if not jar:
                    return {"ok": False, "why": f"{cur}.{seg} points at {nxt!r}, which has no section "
                                               f"in this data dictionary; pass an SDK jar to walk it"}
                if not fqcn.get(nxt):
                    return {"ok": False, "why": f"cannot name the class for {nxt!r} unambiguously"}
                sdk, cur = True, fqcn[nxt]
                continue
            cur = nxt
        else:
            rt = _sdk_getter(jar, cur, seg)
            if not rt:
                return {"ok": False, "why": f"no getter for {seg!r} on {cur} in the SDK jar"}
            m = re.search(r"<([\w.]+)>", rt)
            cur = m.group(1) if m else rt
            if not cur.startswith("com.sustain"):
                return {"ok": False, "why": f"{seg} is {rt}, not a relation - cannot walk past it"}
            # back to the dictionary as soon as it covers this entity: the jar is the weaker
            # source (it strips derived getters - Party has no getPerson), so a walk that dipped
            # into it for a financial hop must not stay there when it reaches Party
            if cur.rsplit(".", 1)[-1] in dd and fqcn.get(cur.rsplit(".", 1)[-1]) == cur:
                cur, sdk = cur.rsplit(".", 1)[-1], False
    last = segs[-1]
    if not sdk:
        t = dd[cur].get(last)
        if t is None:
            # base fields every entity inherits (id, dateCreated, ...) are not listed in the DD
            if jar and fqcn.get(cur) and _sdk_getter(jar, fqcn[cur], last):
                rt = _sdk_getter(jar, fqcn[cur], last)
                return {"ok": True, "terminal": f"{fqcn[cur]}.{last}", "type": rt,
                        "entity": cur, "lookup": None, "lookup_list": None,
                        "range": rt.endswith("Date"), "source": "sdk",
                        "why": "ok (not in the dictionary; found on the SDK class)"}
            return {"ok": False, "why": f"{cur} has no field {last!r}"}
        if t == "Widget":
            return {"ok": False, "why": f"{cur}.{last} is a Widget, not a data field"}
        fq = fqcn.get(cur)
        if not fq:
            return {"ok": False, "why": f"cannot name the class for {cur!r} unambiguously"}
        lk = re.fullmatch(r"Lookup List \((\w+)\)", t)
        return {"ok": True, "terminal": f"{fq}.{last}", "type": t, "entity": cur,
                "lookup": bool(lk), "lookup_list": lk.group(1) if lk else None,
                "range": t in ("Date", "DateTime", "Timestamp"), "source": "dictionary",
                "why": "ok"}
    rt = _sdk_getter(jar, cur, last)
    if not rt:
        return {"ok": False, "why": f"no getter for {last!r} on {cur} in the SDK jar"}
    return {"ok": True, "terminal": f"{cur}.{last}", "type": rt, "entity": cur.rsplit(".", 1)[-1],
            "lookup": None, "lookup_list": None, "range": rt.endswith("Date"),
            "source": "sdk", "why": "ok (walked from the SDK jar - lookup list unknown)"}


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    dd = load_dd(os.path.expanduser(sys.argv[1]))
    root, paths = sys.argv[2], sys.argv[3:]
    fq = learn_fqcn(glob.glob(os.path.expanduser("~/Downloads/FORM-*.zip")),
                    glob.glob(os.path.expanduser("~/Downloads/ecourt-sdk-*.jar")))
    global JAR
    JAR = os.environ.get("JTI_SDK_JAR") or next(iter(sorted(glob.glob(
        os.path.expanduser("~/Downloads/ecourt-sdk-*.jar")))), None)
    bad = 0
    for p in paths:
        r = resolve(dd, fq, root, p, jar=JAR)
        if r["ok"]:
            extra = (f"  lookup {r['lookup_list']}" if r["lookup"] else "") + ("  range" if r["range"] else "")
            print(f"  ok      {p:<34} -> {r['terminal']}   [{r['type']}]{extra}")
        else:
            bad += 1
            print(f"  REFUSED {p:<34}    {r['why']}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
