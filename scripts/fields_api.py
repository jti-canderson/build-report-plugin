"""fields_api.py - the builder's field browser: what fields an entity really has.

    GET /api/fields?project=<project>&entity=<class>

Reads ONLY the project's own registered SDK jar (project.py sdk-register), through the same
javap reader build_plan.py resolves traversals with, so a field the page offers is one the
build will find. `entity` must be a class that exists in that jar - it is looked up in the
jar's own class list, never passed through from the browser - so nothing from the page
reaches a command line. Models are cached per jar for the life of the server: the first
look at an entity costs one javap run (~1 s), every later one is free.

The SDK cannot say whether a String is a pick-list (see the Data Dictionary for that); the
browser says "text" and lets the build decide.
"""
import os
import pathlib
import re
import threading

import build_plan as BP
import project as P

ROOTS = ("Case", "Party", "Person", "Receipt", "Charge", "Obligation", "Document", "Event")
HIDE = re.compile(r"^(serialVersionUID|metaClass|class|hibernateLazyInitializer|handler)$|[$]")
_MODELS, _LOCK = {}, threading.Lock()
_USED = {}
READ = re.compile(r"\?\.([A-Za-z_]\w*)")


def used_names(root):
    """How often each property name is read (`x?.name`) by the rules already in this
    workspace. A field a working report already reads is the best first suggestion there is;
    counted once per server, over at most 600 rules."""
    root = str(root)
    if root not in _USED:
        counts = {}
        for i, f in enumerate(pathlib.Path(root).rglob("*.groovy")):
            if i >= 600 or "jti-reports-plugin" in f.parts or ".jti-build" in f.parts:
                continue
            try:
                for n in set(READ.findall(f.read_text(errors="replace"))):
                    counts[n] = counts.get(n, 0) + 1
            except OSError:
                pass
        _USED[root] = counts
    return _USED[root]


def _jar(folder):
    folder = P._under_root(folder) or pathlib.Path(folder).resolve()
    sdk = P._meta(folder).get("sdk") if folder.is_dir() else None
    if not sdk:
        return None, None
    p = folder / sdk["stored"]
    return (str(p), sdk.get("filename") or p.name) if p.is_file() else (None, None)


def _model(jar):
    with _LOCK:
        if jar not in _MODELS:
            _MODELS[jar] = BP.Model(jar)
        return _MODELS[jar]


def _kind(model, typ):
    """value | entity | collection, and the class a drill-in lands on."""
    # A raw List / Set / Map says nothing about what it holds: it can be neither printed
    # nor followed, so it is shown but not offered.
    if re.match(r"^java\.util\.(List|Set|Collection|Map|SortedSet|Iterable)$", typ) or typ.endswith("[]"):
        return "opaque", None
    el = BP.element(typ)
    if el is None:
        return "value", None
    if el != typ:                                   # generic: List<X>, Set<X>
        return ("collection", el) if el in model.names else ("value", None)
    if BP.PRIMITIVE.match(typ) or typ not in model.names:
        return "value", None
    return "entity", typ


def _label(t):
    return {"java.lang.String": "text", "java.util.Date": "date", "java.sql.Timestamp": "date",
            "java.lang.Long": "number", "java.lang.Integer": "number", "long": "number",
            "int": "number", "java.math.BigDecimal": "decimal", "java.lang.Double": "decimal",
            "double": "decimal", "java.lang.Boolean": "yes/no", "boolean": "yes/no"}.get(t)


def browse(folder, entity):
    jar, sdk_name = _jar(folder)
    if not jar:
        return {"ok": False, "reason": "no-sdk",
                "message": "No field list (SDK) is on file for this project, so the fields "
                           "cannot be browsed. Describe the report in the brief instead - "
                           "Claude asks for the SDK when it builds."}
    model = _model(jar)
    fq, err = model.fqcn(entity or "Case")
    if not fq or fq not in model.names:
        return {"ok": False, "reason": "no-entity", "message": f"{entity!r}: {err or 'not in the SDK'}"}
    # the class and its supers
    chain, cls, seen = [], fq, 0
    while cls and cls != "java.lang.Object" and seen < 12:
        model.load({cls})
        info = model.cache.get(cls)
        if not info:
            break
        chain.append(info)
        cls, seen = info["super"], seen + 1
    out, done = [], set()
    for info in chain:
        for name, (how, typ) in info["members"].items():
            if name in done or HIDE.search(name):
                continue
            done.add(name)
            kind, target = _kind(model, typ)
            out.append({"name": name, "type": typ, "kind": kind,
                        "target": target, "targetShort": target.rsplit(".", 1)[-1] if target else None,
                        "label": _label(typ) or (target.rsplit(".", 1)[-1] if target else typ.rsplit(".", 1)[-1]),
                        "display": name.startswith("cf_")})
    used = used_names(P.ROOT)
    for f in out:
        f["used"] = used.get(f["name"], 0)
    out.sort(key=lambda f: ({"value": 0, "entity": 1, "collection": 2, "opaque": 3}[f["kind"]], f["name"].lower()))
    roots = [r for r in ROOTS if model.fqcn(r)[0]]
    return {"ok": True, "entity": fq.rsplit(".", 1)[-1], "fqcn": fq, "sdk": sdk_name,
            "roots": roots, "fields": out}
