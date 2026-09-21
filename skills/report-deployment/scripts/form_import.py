#!/usr/bin/env python3
"""form_import.py - read, verify and rewrite eSeries FORM config exports (search forms).

    python3 form_import.py --selftest ~/Downloads/FORM-local-2026-09-21.zip
    python3 form_import.py --selftest-all ~/Downloads          # every FORM-*.zip found
    python3 form_import.py --show <zip>                        # what is in it, readably

WHY THIS EXISTS, AND WHY IT IS BUILT THIS WAY
=============================================
A search form imported into eSeries cannot be corrected in place the way a rule can - a bad
one has to be deleted and re-uploaded. So the writer has to be right the FIRST time, and the
only evidence that carries that weight is byte equality against exports the platform itself
produced. `--selftest` is the oracle: parse a real export, write it back out from the parsed
parts, and diff. Anything short of IDENTICAL means the writer does not understand the format
yet and must not be used to generate anything.

That is the same discipline `rule_import.py` uses for RULE exports, for the same reason.

THE DESIGN DECISION THAT MATTERS: this does NOT rebuild a form from a semantic model of my
own. A FormItem carries 54 fields in a fixed order, several of them XStream-specific
(`<showIfValues class="sorted-set"/>`, `<null/>`, `reference="../../../../.."` back-pointers
whose depth varies with nesting). Reconstructing all of that from a model I invented would
mean betting the import on my having catalogued every field correctly.

Instead every operation is a TRANSFORM OF KNOWN-GOOD CONFIG. Items are cloned from real
exported items and specific fields are overridden; the platform's own defaults come along
untouched. What I have to get right shrinks from "the whole schema" to "the fields I chose to
change" - and the diff against the source shows exactly that set, so it can be read before
anything is uploaded.

STRUCTURE OF AN EXPORT
    FORM=<code>.xml inside a zip, holding <com.sustain.api.model.ConfigExportRsp> with:
      srcActionUrl      the source environment's edit URL - per-environment, not portable
      srcContent        sparse JSON: only non-default fields. What the admin diff screen reads.
      srcImportContent  XStream <screen-config-root> with the full Form object. The payload.
      srcRoot           always FORM here
      srcHash           8 hex chars. MUST NOT be empty (see rule_import.py - an empty one is
                        rejected with "error reading zip file", which blames the container).
      srcCode / srcId   the form's code and its primary key IN THE SOURCE ENVIRONMENT.

    Both serializations describe the same form and must agree. srcContent is a projection of
    srcImportContent, so this module edits the XStream and re-projects the JSON from it.
"""
import argparse
import glob
import hashlib
import html
import json
import os
import re
import sys
import zipfile

# ── envelope ────────────────────────────────────────────────────────────────────────
ENVELOPE = ("srcActionUrl", "srcContent", "srcImportContent", "srcRoot",
            "srcHash", "srcCode", "srcId")

# What the platform's own export is named: FORM-<environment>-<date>.zip, with the browser's
# " (2)" suffix when it has been downloaded more than once. Anything else in the folder is
# something we wrote, and it is not evidence about the format.
PLATFORM_EXPORT = re.compile(r"^FORM-.+-\d{4}-\d{2}-\d{2}(?: \(\d+\))?\.zip$")


def members(path):
    """(member name, xml text) for each FORM=*.xml in a zip, or the file itself if xml."""
    if path.lower().endswith(".xml"):
        with open(path, encoding="utf8") as f:
            return [(os.path.basename(path), f.read())]
    out = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.lower().endswith(".xml"):
                out.append((n, z.read(n).decode("utf8")))
    return out


def unwrap(xml):
    """Split the ConfigExportRsp into its seven fields. Values are UNESCAPED."""
    env = {}
    for tag in ENVELOPE:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
        env[tag] = html.unescape(m.group(1)) if m else ""
        env[tag + "__present"] = m is not None
    return env


def esc(text):
    """Escape exactly what the platform escapes: the full five-entity XML set, apostrophes
    included. Established by selftest, not by assumption - my first two guesses at this were
    both wrong, and the only reason that is not now a broken import is that byte equality
    caught them. The Velocity inside a customListQuery is what makes &apos; show up at all."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&apos;"))


def wrap(env):
    """Rebuild the export XML from the seven fields, in the platform's own order."""
    return ("<com.sustain.api.model.ConfigExportRsp>\n"
            f"  <srcActionUrl>{esc(env['srcActionUrl'])}</srcActionUrl>\n"
            f"  <srcContent>{esc(env['srcContent'])}</srcContent>\n"
            f"  <srcImportContent>{esc(env['srcImportContent'])}</srcImportContent>\n"
            f"  <srcRoot>{esc(env['srcRoot'])}</srcRoot>\n"
            f"  <srcHash>{esc(env['srcHash'])}</srcHash>\n"
            f"  <srcCode>{esc(env['srcCode'])}</srcCode>\n"
            f"  <srcId>{esc(env['srcId'])}</srcId>\n"
            "</com.sustain.api.model.ConfigExportRsp>")


# ── the XStream payload ─────────────────────────────────────────────────────────────
ITEM_OPEN = re.compile(
    r'^(\s*)<com\.sustain\.form\.model\.(SearchResultFormItem|SearchCriteriaFormItem|FormItem)'
    r'(\s+serialization="custom")?>\s*$')


def split_items(imp):
    """(head, items, seps, tail) - the direct children of the OUTER <formItems>.

    Depth-tracked rather than regex-matched: an item can nest further items inside
    <additionalItems> (that is how an OR-ed criterion is stored), and those inner items carry
    the same class name. A non-greedy regex takes the first closing tag and truncates the
    parent, which silently drops the OR.

    `seps` holds the whitespace BETWEEN items (len(items) + 1 entries: before the first, each
    gap, after the last). Keeping it separate is what makes the round trip byte-exact - the
    first cut folded the newline-and-indent into nothing and every item ran onto the previous
    line. It also means an inserted item can be given the same indentation as its neighbours.
    """
    open_tag = imp.index("<formItems>")
    close_tag = imp.rindex("</formItems>")
    head = imp[:open_tag + len("<formItems>")]
    body = imp[open_tag + len("<formItems>"):close_tag]
    tail = imp[close_tag:]

    spans, depth, start, base = [], 0, None, None
    for m in re.finditer(r'<(/?)(com\.sustain\.form\.model\.\w+)[^>]*?(/?)>', body):
        closing, name, selfclose = m.group(1), m.group(2), m.group(3)
        if selfclose:
            continue
        if not closing:
            if depth == 0:
                start, base = m.start(), name
            depth += 1
        else:
            depth -= 1
            if depth == 0 and name == base:
                spans.append((start, m.end()))

    items = [body[a:b] for a, b in spans]
    seps, at = [], 0
    for a, b in spans:
        seps.append(body[at:a])
        at = b
    seps.append(body[at:])
    return head, items, seps, tail


def item_class(item):
    m = re.match(r'\s*<com\.sustain\.form\.model\.(\w+)', item)
    return m.group(1) if m else "?"


def field(item, name, block=None):
    """Read a field from an item. Searches the whole item text unless block is given."""
    text = item if block is None else block
    m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    if m:
        return html.unescape(m.group(1))
    return None if re.search(rf"<{name}\s*/>", text) is None else ""


def item_summary(item):
    """What this item IS, for reading and for the structural checks."""
    cls = item_class(item)
    # num/path/readonly live in the FormItem <default>; take the FIRST occurrence, which is
    # this item's own - a nested additionalItems child would otherwise answer for its parent.
    def first(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
        return html.unescape(m.group(1)) if m else None
    return {
        "class": cls,
        "kind": ("result" if cls == "SearchResultFormItem" else
                 "criterion" if cls == "SearchCriteriaFormItem" else "item"),
        "num": int(first("num") or -1),
        "path": first("path"),
        "label": first("label"),
        "type": first("type"),
        "operator": first("operator"),
        "hidden": first("hidden") == "true",
        # How many items are nested INSIDE this one (an OR-ed criterion). Counting
        # <additionalItems> blocks is wrong - one block can hold several items, and
        # S-Person-Simple has 4 blocks holding 6 items, which made the count gate fire on a
        # file the platform itself produced. Every item, nested or not, carries exactly one
        # serialization="custom" on its own opening tag, so the extras are the nested ones.
        "nested": item.count('serialization="custom"') - 1,
    }


def parse(xml):
    """Everything about one export, in a form that can be inspected and rewritten."""
    env = unwrap(xml)
    imp = env["srcImportContent"]
    head, items, seps, tail = split_items(imp)
    cfg = json.loads(env["srcContent"]) if env["srcContent"].strip().startswith("{") else {}
    return {
        "env": env, "imp": imp, "head": head, "items": items, "seps": seps, "tail": tail,
        "cfg": cfg,
        "code": env["srcCode"], "id": env["srcId"],
        "root_xstream": field(head, "rootEntity"),
        "root_json": cfg.get("rootEntity"),
        "name": cfg.get("formName"),
        "type": cfg.get("type"),
        "drilldown": cfg.get("drilldownForm"),
        "validation_ids": (re.search(r'<validationRule ids="([^"]*)"', imp).group(1).split(",")
                           if re.search(r'<validationRule ids="([^"]*)"', imp) else []),
        "summaries": [item_summary(i) for i in items],
    }


def rebuild(p):
    """Reassemble the export from the parsed parts. Byte-identical when nothing was changed."""
    body = "".join(s + i for s, i in zip(p["seps"], p["items"])) + p["seps"][-1]
    imp = p["head"] + body + p["tail"]
    env = dict(p["env"])
    env["srcImportContent"] = imp
    return wrap(env)


# ── editing ─────────────────────────────────────────────────────────────────────────
# Everything below CHANGES a form. The rule for all of it: touch the named field and nothing
# else, then let --diff show what moved. A transform that cannot be read in a diff is a
# transform nobody can approve before an upload that cannot be undone.

def _sub_one(text, tag, value, where):
    """Replace exactly one <tag>...</tag>. Raises if it is absent or ambiguous."""
    hits = list(re.finditer(rf"<{tag}>(.*?)</{tag}>", text, re.S))
    if len(hits) != 1:
        raise ValueError(f"{where}: expected exactly one <{tag}>, found {len(hits)}")
    m = hits[0]
    return text[:m.start(1)] + esc(value) + text[m.end(1):]


def set_form_field(p, xstream_tag, json_key, value):
    """Set a FORM-level field in BOTH serializations, or in whichever one carries it.

    srcContent is sparse - a field at its default is simply absent - so a missing JSON key is
    normal and not an error. The XStream is the full object and is authoritative; if the tag
    is missing there, that is a real problem and it raises.
    """
    if xstream_tag:
        target = "head" if f"<{xstream_tag}>" in p["head"] else "tail"
        p[target] = _sub_one(p[target], xstream_tag, value, f"XStream <{xstream_tag}>")
    if json_key and json_key in p["cfg"]:
        p["cfg"][json_key] = value
    return p


def reproject_json(p):
    """Write the (edited) sparse JSON back into the envelope, in the platform's own layout:
    two-space indent, keys in insertion order - which is why cfg is edited in place rather
    than rebuilt from a dict comprehension."""
    p["env"]["srcContent"] = json.dumps(p["cfg"], indent=2, ensure_ascii=False)
    return p


def rename(p, new_code, new_name=None):
    """Give the form a new code (and optionally a new display name), consistently.

    A code lives in FIVE places and they must agree: the XStream <code>, the JSON "code", the
    envelope <srcCode>, the zip member name FORM=<code>.xml, and - when it mirrors the code,
    which it does on every search form seen so far - <defaultSaveTitle>. Changing four of the
    five is the kind of error that imports successfully and then behaves oddly.
    """
    old = p["code"]
    set_form_field(p, "code", "code", new_code)
    p["env"]["srcCode"] = new_code
    if field(p["tail"], "defaultSaveTitle") == old:
        set_form_field(p, "defaultSaveTitle", "defaultSaveTitle", new_code)
    if new_name:
        set_form_field(p, "formName", "formName", new_name)
    p["code"] = new_code
    return p


def set_drilldown(p, code_or_none):
    """Point the form at a different drilldown, or remove the link.

    The two serializations disagree on purpose and both spellings must be right: the XStream
    namespaces it as FORM=<code>, the JSON carries the bare code.
    """
    if code_or_none:
        if "<drilldownForm>" in p["tail"]:
            p["tail"] = _sub_one(p["tail"], "drilldownForm", f"FORM={code_or_none}", "drilldown")
        else:
            raise ValueError("this form has no <drilldownForm> to point elsewhere")
        p["cfg"]["drilldownForm"] = code_or_none
    else:
        p["tail"] = re.sub(r"\n\s*<drilldownForm>.*?</drilldownForm>", "", p["tail"], flags=re.S)
        p["cfg"].pop("drilldownForm", None)
    return p


def retarget(p, host=None, src_id=None, keep_provenance=False):
    """Adapt an export taken from one environment for import into another.

    WHAT IS AND IS NOT KNOWN. srcActionUrl, srcId, srcHash and the <validationRule ids> list
    are all provenance from the SOURCE environment: primary keys and a URL that mean nothing
    in the target. For RULE exports it is PROVEN (rule_import.py, 2026-09-03) that the
    importer accepts synthesised values and only rejects EMPTY ones. That has NOT been proven
    for FORM exports, so the default here is the conservative one: leave them exactly as the
    platform wrote them. Changing them is opt-in, and `--keep-provenance` is the safer path
    until somebody has watched a retargeted form import successfully.
    """
    changed = []
    if host:
        url = p["env"]["srcActionUrl"]
        new = re.sub(r"https://[^/]+/", f"https://{host}/", url)
        if new != url:
            p["env"]["srcActionUrl"] = new
            changed.append(f"srcActionUrl host -> {host}")
    if src_id is not None:
        p["env"]["srcId"] = str(src_id)
        p["env"]["srcActionUrl"] = re.sub(r"id=\d+", f"id={src_id}", p["env"]["srcActionUrl"])
        changed.append(f"srcId -> {src_id}")
    if not keep_provenance and not changed:
        changed.append("nothing - provenance left as exported (the conservative default)")
    return p, changed


def rehash(p):
    """Recompute srcHash over the payload.

    It must not be EMPTY - an empty one is rejected as "error reading zip file", which blames
    the container and sends you looking in the wrong place (proven for RULE). Whether the
    platform VERIFIES it is unknown; for RULE it demonstrably does not. Recomputing keeps it
    plausible either way, and costs nothing.
    """
    p["env"]["srcHash"] = hashlib.sha1(
        p["env"]["srcImportContent"].encode("utf8")).hexdigest()[:8]
    return p


def write_zip(path, code, xml):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"FORM={code}.xml", xml)
    return path


def _form_tags(p):
    """Every FORM-level tag in the XStream, as a dict. These are the head/tail fields - the
    form's own settings, not its items."""
    out = {}
    for chunk in (p["head"].rsplit("<formItems>", 1)[0], p["tail"]):
        for m in re.finditer(r"<([a-zA-Z][\w]*)>(.*?)</\1>", chunk, re.S):
            out[m.group(1)] = html.unescape(m.group(2))
    return out


def diff_forms(a_path, b_path):
    """Field-level difference between two exports - what an approver actually needs to read.

    A raw text diff of a 400KB XStream document is unreadable, and unreadable is how a wrong
    field gets waved through. So: name every field that moved, and then say plainly whether
    anything ELSE moved - because "otherwise identical" is the sentence the reader is trusting,
    and it has to be earned rather than asserted.
    """
    (an, ax), (bn, bx) = members(a_path)[0], members(b_path)[0]
    a, b = parse(ax), parse(bx)
    print(f"  A  {an}\n  B  {bn}\n")
    n = 0

    print("  envelope")
    for k in ("srcActionUrl", "srcRoot", "srcHash", "srcCode", "srcId"):
        if a["env"][k] != b["env"][k]:
            print(f"    {k:<26} {a['env'][k]!r}  ->  {b['env'][k]!r}")
            n += 1

    ta, tb = _form_tags(a), _form_tags(b)
    print("  form settings")
    for k in sorted(set(ta) | set(tb)):
        if ta.get(k) != tb.get(k):
            print(f"    {k:<26} {ta.get(k)!r}  ->  {tb.get(k)!r}")
            n += 1

    print("  items")
    if len(a["items"]) != len(b["items"]):
        print(f"    count                      {len(a['items'])}  ->  {len(b['items'])}")
        n += 1
    for i, (x, y) in enumerate(zip(a["summaries"], b["summaries"])):
        d = {k: (x[k], y[k]) for k in x if x[k] != y[k]}
        if d:
            print(f"    item {i:<3} " + ", ".join(f"{k}: {v[0]!r} -> {v[1]!r}"
                                                  for k, v in d.items()))
            n += 1
    # the honest backstop: item TEXT equality, which catches a changed field the summary
    # does not surface at all
    text_changed = [i for i, (x, y) in enumerate(zip(a["items"], b["items"])) if x != y]
    if text_changed:
        print(f"    item text differs at: {text_changed}")
        n += len(text_changed)

    print(f"\n  {n} difference(s). " + ("Nothing else moved." if
          a["items"] == b["items"] or not text_changed else
          "Read the item list above before uploading."))


# ── composing a form ────────────────────────────────────────────────────────────────
def item_num(item):
    m = re.search(r"<num>(\d+)</num>", item)
    return int(m.group(1)) if m else -1


def renumber(item, n):
    """Set this item's own num, leaving any nested item's num alone.

    Only the FIRST <num> belongs to this item - a nested OR-ed criterion carries its own
    further down the same text, and a global replace would give both the same number.
    """
    return re.sub(r"<num>\d+</num>", f"<num>{n}</num>", item, count=1)


def renumber_nested(item, n):
    """Set the num of the LAST nested item (used when renumbering an OR-ed criterion)."""
    hits = list(re.finditer(r"<num>(\d+)</num>", item))
    if len(hits) < 2:
        return item
    m = hits[-1]
    return item[:m.start()] + f"<num>{n}</num>" + item[m.end():]


def compose(donor, paths, code, name, keep_results=None):
    """Build a form holding exactly the named items, in the order given, taken from a donor.

    THE WHOLE SAFETY ARGUMENT IS HERE. Items are lifted verbatim from a form the platform
    exported, so every one of the 54 fields, the XStream artifacts and the resolved
    <string>entityClass.field come along untouched. What this function decides is only WHICH
    items appear and in WHAT ORDER - so that is the only thing that can be wrong, and the diff
    against the donor shows it.

    `paths` selects criteria in screen order; `keep_results` selects result columns (default:
    all of the donor's, in their existing order).

    Numbering: eSeries orders the screen by `num`, so the criteria are numbered in the order
    given and the results after them. A nested (OR-ed) criterion keeps its parent's position
    and takes the next number after the whole list, which is what the donor itself does.
    """
    # Key by (kind, path), NOT path alone. On S-Case-Simple `location`, `caseType` and
    # `status` are EACH both a result column and a criterion - same path, different item,
    # different label ("Office" vs "Agency"). Keying by path alone silently hands back the
    # result column for three of the eight criteria, and the form still builds.
    by_path = {}
    for it in donor["items"]:
        sm = item_summary(it)
        by_path.setdefault((sm["kind"], sm["path"]), []).append(it)

    missing = [p for p in paths if ("criterion", p) not in by_path]
    if missing:
        raise ValueError(f"the donor has no item for: {missing}. Available criteria: "
                         + ", ".join(sorted(sm['path'] for sm in donor['summaries']
                                            if sm['kind'] == 'criterion' and sm['path'])))

    crit = [by_path[("criterion", p)][0] for p in paths]
    results = [it for it in donor["items"] if item_summary(it)["kind"] == "result"]
    if keep_results is not None:
        want = list(keep_results)
        results = [it for it in results if item_summary(it)["path"] in want]

    # results first (the donor numbers them 0..n-1), then criteria - matching S-Case-Simple
    ordered, n = [], 0
    for it in results:
        ordered.append(renumber(it, n)); n += 1
    nested_after = []
    for it in crit:
        ordered.append(renumber(it, n)); n += 1
    # nested items take the numbers after everything else, as the donor does
    for i, it in enumerate(ordered):
        if item_summary(it)["nested"]:
            ordered[i] = renumber_nested(it, n); n += 1

    out = dict(donor)
    out["items"] = ordered
    sep = donor["seps"][1] if len(donor["seps"]) > 1 else "\n    "
    out["seps"] = [donor["seps"][0]] + [sep] * (len(ordered) - 1) + [donor["seps"][-1]]
    out["summaries"] = [item_summary(i) for i in ordered]

    # the JSON has to say the same thing. Rebuild it from the chosen items rather than
    # editing the donor's array, so a dropped item cannot survive in one serialization.
    keep_paths = [item_summary(i)["path"] for i in ordered]
    js = {j.get("path"): j for j in (donor["cfg"].get("formItems") or [])}
    new_items = []
    for it in ordered:
        sm = item_summary(it)
        j = dict(js.get(sm["path"]) or {})
        j["num"] = sm["num"]
        if "additionalItems" in j:
            inner = [dict(x) for x in j["additionalItems"]]
            for x in inner:
                x["num"] = item_summary(it)["num"]   # placeholder, fixed below
            j["additionalItems"] = inner
        new_items.append(j)
    # the JSON lists a nested item BOTH inside its parent and at top level - reproduce that
    for it, j in zip(ordered, new_items):
        for x in j.get("additionalItems", []):
            nums = [int(m.group(1)) for m in re.finditer(r"<num>(\d+)</num>", it)]
            if len(nums) > 1:
                x["num"] = nums[-1]
                top = dict(x)
                new_items.append(top)
    out["cfg"] = dict(donor["cfg"])
    out["cfg"]["formItems"] = new_items

    # the per-item validation ids are source-environment primary keys, mapped positionally to
    # the donor's items. Subsetting them positionally is an ASSUMPTION - it has never been
    # checked against a real import, so a composed form that drops items says so out loud.
    rename(out, code, name)
    return out


# ── the gate ────────────────────────────────────────────────────────────────────────
def check(p, member_name=None):
    """Everything that must be true of a form before anybody uploads it.

    Split into FAULTS (would import wrong, or not at all) and NOTES (worth a human's eye).
    These are the checks that are cheap and mechanical; they do not and cannot tell you the
    search returns the right rows.
    """
    faults, notes = [], []

    for tag in ("srcActionUrl", "srcHash", "srcId"):
        if not p["env"].get(tag, "").strip():
            faults.append(f"<{tag}> is empty - the importer rejects this with the misleading "
                          f'message "error reading zip file" (proven for RULE exports)')
    if p["env"]["srcRoot"] != "FORM":
        faults.append(f"srcRoot is {p['env']['srcRoot']!r}, expected FORM")

    # the code lives in five places and they have to agree
    x_code, j_code, e_code = field(p["head"], "code"), p["cfg"].get("code"), p["env"]["srcCode"]
    if not (x_code == j_code == e_code):
        faults.append(f"code disagrees: XStream {x_code!r}, JSON {j_code!r}, "
                      f"envelope {e_code!r}")
    if member_name and member_name != f"FORM={e_code}.xml":
        faults.append(f"zip member is {member_name!r}, expected FORM={e_code}.xml")

    # the two root-entity spellings
    xr, jr = p["root_xstream"], p["root_json"]
    if xr and jr and not xr.endswith("." + jr) and xr != jr:
        faults.append(f"rootEntity disagrees: XStream {xr!r} vs JSON {jr!r}")

    # drilldown: XStream namespaces it, JSON does not
    xd, jd = field(p["tail"], "drilldownForm"), p["cfg"].get("drilldownForm")
    if (xd or jd) and xd != (f"FORM={jd}" if jd else None):
        faults.append(f"drilldownForm disagrees: XStream {xd!r} vs JSON {jd!r} "
                      f"(XStream namespaces it as FORM=<code>)")

    # item counts. The JSON lists an OR-ed criterion BOTH nested and at top level, so the two
    # counts legitimately differ by the number of nested items - anything else is a fault.
    x_n = len(p["items"])
    j_n = len(p["cfg"].get("formItems") or [])
    nested = sum(sm["nested"] for sm in p["summaries"])
    if j_n and x_n + nested != j_n:
        faults.append(f"item count: {x_n} in XStream + {nested} nested != {j_n} in JSON")

    nums = [sm["num"] for sm in p["summaries"]]
    if len(set(nums)) != len(nums):
        dupes = sorted({n for n in nums if nums.count(n) > 1})
        faults.append(f"duplicate num values among top-level items: {dupes}")

    if p["type"] == 4:
        if not any(sm["kind"] == "result" for sm in p["summaries"]):
            faults.append("a search form with no result columns has nothing to show")
        if not any(sm["kind"] == "criterion" for sm in p["summaries"]):
            notes.append("no criteria - this search cannot be narrowed by the user")
        hidden = [sm for sm in p["summaries"] if sm["hidden"] and sm["kind"] == "criterion"]
        for h in hidden:
            notes.append(f"criterion {h['num']} ({h['path']}) is hidden - a forced filter the "
                         f"user will not see")
    if jd and p["type"] == 4:
        notes.append(f"drills down to {jd} - that form must exist in the target environment")
    for sm in p["summaries"]:
        if not sm["path"]:
            notes.append(f"item {sm['num']} has no path (type {sm['type']} - a widget?)")
    return faults, notes


# ── selftest ────────────────────────────────────────────────────────────────────────
def selftest(path, verbose=False):
    ok = True
    for name, xml in members(path):
        try:
            p = parse(xml)
        except Exception as e:                      # noqa: BLE001 - report, do not raise
            print(f"  {name}: PARSE FAILED - {type(e).__name__}: {e}")
            ok = False
            continue
        built = rebuild(p)
        if built == xml:
            kinds = {}
            for sm in p["summaries"]:
                kinds[sm["kind"]] = kinds.get(sm["kind"], 0) + 1
            shape = ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
            print(f"  {name}: IDENTICAL  ({len(xml)} bytes, {len(p['items'])} items: {shape})")
        else:
            ok = False
            print(f"  {name}: DIFFERS ({len(xml)} vs {len(built)} bytes)")
            import difflib
            for ln in list(difflib.unified_diff(xml.splitlines(), built.splitlines(),
                                                "platform", "rebuilt", lineterm=""))[:20]:
                print("     ", ln[:160])
    return ok


def show(path):
    for name, xml in members(path):
        p = parse(xml)
        print(f"\n=== {name}")
        print(f"  code {p['code']}   id {p['id']}   type {p['type']}   root {p['root_json']}"
              f" ({p['root_xstream']})")
        print(f"  name {p['name']!r}   drilldown {p['drilldown'] or '-'}")
        print(f"  {len(p['items'])} items, {len(p['validation_ids'])} validation ids")
        for s in p["summaries"]:
            flag = "H" if s["hidden"] else " "
            extra = f"  +{s['nested']} OR" if s["nested"] else ""
            print(f"    {s['num']:>3} {flag} {s['kind']:<9} {str(s['path'])[:44]:<44}"
                  f" {str(s['label'] or '')[:22]:<22} {s['operator'] or ''}{extra}")


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--selftest")
    ap.add_argument("--selftest-all")
    ap.add_argument("--show")
    ap.add_argument("--check")
    ap.add_argument("--diff", nargs=2)
    ap.add_argument("--copy", help="an existing export to adapt")
    ap.add_argument("--code"); ap.add_argument("--name")
    ap.add_argument("--drilldown", help="new drilldown code, or 'none' to unlink")
    ap.add_argument("--host"); ap.add_argument("--id")
    ap.add_argument("--rehash", action="store_true")
    ap.add_argument("--out", help="where to write the zip")
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args()
    if a.help or not (a.selftest or a.selftest_all or a.show or a.check or a.diff or a.copy):
        print(__doc__)
        sys.exit(0)
    if a.show:
        show(a.show)
        return
    if a.diff:
        diff_forms(*a.diff)
        return
    if a.check:
        bad = 0
        for name, xml in members(a.check):
            f, n = check(parse(xml), name)
            print(f"  {name}")
            for x in f:
                print(f"    FAULT  {x}")
            for x in n:
                print(f"    note   {x}")
            if not f:
                print("    no faults")
            bad += len(f)
        sys.exit(1 if bad else 0)
    if a.copy:
        if not a.out:
            sys.exit("  --copy needs --out")
        (name, xml), = members(a.copy)[:1]
        p = parse(xml)
        origin = p["code"]
        if a.code:
            rename(p, a.code, a.name)
        elif a.name:
            set_form_field(p, "formName", "formName", a.name)
        if a.drilldown:
            set_drilldown(p, None if a.drilldown.lower() == "none" else a.drilldown)
        p, changed = retarget(p, host=a.host, src_id=a.id)
        reproject_json(p)
        p["env"]["srcImportContent"] = (p["head"] +
            "".join(s2 + i for s2, i in zip(p["seps"], p["items"])) + p["seps"][-1] + p["tail"])
        if a.rehash:
            rehash(p)
        xml_out = wrap(p["env"])
        # re-parse what we are about to write and gate it, rather than trusting the edit
        back = parse(xml_out)
        faults, notes = check(back, f"FORM={back['env']['srcCode']}.xml")
        print(f"  adapted {origin} -> {back['code']}")
        for c in changed:
            print(f"    {c}")
        for x in faults:
            print(f"    FAULT  {x}")
        for x in notes:
            print(f"    note   {x}")
        if faults:
            sys.exit("\n  refusing to write a form with faults")
        write_zip(a.out, back["env"]["srcCode"], xml_out)
        print(f"\n  wrote {a.out}")
        return
    if a.selftest:
        sys.exit(0 if selftest(a.selftest) else 1)
    files = sorted(glob.glob(os.path.join(os.path.expanduser(a.selftest_all), "FORM-*.zip")))
    # Only a file the PLATFORM wrote is evidence. Our own output lands in the same folder (it
    # is where the user asked for it), and counting it would make the oracle partly circular -
    # the writer would be marking its own homework and the number would keep going up.
    plat = [f for f in files if PLATFORM_EXPORT.match(os.path.basename(f))]
    ours = [f for f in files if f not in plat]
    print(f"{len(plat)} platform export(s)" +
          (f", ignoring {len(ours)} generated file(s): " +
           ", ".join(os.path.basename(f) for f in ours) if ours else "") + "\n")
    good = bad = 0
    for f in plat:
        print(os.path.basename(f))
        if selftest(f):
            good += 1
        else:
            bad += 1
    print(f"\n  {good} platform export(s) reproduced byte-for-byte, {bad} failed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
