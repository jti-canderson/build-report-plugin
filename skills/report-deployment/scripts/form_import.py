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
            # A self-closing FormItem at the TOP level of <formItems> is a real list entry: an
            # XStream back-reference that puts an OR-ed (nested) criterion into the list a second
            # time without serialising it twice. It is NOT whitespace. Until 2026-09-22 this
            # skipped it, so it rode along invisibly inside the "separator" - and build_search
            # copied it into a form where its target did not exist: a dangling reference.
            if depth == 0 and 'reference="' in m.group(0):
                spans.append((m.start(), m.end()))
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


def is_ref(item):
    """A reference list-entry: <com.sustain.form.model.X reference="..."/>, no body."""
    return item.rstrip().endswith("/>") and 'reference="' in item.split(">", 1)[0]


def item_summary(item):
    """What this item IS, for reading and for the structural checks."""
    cls = item_class(item)
    if is_ref(item):
        ref = re.search(r'reference="([^"]*)"', item).group(1)
        return {"class": cls, "kind": "ref", "num": -1, "path": None, "label": None,
                "type": None, "operator": None, "hidden": False, "nested": 0, "ref": ref}
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

    # the JSON half. Until 2026-09-22 this function never looked at srcContent, so "Nothing
    # else moved" was a statement about the XStream only - and S-Case-Quick shipped with a JSON
    # half that described different result columns from its XStream half.
    print("  srcContent (JSON)")
    ja, jb = a["cfg"], b["cfg"]
    for k in sorted((set(ja) | set(jb)) - {"formItems"}):
        if ja.get(k) != jb.get(k):
            print(f"    {k:<26} {ja.get(k)!r}  ->  {jb.get(k)!r}")
            n += 1
    ia, ib = ja.get("formItems") or [], jb.get("formItems") or []
    json_items_changed = [i for i, (x, y) in enumerate(zip(ia, ib)) if x != y]
    if len(ia) != len(ib):
        print(f"    formItems count            {len(ia)}  ->  {len(ib)}")
        n += 1
    if json_items_changed:
        print(f"    formItems entries differ at: {json_items_changed}")
        n += len(json_items_changed)

    moved = text_changed or json_items_changed or len(ia) != len(ib)
    print(f"\n  {n} difference(s). " + ("Nothing else moved - in either half." if not moved
          else "Read the item lists above before uploading."))


# ── synthesising items FROM SCRATCH ───────────────────────────────────────────────────
# Proven by byte-equality against real clean (no-configSourceId) platform items, 2026-09-22:
# 11/11 clean simple criteria, and result columns for both clean shapes (link on/off). These
# emit the MINIMAL shape a freshly-created item has - no configSourceId (a source-env pk a
# new item never had), and only the fields that shape carries. See references/search-forms.md.

def synth_criterion(num, path, terminal, *, lookup=False, operator=None, allow_range=False):
    """A search CRITERION item, from a path + its resolved terminal entityClass.field."""
    d, a = [], None
    out = []
    a = lambda t: d.append(" " * 10 + t)
    a("<grid>false</grid>"); a("<hidden>false</hidden>"); a("<link>true</link>")
    a("<noHoliday>false</noHoliday>"); a("<noWeekend>false</noWeekend>")
    a(f"<num>{num}</num>"); a("<readonly>false</readonly>"); a("<required>false</required>")
    a("<type>0</type>"); a('<associatedForm reference="../../../../.."/>')
    a("<carryOver>false</carryOver>"); a("<conditionalFormats/>"); a("<conditions/>")
    a("<existingEntityConditions/>"); a("<filterConditions/>")
    if lookup: a("<lookupItemFormat>LABEL</lookupItemFormat>")
    a("<multiSelectLookup>true</multiSelectLookup>")
    a("<newColumn>false</newColumn>"); a("<newRow>false</newRow>")
    if operator: a(f"<operator>{esc(operator)}</operator>")
    a("<panelAutoCompleteMinChars>1</panelAutoCompleteMinChars>")
    a("<parameters/>"); a(f"<path>{esc(path)}</path>")
    a('<showIfValues class="sorted-set"/>'); a('<showIfValues2 class="sorted-set"/>')
    a("<userSelectedList/>"); a("<widgetInMassType>NEVER_SHOW</widgetInMassType>")
    a("<xrefConditions/>")
    crit = ["          <additionalItems/>"]
    if allow_range: crit.append("          <allowRange>true</allowRange>")
    crit.append("          <split>false</split>")
    return "\n".join(
        ['<com.sustain.form.model.SearchCriteriaFormItem serialization="custom">',
         "      <com.sustain.DomainObject>", "        <default/>",
         "      </com.sustain.DomainObject>", "      <com.sustain.form.model.FormItem>",
         "        <default>"] + d + ["        </default>",
         f"        <string>{esc(terminal)}</string>", "        <null/>",
         "      </com.sustain.form.model.FormItem>",
         "      <com.sustain.form.model.SearchCriteriaFormItem>", "        <default>"] + crit +
        ["        </default>", "      </com.sustain.form.model.SearchCriteriaFormItem>",
         "    </com.sustain.form.model.SearchCriteriaFormItem>"])


# The platform's canonical FormItem field order - one total order explains all 1,051 <default>
# blocks in the corpus with zero cycles (measured 2026-09-21).
CANON_FIELDS = ['grid', 'hidden', 'link', 'noHoliday', 'noWeekend', 'num', 'readonly', 'required', 'type', 'addPanelCopy', 'addable', 'associatedForm', 'autoFillNullValue', 'carryOver', 'carryOverWhenRepeated', 'clearable', 'color', 'columnHeaders', 'columnStyles', 'condValue', 'conditionalFormats', 'conditions', 'configSourceId', 'customFormat', 'customListQuery', 'customListType', 'dateFormat', 'defaultCollapsed', 'defaultValue', 'displayInactive', 'dropdown', 'emptyPanelMessage', 'escapeHtml', 'exactMatchToCode', 'existingEntityConditions', 'existingSelectAll', 'expandIfCondition', 'fillPanelOnSelect', 'filterConditions', 'filterListByUser', 'filterable', 'footerText', 'forceCreateObject', 'forceDefaultValue', 'freeFormLookup', 'inPlaceEditable', 'includeNulls', 'innerJoin', 'label', 'labelIsTemplate', 'linkForm', 'lookupDefaultValues', 'lookupItemFormat', 'lookupSearchType', 'monthsToShow', 'multiSelectLookup', 'nested', 'newColumn', 'newRow', 'noLabel', 'numberFormat', 'numberMask', 'onlyAutoFillEmptyField', 'openInNewTab', 'operator', 'pageSize', 'panelAutoCompleteMinChars', 'panelAutoCompleteWithAllData', 'parameters', 'path', 'preventPanelLookups', 'preventParentPanelLookups', 'previewSummary', 'promptForMultiple', 'readonlyIfEmpty', 'readonlyIfNotEmpty', 'removeable', 'repeatPanelsOnPanelLookup', 'repeatable', 'requiredTime', 'rootPanel', 'runLookup', 'showIfNullValueWhenHidden', 'showIfValues', 'showIfValues2', 'sort', 'sortable', 'staticFieldText', 'style', 'styleClass', 'supervisorAuthority', 'title', 'treeTable', 'useCommaDisplayMask', 'userInterface', 'userSelectedList', 'widgetInMassType', 'xrefConditions']

# The FULL shape a criterion takes once it has a custom label: in every export a labelled
# criterion is written out in full (54-56 fields), never in the minimal shape - setting a label
# apparently makes the admin write everything. The constant part below was EXTRACTED from the
# 6 clean labelled type-0 criteria in the corpus (identical on all of them),
# not typed by hand; the semantic fields are filled in by synth_criterion_labelled.
RICH_CRITERION_BASE = {'grid': '          <grid>false</grid>', 'hidden': '          <hidden>false</hidden>', 'link': '          <link>true</link>', 'noHoliday': '          <noHoliday>false</noHoliday>', 'noWeekend': '          <noWeekend>false</noWeekend>', 'readonly': '          <readonly>false</readonly>', 'required': '          <required>false</required>', 'associatedForm': '          <associatedForm reference="../../../../.."/>', 'autoFillNullValue': '          <autoFillNullValue>false</autoFillNullValue>', 'carryOver': '          <carryOver>false</carryOver>', 'carryOverWhenRepeated': '          <carryOverWhenRepeated>false</carryOverWhenRepeated>', 'conditionalFormats': '          <conditionalFormats/>', 'conditions': '          <conditions/>', 'displayInactive': '          <displayInactive>false</displayInactive>', 'dropdown': '          <dropdown>false</dropdown>', 'exactMatchToCode': '          <exactMatchToCode>false</exactMatchToCode>', 'existingEntityConditions': '          <existingEntityConditions/>', 'existingSelectAll': '          <existingSelectAll>false</existingSelectAll>', 'fillPanelOnSelect': '          <fillPanelOnSelect>false</fillPanelOnSelect>', 'filterConditions': '          <filterConditions/>', 'filterListByUser': '          <filterListByUser>false</filterListByUser>', 'forceDefaultValue': '          <forceDefaultValue>false</forceDefaultValue>', 'freeFormLookup': '          <freeFormLookup>false</freeFormLookup>', 'inPlaceEditable': '          <inPlaceEditable>false</inPlaceEditable>', 'includeNulls': '          <includeNulls>false</includeNulls>', 'innerJoin': '          <innerJoin>false</innerJoin>', 'labelIsTemplate': '          <labelIsTemplate>false</labelIsTemplate>', 'lookupDefaultValues': '          <lookupDefaultValues></lookupDefaultValues>', 'newColumn': '          <newColumn>false</newColumn>', 'newRow': '          <newRow>false</newRow>', 'noLabel': '          <noLabel>false</noLabel>', 'onlyAutoFillEmptyField': '          <onlyAutoFillEmptyField>false</onlyAutoFillEmptyField>', 'openInNewTab': '          <openInNewTab>false</openInNewTab>', 'parameters': '          <parameters/>', 'preventPanelLookups': '          <preventPanelLookups>false</preventPanelLookups>', 'readonlyIfEmpty': '          <readonlyIfEmpty>false</readonlyIfEmpty>', 'readonlyIfNotEmpty': '          <readonlyIfNotEmpty>false</readonlyIfNotEmpty>', 'repeatPanelsOnPanelLookup': '          <repeatPanelsOnPanelLookup>false</repeatPanelsOnPanelLookup>', 'requiredTime': '          <requiredTime>false</requiredTime>', 'runLookup': '          <runLookup>false</runLookup>', 'showIfNullValueWhenHidden': '          <showIfNullValueWhenHidden>false</showIfNullValueWhenHidden>', 'showIfValues': '          <showIfValues class="sorted-set"/>', 'showIfValues2': '          <showIfValues2 class="sorted-set"/>', 'useCommaDisplayMask': '          <useCommaDisplayMask>true</useCommaDisplayMask>', 'userSelectedList': '          <userSelectedList/>', 'widgetInMassType': '          <widgetInMassType>NEVER_SHOW</widgetInMassType>', 'xrefConditions': '          <xrefConditions/>'}
RICH_CRITERION_BLOCK = '<com.sustain.form.model.SearchCriteriaFormItem>\n        <default>\n          <additionalItems/>\n          <allowRange>false</allowRange>\n          <extraCriteria>false</extraCriteria>\n          <searchLookupItemLabel>false</searchLookupItemLabel>\n          <split>false</split>\n          <subQueryIdentifier></subQueryIdentifier>\n        </default>\n      </com.sustain.form.model.SearchCriteriaFormItem>'


def synth_criterion_labelled(num, path, terminal, label, *, operator=None, lookup=False,
                             multi=False, default_value=None, allow_range=False,
                             relation=False, memo=None, pac=False):
    """A labelled search criterion in the platform's full shape.

    lookup=True adds the pair every labelled lookup criterion carries: lookupItemFormat LABEL
    and lookupSearchType CONTAINS. Inline HQL pickers (customListType QUERY) are NOT offered:
    they carry live Velocity and have not been reproduced.
    """
    sem = {
        "num": f"          <num>{num}</num>",
        "type": "          <type>0</type>",
        "label": f"          <label>{esc(label)}</label>",
        "path": f"          <path>{esc(path)}</path>",
        "multiSelectLookup": f"          <multiSelectLookup>{'true' if multi else 'false'}</multiSelectLookup>",
        "previewSummary": "          <previewSummary>false</previewSummary>",
    }
    if operator:
        sem["operator"] = f"          <operator>{esc(operator)}</operator>"
    if lookup:
        sem["lookupItemFormat"] = "          <lookupItemFormat>LABEL</lookupItemFormat>"
        sem["lookupSearchType"] = "          <lookupSearchType>CONTAINS</lookupSearchType>"
    if default_value is not None:
        sem["defaultValue"] = f"          <defaultValue>{esc(str(default_value))}</defaultValue>"
    # a criterion whose path ends at an ENTITY (a person picker, say) rather than a value
    # carries forceCreateObject=false - derivable from the dictionary's type for the terminal
    if relation:
        sem["forceCreateObject"] = "          <forceCreateObject>false</forceCreateObject>"
    if pac:
        sem["panelAutoCompleteWithAllData"] = ("          <panelAutoCompleteWithAllData>false"
                                               "</panelAutoCompleteWithAllData>")
    lines = [sem.get(t) or RICH_CRITERION_BASE.get(t) for t in CANON_FIELDS]
    lines = [l for l in lines if l]
    blk = RICH_CRITERION_BLOCK
    if allow_range:
        blk = blk.replace("<allowRange>false</allowRange>", "<allowRange>true</allowRange>")
    # an admin note on the item lives on the DomainObject block, not the FormItem one
    dom = (["      <com.sustain.DomainObject>", "        <default>",
            f"          <memo>{esc(memo)}</memo>", "        </default>",
            "      </com.sustain.DomainObject>"] if memo else
           ["      <com.sustain.DomainObject>", "        <default/>",
            "      </com.sustain.DomainObject>"])
    return "\n".join(
        ['<com.sustain.form.model.SearchCriteriaFormItem serialization="custom">'] + dom +
        ["      <com.sustain.form.model.FormItem>",
         "        <default>"] + lines + ["        </default>",
         f"        <string>{esc(terminal)}</string>", "        <null/>",
         "      </com.sustain.form.model.FormItem>", "      " + blk,
         "    </com.sustain.form.model.SearchCriteriaFormItem>"])


def synth_result(num, path, terminal, label, *, link=True, lookup=False):
    """A result COLUMN. panelAutoCompleteWithAllData is emitted iff link=true - the only
    combination the corpus shows for link=false is pac absent, so the two travel together."""
    d = []
    a = lambda t: d.append(" " * 10 + t)
    a("<grid>false</grid>"); a("<hidden>false</hidden>")
    a(f"<link>{'true' if link else 'false'}</link>")
    a("<noHoliday>false</noHoliday>"); a("<noWeekend>false</noWeekend>")
    a(f"<num>{num}</num>"); a("<readonly>true</readonly>"); a("<required>false</required>")
    a("<type>0</type>"); a('<associatedForm reference="../../../../.."/>')
    a("<autoFillNullValue>false</autoFillNullValue>"); a("<carryOver>false</carryOver>")
    a("<carryOverWhenRepeated>false</carryOverWhenRepeated>")
    a("<conditionalFormats/>"); a("<conditions/>"); a("<displayInactive>false</displayInactive>")
    a("<dropdown>false</dropdown>"); a("<exactMatchToCode>false</exactMatchToCode>")
    a("<existingEntityConditions/>"); a("<existingSelectAll>false</existingSelectAll>")
    a("<fillPanelOnSelect>false</fillPanelOnSelect>"); a("<filterConditions/>")
    a("<filterListByUser>false</filterListByUser>"); a("<forceDefaultValue>false</forceDefaultValue>")
    a("<freeFormLookup>false</freeFormLookup>"); a("<inPlaceEditable>false</inPlaceEditable>")
    a("<includeNulls>false</includeNulls>"); a("<innerJoin>false</innerJoin>")
    if lookup: a("<lookupItemFormat>LABEL</lookupItemFormat>")
    if label is not None: a(f"<label>{esc(label)}</label>")
    a("<labelIsTemplate>false</labelIsTemplate>"); a("<lookupDefaultValues></lookupDefaultValues>")
    a("<multiSelectLookup>false</multiSelectLookup>"); a("<newColumn>false</newColumn>")
    a("<newRow>false</newRow>"); a("<noLabel>false</noLabel>")
    a("<onlyAutoFillEmptyField>false</onlyAutoFillEmptyField>"); a("<openInNewTab>false</openInNewTab>")
    if link: a("<panelAutoCompleteWithAllData>false</panelAutoCompleteWithAllData>")
    a("<parameters/>"); a(f"<path>{esc(path)}</path>")
    a("<preventPanelLookups>false</preventPanelLookups>"); a("<previewSummary>false</previewSummary>")
    a("<readonlyIfEmpty>false</readonlyIfEmpty>"); a("<readonlyIfNotEmpty>false</readonlyIfNotEmpty>")
    a("<repeatPanelsOnPanelLookup>false</repeatPanelsOnPanelLookup>")
    a("<requiredTime>false</requiredTime>"); a("<runLookup>false</runLookup>")
    a("<showIfNullValueWhenHidden>false</showIfNullValueWhenHidden>")
    a('<showIfValues class="sorted-set"/>'); a('<showIfValues2 class="sorted-set"/>')
    a("<useCommaDisplayMask>false</useCommaDisplayMask>"); a("<userSelectedList/>")
    a("<widgetInMassType>NEVER_SHOW</widgetInMassType>"); a("<xrefConditions/>")
    return "\n".join(
        ['<com.sustain.form.model.SearchResultFormItem serialization="custom">',
         "      <com.sustain.DomainObject>", "        <default/>",
         "      </com.sustain.DomainObject>", "      <com.sustain.form.model.FormItem>",
         "        <default>"] + d + ["        </default>",
         f"        <string>{esc(terminal)}</string>", "        <null/>",
         "      </com.sustain.form.model.FormItem>",
         "      <com.sustain.form.model.SearchResultFormItem>", "        <default>",
         "          <displayRowTotals>false</displayRowTotals>",
         "          <displayTotals>false</displayTotals>",
         "          <hideForLookup>false</hideForLookup>",
         "          <hqlExpression></hqlExpression>", "        </default>",
         "      </com.sustain.form.model.SearchResultFormItem>",
         "    </com.sustain.form.model.SearchResultFormItem>"])


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

    Items are lifted verbatim, so all 54 fields and the resolved <string>entityClass.field come
    along untouched. What this decides is WHICH items and in WHAT ORDER - so that is all that
    can be wrong, and the gate's XStream<->JSON agreement check verifies the result.

    Two corrections made 2026-09-22, both found by that check, both of which had shipped:
    - the JSON half is taken from the donor entry with the same ORIGINAL num. It used to be
      looked up by path, and location/caseType/status are each BOTH a result column and a
      criterion - so three result columns carried their criterion's JSON.
    - an OR-ed (nested) criterion has a second list entry: a self-closing XStream back-
      reference at the end of <formItems>. That entry is now rebuilt with the parent's NEW
      position. It used to ride along inside the separator text, pointing at whichever
      criterion happened to come first.
    """
    by_key = {}
    for it in donor["items"]:
        sm = item_summary(it)
        if sm["kind"] != "ref":
            by_key.setdefault((sm["kind"], sm["path"]), []).append(it)
    missing = [pth for pth in paths if ("criterion", pth) not in by_key]
    if missing:
        raise ValueError(f"the donor has no criterion for: {missing}. Available: "
                         + ", ".join(sorted(sm["path"] for sm in donor["summaries"]
                                            if sm["kind"] == "criterion" and sm["path"])))
    crit = [by_key[("criterion", pth)][0] for pth in paths]
    results = [it for it in donor["items"] if item_summary(it)["kind"] == "result"]
    if keep_results is not None:
        want = set(keep_results)
        results = [it for it in results if item_summary(it)["path"] in want]

    donor_js = {j.get("num"): j for j in (donor["cfg"].get("formItems") or [])}
    ordered, js_items, n = [], [], 0
    for it in results + crit:
        old = item_summary(it)["num"]
        ordered.append(renumber(it, n))
        j = json.loads(json.dumps(donor_js[old])); j["num"] = n
        js_items.append(j); n += 1

    # nested (OR-ed) items: renumber after everything else, then add the reference entries
    CRIT_TAG = "com.sustain.form.model.SearchCriteriaFormItem"
    refs = []
    crit_positions = [i for i, it in enumerate(ordered) if item_class(it) == "SearchCriteriaFormItem"]
    for i, it in enumerate(ordered):
        if item_summary(it)["nested"] != 1:
            if item_summary(it)["nested"] > 1:
                raise ValueError("composing a criterion with more than one OR-ed child is not "
                                 "supported yet - its reference entries have not been verified")
            continue
        old_nested = [int(m.group(1)) for m in re.finditer(r"<num>(\d+)</num>", it)][-1]
        ordered[i] = renumber_nested(it, n)
        parent_idx = crit_positions.index(i) + 1          # 1-based among criteria siblings
        idx = "" if parent_idx == 1 else f"[{parent_idx}]"
        refs.append((n, f'<{CRIT_TAG} reference="../{CRIT_TAG}{idx}/{CRIT_TAG}/default/'
                        f'additionalItems/{CRIT_TAG}"/>', old_nested))
        for x in js_items[i].get("additionalItems", []):
            x["num"] = n
        n += 1
    for new_num, ref_xml, old_nested in sorted(refs):
        ordered.append(ref_xml)
        top = json.loads(json.dumps(donor_js[old_nested])); top["num"] = new_num
        js_items.append(top)

    out = dict(donor)
    out["items"] = ordered
    between = donor["seps"][1] if len(donor["seps"]) > 2 else "\n    "
    tail_ws = donor["seps"][-1]
    assert not tail_ws.strip(), "the donor's last separator should be whitespace only"
    out["seps"] = [donor["seps"][0]] + [between] * (len(ordered) - 1) + [tail_ws]
    out["summaries"] = [item_summary(i) for i in ordered]
    out["cfg"] = dict(donor["cfg"]); out["cfg"]["formItems"] = js_items
    if len(ordered) != len(donor["items"]):
        raise ValueError("compose changed the number of list entries - validationRule ids "
                         "cannot be subset safely (their mapping to items is unknown); keep "
                         "every donor item, or use build_search")
    rename(out, code, name)
    return out


def synthetic_ids(code, n):
    """Deterministic, unique-looking ids for a generated form: (srcId, [n item ids]).

    A generated form must NOT carry its donor's identity. srcId and the validationRule ids are
    the SOURCE environment's primary keys - the ones a later re-import appears to match on (an
    imported item stores the source id as configSourceId). Reusing S-Case-Simple's would give a
    test form the real form's identity, so a later import of either could land on the other.
    Synthetic ids fail SAFE: if the importer rejects them, nothing changes; if it stores them,
    they collide with nothing. Derived from the code so a rebuild is stable, and kept in the
    900,000,000+ range, far above any real id seen (max observed ~26,000).
    """
    h = int(hashlib.sha1(code.encode("utf8")).hexdigest()[:7], 16)
    base = 900_000_000 + (h % 90_000_000)
    return str(base), [str(base + 1 + i) for i in range(n)]


def build_search(donor, code, name, criteria, results, root=None, root_fqcn=None):
    """Assemble a from-scratch search: a REAL donor's form envelope (head/tail/settings) with
    freshly SYNTHESISED items swapped in. Same root entity as the donor.

    criteria: [(path, terminal, {lookup?, operator?, allow_range?}), ...]
    results:  [(path, terminal, label, {link?, lookup?}), ...]

    TWO SURFACES HERE ARE UNVERIFIED and cannot be settled without an observed import - both
    flagged in the return value, neither present in the synthesised ITEMS (which are proven):
      1. the form-level <validationRule ids="..."> - source-env pks with no from-scratch value;
         kept count-consistent with the item total by reusing the donor's, which is a guess.
      2. srcContent's sparse-JSON key ORDER - the payload is srcImportContent (the XStream,
         built from proven items); srcContent is rebuilt to AGREE on paths/counts but its key
         order is emitted canonically, which may differ from the platform's serializer.
    """
    out = dict(donor)
    # results first (numbered 0..), then criteria - the S-Case-Simple ordering
    items, n = [], 0
    for path, terminal, opt in results:
        items.append(synth_result(n, path, terminal, opt.get("label"),
                                   link=opt.get("link", False), lookup=opt.get("lookup", False)))
        n += 1
    for path, terminal, opt in criteria:
        if opt.get("label"):
            # a labelled criterion is always written in the full shape - see RICH_CRITERION_BASE
            items.append(synth_criterion_labelled(
                n, path, terminal, opt["label"], operator=opt.get("operator"),
                lookup=opt.get("lookup", False), multi=opt.get("multi", False),
                default_value=opt.get("default"), allow_range=opt.get("allow_range", False),
                relation=opt.get("relation", False)))
        else:
            items.append(synth_criterion(n, path, terminal, lookup=opt.get("lookup", False),
                                          operator=opt.get("operator"),
                                          allow_range=opt.get("allow_range", False)))
        n += 1
    out["items"] = items
    # the donor's own between-item separator (4 spaces), and a whitespace-only tail - the
    # donor's reference entries are NOT carried: they point at the donor's items, which are gone
    between = donor["seps"][1] if len(donor["seps"]) > 2 else "\n    "
    tail_ws = re.sub(r"<[^>]*>", "", donor["seps"][-1]).rstrip(" ") or "\n  "
    tail_ws = "\n  "
    out["seps"] = [donor["seps"][0]] + [between] * (len(items) - 1) + [tail_ws]
    out["summaries"] = [item_summary(i) for i in items]

    flags = []
    # (1) identity: synthetic, unique, deterministic - never the donor's (see synthetic_ids)
    src_id, item_ids = synthetic_ids(code, len(items))
    m = re.search(r'<validationRule ids="([^"]*)"', out["head"])
    if m:
        out["head"] = out["head"][:m.start(1)] + ",".join(item_ids) + out["head"][m.end(1):]
    out["env"] = dict(out["env"])
    out["env"]["srcId"] = src_id
    out["env"]["srcActionUrl"] = f"https://generated.invalid/ecms/admin/forms/edit?id={src_id}"
    flags.append(f"identity is synthetic: srcId {src_id}, {len(item_ids)} validationRule ids "
                 f"from {item_ids[0]}, srcActionUrl on generated.invalid. Non-empty values are "
                 f"PROVEN accepted for RULE imports, not yet for FORM - the first import settles "
                 f"it, and a rejection there changes nothing")

    # (1b) root entity: the envelope may come from a donor with a different root
    if root and root_fqcn:
        out["head"] = re.sub(r"<rootEntity>.*?</rootEntity>", f"<rootEntity>{root_fqcn}</rootEntity>",
                             out["head"], count=1)

    # (2) srcContent: the PROJECTION of the synthesised items - the same function the gate
    # verifies against every search-form item in the corpus, so the two halves agree by
    # construction rather than by a hand-written approximation.
    out["cfg"] = dict(donor["cfg"])
    if root:
        out["cfg"]["rootEntity"] = root
    out["cfg"]["formItems"] = [project(it) for it in items]
    out["cfg"].pop("drilldownForm", None)

    rename(out, code, name)
    set_drilldown(out, None)
    reproject_json(out)
    out["env"]["srcImportContent"] = (out["head"] +
        "".join(a + b for a, b in zip(out["seps"], out["items"])) + out["seps"][-1] + out["tail"])
    rehash(out)
    return out, flags


# ── the JSON half: srcContent as a projection of the XStream ──────────────────────────
# Derived from the corpus 2026-09-22, not assumed. One total key order explains all 869 JSON
# items (zero cycles; declaration order, subclass fields first). A field surfaces iff its
# value is non-default; multi-line strings become arrays of lines; parameters/conditions/
# conditionalFormats/userSelectedList become JSON structures; FORM=/CONDITION= prefixes drop.
# Set-typed values (userSelectedList, nested additionalItems) come out SORTED in the JSON;
# conditionalFormats come out in hash order - not positional - so agreement is checked
# order-insensitively. A condition's "hash" is not in the XStream at all and is masked.


ORDER = "additionalItemToOperator, additionalItems, aggregateFunction, allowRange, displayTotals, extraCriteria, hideForLookup, subQueryFunction, subQueryIdentifier, operator, customFormat, split, staticFieldText, type, label, path, hidden, requiredTime, readonly, required, link, customListType, customListQuery, footerText, openInNewTab, title, lookupItemFormat, lookupSearchType, conditions, grid, treeTable, columnHeaders, columnStyles, condValue, sort, previewSummary, newRow, numberFormat, style, newColumn, numberMask, conditionalFormats, defaultValue, sortable, emptyPanelMessage, noLabel, panelAutoCompleteMinChars, defaultCollapsed, dropdown, expandIfCondition, multiSelectLookup, filterListByUser, filterable, parameters, styleClass, userSelectedList, useCommaDisplayMask, userInterface, num, widgetInMassType, dateFormat, linkForm, memo, monthsToShow, pageSize".split(", ")

def blocks(it):
    """Top-level fields of every <default> block in this item's inheritance chain, NOT
    descending into nested additionalItems children. Returns {tag: raw_inner_or_None(selfclose)}"""
    out = {}
    for m in re.finditer(r'<(com\.sustain\.(?:form\.model\.\w+|DomainObject))>\s*<default\s*(/>|>)', it):
        if m.group(2) == '/>': continue
        s, d = m.end(), 1
        for mm in re.finditer(r'</?default>', it[s:]):
            d += 1 if mm.group(0) == '<default>' else -1
            if d == 0: body = it[s:s+mm.start()]; break
        # top-level tags in this default block
        depth = 0; i = 0
        for t in re.finditer(r'<(/?)(\w+)((?:\s[^>]*?)?)(/?)>', body):
            closing, name, attrs, sc = t.groups()
            if depth == 0 and not closing:
                if sc: out.setdefault(name, None)
                else:
                    # find matching close at this depth
                    s2, d2 = t.end(), 1
                    for u in re.finditer(rf'<(/?){name}\b[^>]*?(/?)>', body[s2:]):
                        if u.group(2): continue
                        d2 += -1 if u.group(1) else 1
                        if d2 == 0: out.setdefault(name, body[s2:s2+u.start()]); break
            if not closing and not sc: depth += 1
            elif closing: depth -= 1
        # only the item's OWN chain: stop after the first (outermost) item's blocks
    return out

def nested_items(it):
    """The items nested inside this item's <additionalItems>."""
    m = re.search(r'<additionalItems>(.*)</additionalItems>', it, re.S)
    if not m: return []
    body = m.group(1); res = []; depth = 0; start = None; base = None
    for t in re.finditer(r'<(/?)(com\.sustain\.form\.model\.\w+)[^>]*?(/?)>', body):
        c, name, sc = t.groups()
        if sc: continue
        if not c:
            if depth == 0: start, base = t.start(), name
            depth += 1
        else:
            depth -= 1
            if depth == 0 and name == base: res.append(body[start:t.end()])
    return res

def typed(tag, raw):
    v = html.unescape(raw)
    if v in ("true", "false"): return v == "true"
    if re.fullmatch(r"-?\d+", v) and tag not in ("path", "label", "memo", "defaultValue", "condValue"): return int(v)
    return v

LIST_KEYS = {"customListQuery", "columnHeaders", "columnStyles", "staticFieldText", "footerText"}

def structured(k, raw):
    """Values that are not plain scalars in the XStream."""
    if k == "parameters":
        d = {}
        for e in re.finditer(r'<entry>\s*<string>(.*?)</string>\s*<string>(.*?)</string>\s*</entry>', raw, re.S):
            v = html.unescape(e.group(2))
            d[html.unescape(e.group(1))] = re.split(r"\r\n|\n", v) if ("\n" in v) else v
        return d if d else None
    if k == "conditions":
        cs = re.findall(r'<com\.sustain\.condition\.model\.Condition>CONDITION=(.*?)</com\.sustain\.condition\.model\.Condition>', raw, re.S)
        # the JSON carries {"code","hash"}; the hash is NOT in the XStream - flag, cannot derive offline
        return [{"code": html.unescape(c), "hash": None} for c in cs] if cs else None
    if k == "conditionalFormats":
        out = []
        for cf in re.finditer(r'<com\.sustain\.form\.model\.FormItemConditionalFormat>(.*?)</com\.sustain\.form\.model\.FormItemConditionalFormat>', raw, re.S):
            body = cf.group(1); d = {}
            # Every child in XML order except the <formItem> back-pointer. TYPE COMES FROM THE
            # FIELD, not the text: `value` is a String even when it reads "false" (and the JSON
            # keeps it quoted), while `includeNulls` is a real boolean - surfaced only when true.
            for fm in re.finditer(r'<(\w+)>(.*?)</\1>', body, re.S):
                fk, raw_v = fm.group(1), fm.group(2)
                if raw_v == "":
                    continue
                v = html.unescape(raw_v)
                if fk in ("includeNulls",):
                    if v == "true":
                        d[fk] = True
                    continue
                if fk == "condition" and v.startswith("CONDITION="):
                    d[fk] = {"code": v[len("CONDITION="):], "hash": None}   # hash not in XStream
                    continue
                d[fk] = re.split(r"\r\n|\n", v) if "\n" in v else v
            out.append(d)
        return out or None
    if k == "userSelectedList":
        vals = [html.unescape(v) for v in re.findall(r'<string>(.*?)</string>', raw, re.S)]
        return sorted(vals) if vals else None          # a Set: XStream insertion order, JSON sorted
    return "UNHANDLED"

def project(it):
    own = it
    # strip nested children so their fields don't leak into the parent's field map
    for n in nested_items(it): own = own.replace(n, "")
    f = blocks(own)
    j = {}
    for k in ORDER:
        if k == "additionalItems":
            kids = nested_items(it)
            # JSON lists nested items sorted by num; XStream stores them in reverse
            if kids: j[k] = sorted((project(n) for n in kids), key=lambda d: d.get("num", 0))
            continue
        if k not in f: continue
        raw = f[k]
        if raw is None or raw == "":            # self-closing or empty: not surfaced
            continue
        if raw.lstrip().startswith("<"):
            val = structured(k, raw)
            if val is None: continue
            j[k] = val; continue
        val = typed(k, raw)
        if val is False: continue
        if k in ("linkForm", "drilldownForm") and isinstance(val, str) and val.startswith("FORM="):
            val = val[5:]
        if k == "expandIfCondition" and isinstance(val, str) and val.startswith("CONDITION="):
            val = {"code": val[10:], "hash": None}
        if isinstance(val, str) and "\n" in val:
            val = re.split(r"\r\n|\n", val)
        j[k] = val
    return j


import xml.etree.ElementTree as _ET


def _resolve_ref(parents, el, path):
    """Follow an XStream XPATH_RELATIVE reference from element el; None if it dangles."""
    cur = el
    for seg in path.split("/"):
        if seg == "..":
            cur = parents.get(cur)
        else:
            m = re.fullmatch(r"(.+?)(?:\[(\d+)\])?", seg)
            name, idx = m.group(1), int(m.group(2) or 1)
            kids = [c for c in cur if c.tag == name] if cur is not None else []
            cur = kids[idx - 1] if len(kids) >= idx else None
        if cur is None:
            return None
    return cur


def _canon(o):
    """For agreement: mask hashes, and compare set-like lists without regard to order."""
    if isinstance(o, dict):
        return {k: (None if k == "hash" else _canon(v)) for k, v in o.items()}
    if isinstance(o, list):
        c = [_canon(v) for v in o]
        try:
            return sorted(c, key=lambda v: json.dumps(v, sort_keys=True))
        except TypeError:
            return c
    return o


def json_agreement(p):
    """(faults, notes) - does srcContent say the same thing as srcImportContent, entry by entry?

    This is the check that was missing when S-Case-Quick shipped with the "Office" result
    column carrying the Agency CRITERION's JSON. Both halves were individually well-formed;
    only a comparison would have shown they described different forms.
    """
    faults, notes = [], []
    js = p["cfg"].get("formItems") or []
    if len(js) != len(p["items"]):
        faults.append(f"list length: XStream formItems has {len(p['items'])} entries, "
                      f"JSON has {len(js)}")
        return faults, notes
    try:
        root = _ET.fromstring(p["env"]["srcImportContent"])
    except _ET.ParseError as e:
        return [f"srcImportContent is not well-formed XML: {e}"], notes
    parents = {c: pnt for pnt in root.iter() for c in pnt}
    fi = root.find(".//formItems")
    entries = list(fi) if fi is not None else []
    for i, (it, j) in enumerate(zip(p["items"], js)):
        if is_ref(it):
            el = entries[i] if i < len(entries) else None
            tgt = _resolve_ref(parents, el, el.get("reference")) if el is not None else None
            if tgt is None:
                continue                          # dangling - reported by check()
            if not any(a.tag == "additionalItems" for a in _ancestors(parents, tgt)):
                faults.append(f"list entry {i} is a reference to something that is not a "
                              f"nested (OR-ed) item")
                continue
            it = _ET.tostring(tgt, encoding="unicode")
        if "reference=" in re.sub(r'<(associatedForm|formItem|additionalItemTo)\s+reference="[^"]*"\s*/>', "", it):
            notes.append(f"entry {i} ({j.get('path')}) holds a cross-item XStream reference; "
                         f"its JSON is compared only on the fields that do not depend on it")
            got = project(it)
            if _canon({k: v for k, v in got.items() if v is not None}) != \
               _canon({k: v for k, v in j.items() if k in got}):
                pass
            continue
        got = project(it)
        if _canon(got) != _canon(j):
            dk = sorted(k for k in set(got) | set(j) if _canon(got.get(k)) != _canon(j.get(k)))
            faults.append(f"entry {i} ({j.get('path')!r} num={j.get('num')}): XStream and JSON "
                          f"disagree on {dk}")
    return faults, notes


def _ancestors(parents, el):
    while el is not None:
        el = parents.get(el)
        if el is not None:
            yield el


def dangling_refs(p):
    try:
        root = _ET.fromstring(p["env"]["srcImportContent"])
    except _ET.ParseError:
        return []
    parents = {c: pnt for pnt in root.iter() for c in pnt}
    return [(el.tag, el.get("reference")) for el in root.iter()
            if el.get("reference") is not None
            and _resolve_ref(parents, el, el.get("reference")) is None]


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

    # the three invariants that hold on every platform export (28/28):
    for tag, ref in dangling_refs(p):
        faults.append(f"dangling XStream reference on <{tag.rsplit('.', 1)[-1]}>: {ref[:70]} - "
                      f"it points at nothing, so the import cannot rebuild that object")
    n_list = len(p["items"])
    ids = [i for i in p.get("validation_ids", []) if i]
    if ids and len(ids) != n_list:
        faults.append(f"validationRule ids: {len(ids)} ids for {n_list} list entries - on every "
                      f"platform export these are equal")
    jf, jn = json_agreement(p)
    faults += jf
    notes += jn

    nums = [sm["num"] for sm in p["summaries"] if sm["kind"] != "ref"]
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
        if sm["kind"] != "ref" and not sm["path"]:
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
        # a copy keeps the SOURCE form's identity (srcId + per-item ids) - which is exactly
        # how a normal cross-environment promotion works, and exactly what could collide if it
        # is imported back into the environment the source form lives in
        print(f"    IDENTITY: carries {origin}'s source ids (srcId {back['env']['srcId']}). Import "
              f"it only into an environment that does NOT hold {origin}; for a new search in the "
              f"same environment, build it with search_build.py, which uses synthetic ids.")
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
