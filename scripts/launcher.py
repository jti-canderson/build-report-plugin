#!/usr/bin/env python3
"""The report launcher: a StaticTextWidget snippet (Velocity) that runs the report for the
record on the screen - a "print this case" link or icon on a folder view.

Asked for in the builder (spec.launcher) and GENERATED here by scaffold.py, never written by
hand: the CSRF scrape, the POST to the report's own run endpoint and the placement warning are
the same every time, and the only choices are the icon, the words and which launch input gets
the record's id.

    spec["launcher"] = {"icon": "i-print", "text": "Print case summary", "param": "caseId",
                        "style": "blue"}

`icon` and `text` are both optional (with neither, the text defaults to "Run <title>").
`style` is "link" (plain blue text, the default), or a button with the eSeries classes:
"blue" (btn btn-primary), "grey" (btn btn-default) or "red" (btn btn-danger).
`param` is the launch input the record's id is posted to; when the spec has no input of that
name, normalise() adds one, so the rule, the .jrxml and the registration all carry it.

Icon class names come from the eSeries style guide (/ecms/help/style), captured in
templates/eseries_icons.json. Two families with different markup: font icons
(`glyphicon i-print`) and multi-coloured SVG icons (`icon printer`).
"""
import html
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ICONS_FILE = os.path.join(os.path.dirname(HERE), "templates", "eseries_icons.json")
PARAM_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,59}$")
MAX_TEXT = 80

# The eSeries button classes - the platform styles them, so nothing is drawn inline here.
BUTTON_CLASS = {"blue": "btn btn-primary", "grey": "btn btn-default", "red": "btn btn-danger"}
STYLES = ("link",) + tuple(BUTTON_CLASS)


def icons():
    with open(ICONS_FILE, encoding="utf8") as f:
        return json.load(f)


def family(icon, cat=None):
    """'font', 'svg', or None for a class the style guide does not list."""
    cat = cat or icons()
    if icon in cat["font"]:
        return "font"
    if icon in cat["svg"]:
        return "svg"
    return None


def validate(launcher):
    """Errors in a spec.launcher, in words. An empty list means it can be generated."""
    if launcher is None:
        return []
    if not isinstance(launcher, dict):
        return ["launcher: must be an object"]
    errs = []
    icon = (launcher.get("icon") or "").strip()
    if icon and family(icon) is None:
        errs.append(f"launcher icon '{icon}' is not in the eSeries style guide list "
                    f"(templates/eseries_icons.json)")
    text = launcher.get("text") or ""
    if len(text) > MAX_TEXT:
        errs.append(f"launcher text is longer than {MAX_TEXT} characters")
    style = (launcher.get("style") or "link").strip()
    if style not in STYLES:
        errs.append(f"launcher style '{style}' must be one of: {', '.join(STYLES)}")
    param = (launcher.get("param") or "").strip()
    if not PARAM_OK.match(param):
        errs.append("launcher: the launch input that receives the record id must be a name - "
                    "letters, digits and underscores, starting with a letter (e.g. caseId)")
    return errs


def clean(launcher):
    """The launcher as it is stored in spec.json: trimmed, only the known keys."""
    return {"icon": (launcher.get("icon") or "").strip(),
            "text": (launcher.get("text") or "").strip()[:MAX_TEXT],
            "param": (launcher.get("param") or "").strip(),
            "style": (launcher.get("style") or "link").strip()}


def normalise(spec):
    """Make sure the report HAS the input the launcher posts to. Returns True if one was
    added - a launcher pointing at an input the rule never declares prints a blank report."""
    la = spec.get("launcher")
    if not la:
        return False
    params = spec.setdefault("params", [])
    names = {p[0] for p in params if isinstance(p, (list, tuple)) and p}
    for c in spec.get("criteria") or []:
        names.update(c.get("params") or [])
    if la["param"] in names:
        return False
    params.append([la["param"], "java.lang.Long"])
    return True


def filename(spec):
    return f"{spec['name']}_Launcher.vm"


def _vel(s):
    """HTML-escaped AND inert to Velocity: a $ or # in the words must print, not evaluate."""
    # '#' first: the entity for '$' contains a '#' of its own.
    return html.escape(s, quote=True).replace("#", "&#35;").replace("$", "&#36;")


def gen(spec, order=None):
    """The .vm text, or '' when the spec asks for no launcher.

    `order` is every <parameter> name in the .jrxml, in declaration order (scaffold reads it
    off the generated file). The record id is posted at its input's index in that list."""
    la = spec.get("launcher")
    if not la:
        return ""
    cat = icons()
    code, title, param = spec["name"], spec.get("title") or spec["name"], la["param"]
    icon = la.get("icon") or ""
    text = la.get("text") or ("" if icon else f"Run {title}")
    tip = _vel(f"{text or title} (opens the PDF)")
    mark = ""
    if icon:
        mark = cat["markup"][family(icon, cat)].format(cls=icon)
    label = mark + (" " if mark and text else "") + _vel(text)
    style = la.get("style") or "link"
    look = (f'class="{BUTTON_CLASS[style]}"' if style in BUTTON_CLASS
            else 'style="color:#054CFF;"')
    root = spec.get("root") or "record"
    # The id goes at the input's OWN index among every <parameter> the .jrxml declares,
    # journalLogo included: the run screen binds reportParams[N] by position. Nothing else is
    # posted, so the other inputs (and the logo) keep their defaults.
    order = list(order or ["journalLogo"] + [p[0] for p in spec.get("params") or []])
    if param not in order:
        order.append(param)
    i = order.index(param)
    posts = f"  add('reportParams[{i}].name','{param}'); add('reportParams[{i}].value','$object.id');"
    return f"""## {title} - launcher. GENERATED by scaffold.py from spec.launcher: change it in the
## builder and rebuild, rather than editing this file.
##
## WHERE IT GOES: a StaticTextWidget item on the {root} folder view, at the FORM ROOT - before
## the first panel, or in a panel whose items sit on the {root} itself - so its $object is the
## {root}. A static item inherits $object from the item in front of it: placed after a party,
## charge or event item it would post THAT record's id as {param} and run the report for the
## wrong record, or for nothing.
##
## WHAT IT DOES: posts {param} = $object.id to the report's own run endpoint, as the Reports
## run screen does (reportParams[N] at the input's position among the .jrxml's parameters,
## plus format), and opens the PDF in a new tab. The
## report is addressed by its CODE ({code}), never the numeric id, which differs per
## environment. The base path comes from the page, so district paths (/04/ecms/...) work.
##
## FRAGILE PART: Velocity cannot see the CSRF token, so it is read from the page's hidden
## _csrf input. This mimics a platform form; it is config, not a supported launcher. Test it
## once on a real record after the report is registered under the code {code}.
#set($reportCode = "{code}")
#if($object && $object.id)
<a href="javascript:void(0)" {look} title="{tip}" onclick="(function(){{
  var base=location.pathname.replace(/\\/ecms\\/.*$/, '/ecms/');
  var f=document.createElement('form');
  f.method='post'; f.action=base+'reportsGenerate/run/$reportCode/onRun'; f.target='_blank';
  var add=function(n,v){{var i=document.createElement('input');i.type='hidden';i.name=n;i.value=v;f.appendChild(i);}};
  add('code','$reportCode');
{posts}
  add('format','pdf');
  var t=document.querySelector('input[name=_csrf]'); if(t){{add('_csrf',t.value);}}
  document.body.appendChild(f); f.submit(); f.parentNode.removeChild(f);
}})()">{label}</a>
#end
"""
