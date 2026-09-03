# The handoff (`HANDOFF.md` + Deployment Guide)

Two artifacts, one source of truth.

| File | Lives in | Audience | Format |
|---|---|---|---|
| `HANDOFF.md` | the report folder | the next person (or instance) to touch the report | Markdown, terse, updated constantly |
| `Deployment Guide- <Report Name> (<Report_Code>).docx` | the report folder | the client, the ticket, a deployer | Word, prose, regenerated from the above |

`HANDOFF.md` is authoritative. The docx is a rendering of it, so never write facts into the
docx that are not in the Markdown — they will be lost at the next regeneration.

## When to write it

- **First contact with a report**, before you finish the first change. If a folder has no
  `HANDOFF.md`, creating one is part of the work.
- **Every subsequent change**, in the same turn as the rule or jrxml edit — new field,
  changed path, new parameter, corrected guess, gap closed, new client request.
- **Regenerate the docx** when the change is material (fields, parameters, paths, deploy
  steps). Cosmetic and internal notes can wait.

A stale handoff is worse than a missing one: it gets believed. If you cannot verify a claim
in it any more, mark it unproven rather than deleting it.

## `HANDOFF.md` sections, in order

1. **Title line** — ticket, report code, environment it was built in, date last updated.
   Then two or three sentences on what the report is *for* and where it is launched from.
2. **Artifacts and current state** — a table: rule, report registration, jrxml, any widget.
   For each: where it lives (**with the environment named**) and whether it is current,
   stale, or pending an upload. This is the first thing anyone reads; it must be true.
3. **Local files** — every file in the folder and what it is, including **both** forms of the
   rule (the `.groovy` source and the generated `RULE-<Code>.zip` import), and whether the zip
   was regenerated after the last rule change. Say plainly that the folder is
   the source of truth and that reports are never compiled locally.
4. **Parameters** — a table of JRXML name, Groovy binding, whether required, and behaviour.
   Note that values arrive as Strings whatever the declared class, and any registration trap
   (a stray Preset Value, a required-vs-optional mismatch).
5. **Entities and fields used** — per entity, the exact paths, and where they were verified
   (folder view config, Data Dictionary, Velocity test). Then a **corrected-guesses table**:
   the right name beside the wrong one. This is the highest-value section in the file — it is
   what stops the next person "fixing" a verified path back to a plausible wrong one.
6. **Rule logic** — numbered steps, including the API shapes that only work one way
   (two-arg `get()`, `binding.hasVariable`, a traversal that needs a null guard) and the
   deliberate presentation choices, so they are not read as bugs and undone.
7. **Output fields** — grouped by section, with the count and the "every field is a String"
   statement. Then the layout facts: page size, column width, group flags, band geometry.
8. **Anything hand-rolled** — a launcher widget, a CSRF scrape, a placement that must not
   move. Say *why* it is fragile and whether it is the house pattern.
9. **Deploy** — the numbered steps, which uploads are independent, and how to see a change
   (refresh the report tab; never re-navigate a POST result).
10. **Open items** — what is not deployed, what has never rendered, which branch of the data
    has no test case, any convention the report does not yet meet. Never an empty section.
11. **Client requests** — dated table of request, who asked, and status. This is the record
    that a request was honoured, and the place to notice one that was not.

## Rules that keep it useful

**Name the environment with every id.** "rule 10442 in <environment>", never "rule 10442". Ids are
per-environment primary keys; a bare number sends someone editing the wrong record.

**Distinguish proven from assumed.** A section that has never rendered, a property seen blank
in the one test case, a traversal that has not run — each says so explicitly. Writing "verified"
about anything you have not seen execute is the one failure this file exists to prevent.

**Keep the reasoning where it belongs.** The `.groovy` header holds the why of the code, the
`JRXML_CONTRACT.txt` holds the field-by-field contract and its change log, and `HANDOFF.md`
holds state, orientation, and open questions. Repeat only what a reader needs in place.

## Generating the docx

The corpus convention is section headings `1. Prerequisites`, `2. Required Parameters`,
`3. Entities & Fields Used`, `4. Business Rules Logic Summary`, `5. Output Fields`, then
whatever the report needs (deployment steps, known gaps, client requests). House look: US
Letter (12240 × 15840 DXA), 1" margins, Arial throughout, title 16pt bold, headings 14pt bold,
body 11pt, tables in the `TableGrid` style with a shaded header row.

With Node available, write it with the `docx` npm package. **This machine has had no
`node`, `pandoc`, or `soffice`**, so the reliable path is to clone an existing guide's package
and swap the body — it inherits the correct styles, numbering, and page setup:

```python
zin  = zipfile.ZipFile(EXISTING_GUIDE)          # any Deployment Guide- *.docx in the corpus
orig = zin.read('word/document.xml').decode('utf8')
head = orig[:orig.find('<w:body>') + len('<w:body>')]   # keep its namespaces
doc  = head + generated_body_xml + sectPr + '</w:body></w:document>'
# rewrite word/document.xml and docProps/core.xml <dc:title>, copy every other part verbatim
```

Bullets need a `numId` that the inherited `numbering.xml` actually defines as a bullet — check
before trusting it. Tables need `<w:tblStyle w:val="TableGrid"/>` plus explicit `tblGrid`
widths in DXA summing to `tblW`. Escape text, and never emit `\n` inside a `<w:t>`.

Verify by parsing the result and dumping its paragraphs back to text: confirm the section
order, that nothing was truncated, and that **no text from the cloned source survives**
(grep the old report's name — a count of zero is the check). Without LibreOffice you cannot
render it, so say that the layout is unrendered when you hand it over.

**Extracting the text is a trap worth knowing.** The obvious
`re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml)` returns table markup as well as prose on these
documents — a table cell's run is preceded by its `<w:tcPr>`, and a non-greedy match that
starts at the wrong `<w:t` swallows a screenful of `<w:tcW>`/`<w:shd>`/`<w:rPr>`. Dumping
that into context is thousands of tokens of noise for a handful of headings. Strip the
tags first, then match:

```python
import re, html
def doc_text(xml):
    body = re.sub(r'<w:tbl>.*?</w:tbl>', '\u3010table\u3011', xml, flags=re.S)  # tables as placeholders
    return [html.unescape(t) for t in re.findall(r'<w:t[^>]*>([^<]*)</w:t>', body) if t.strip()]
```

`[^<]*` instead of `.*?` is the fix: a real text run never contains `<`, so the character
class cannot run past the end of its own element. Read the *template* the same way before
cloning it — you need its `<w:body>` prefix and its `<w:sectPr>`, not its prose.
