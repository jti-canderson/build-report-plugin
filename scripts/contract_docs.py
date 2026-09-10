#!/usr/bin/env python3
"""
Write RULE_REGISTRATION.txt and JRXML_CONTRACT.txt from the rule + jrxml themselves.

Called by rule_zip.py, which has already parsed both files and already failed the build if
they disagree - so these documents cannot describe a contract the zip does not ship.

WHY THIS EXISTS: both files used to be typed out by hand, and both are mostly a restatement
of tables the tooling had already derived to build the zip. Retyping them cost ~70 lines of
the slowest kind of token per report and could drift from the artifact they describe. What is
mechanical is generated here; what is judgment stays with the person, in a NOTES block.

NOTES BLOCKS ARE PRESERVED. Everything between the NOTES markers is human-authored and is
read back out of the existing file and re-inserted on every regeneration. This matters
because finish.sh re-runs rule_zip.py on EVERY iteration of a build - a generator that
clobbered the notes would silently eat the deploy warnings somewhere around the fourth
render, which is exactly when nobody is re-reading these files.
"""
import os
import re

BEGIN = "### NOTES - yours. Regenerating this file preserves everything to END NOTES."
END = "### END NOTES"

SEED_REG = """TODO before this ships. Delete the lines that do not apply.
  - Which inputs are OPTIONAL by design, and what an empty one means (no value = all?).
  - Any input that only accepts a fixed set of values, and what happens to a bad one.
  - Anything the deployer must do in a particular order."""

SEED_CON = """TODO before this ships.
  - SECTION ORDER, if the rule emits more than one section. Jasper groups CONSECUTIVE rows
    and does not sort, so name the order the rule must emit and where it does it.
  - Which fields belong to which section, and which are required on EVERY row.
  - WHAT IS NOT PROVEN: every traversal the local render did not exercise, every lookup list
    name, every date field that was a choice rather than a certainty."""


def notes(path, seed):
    """The human-authored block from an existing file, or the seed for a new one."""
    if not os.path.exists(path):
        return seed
    text = open(path, encoding='utf8').read()
    m = re.search(re.escape(BEGIN) + r'\n(.*?)\n' + re.escape(END), text, re.S)
    return m.group(1) if m else seed


def geometry(jrxml):
    xml = open(jrxml, encoding='utf8').read()

    def attr(n):
        m = re.search(n + r'="([^"]+)"', xml)
        return m.group(1) if m else '?'
    w, h = attr('pageWidth'), attr('pageHeight')
    # A jrxml has no orientation attribute unless it is landscape, and the reliable signal is
    # the page being wider than it is tall - not the attribute's absence.
    try:
        orient = 'Landscape' if int(w) > int(h) else 'Portrait'
    except ValueError:
        orient = '?'
    return orient, w, h, attr('columnWidth')


def fields(jrxml):
    xml = open(jrxml, encoding='utf8').read()
    return re.findall(r'<field\s+name="([^"]+)"(?:\s+class="([^"]+)")?', xml)


def write(out_dir, meta, inputs, outputs, self_supplied, jrxml, template=None):
    reg = os.path.join(out_dir, 'RULE_REGISTRATION.txt')
    con = os.path.join(out_dir, 'JRXML_CONTRACT.txt')
    name = meta['name']
    orient, pw, ph, cw = geometry(jrxml)

    L = [f"{name} - what to type into the empty rule form",
         "=" * (len(name) + 38),
         f"Faster path: import RULE-{meta['code']}.zip instead of typing any of this. These values",
         "are what that zip contains, for when the form has to be filled by hand.", "",
         f"Code             {meta['code']}",
         f"Name             {name}",
         f"Category         {meta['category']}",
         f"Description      {meta['description']}",
         "Transaction End  false",
         "Engine           SCRIPT", "",
         "INPUT PARAMETERS   (bare name, no leading underscore - the rule reads _Name)"]
    for p in inputs:
        L.append(f"  {p['name']:<12} {p['type']:<10} {p['className']}")
    L += ["", "OUTPUT PARAMETER   <- WITHOUT THIS THE REPORT RENDERS A BLANK PAGE AND REPORTS SUCCESS"]
    for p in outputs:
        L.append(f"  {p['name']:<12} {p['type']:<10} {p['className']}")
    L += ["",
          "The names above must match the .jrxml <parameter> names EXACTLY. The registration binds",
          "by name, so a mismatch fails when the report is RUN, not when it is saved.", "",
          BEGIN, notes(reg, SEED_REG), END, ""]
    open(reg, 'w', encoding='utf8').write("\n".join(L))

    C = [f"{name} - the rule/layout contract",
         "=" * (len(name) + 26),
         "Generated from the .groovy and the .jrxml by rule_zip.py. Never hand-edit the .jrxml;",
         "edit its generator and re-run it." + (f"  Template: {template}" if template else ""), "",
         "PARAMETERS (jrxml <parameter> -> Groovy)"]
    for p in inputs:
        C.append(f"  {p['name']:<18} -> _{p['name']}")
    for s in sorted(self_supplied):
        C.append(f"  {s:<18}    supplied by the template itself, NOT a launch input")
    C += ["",
          "FIELDS - every one must be a key in the rule's base map, or that cell silently empties"]
    for fname, fcls in fields(jrxml):
        C.append(f"  {fname:<18} {(fcls or 'java.lang.String').replace('java.lang.', '')}")
    C += ["", "GEOMETRY",
          f"  {orient}, {pw}x{ph}pt page, {cw}pt column.", "",
          "WHAT IS PROVEN LOCALLY",
          "  Layout, pagination, grouping, the field contract, PDF export - whatever variants",
          "  verification/run.sh actually rendered.", "",
          "WHAT IS NOT",
          "  Any traversal. The fixture is hand-written, so a path that returns a value here can",
          "  still empty a column in the target environment. See the notes below.", "",
          BEGIN, notes(con, SEED_CON), END, ""]
    open(con, 'w', encoding='utf8').write("\n".join(C))

    return reg, con
