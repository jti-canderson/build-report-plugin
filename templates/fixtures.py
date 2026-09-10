#!/usr/bin/env python3
"""
Fixture rows per template, written as TSV for render_check.groovy.

These prove LAYOUT only. They are plain maps - they say nothing about eSeries
entities, traversals or whether a path resolves. Deliberately awkward: long names,
long memos, empty cells, so the page is stressed rather than flattered.
"""
import pathlib
import sys

OUT = pathlib.Path(__file__).parent / "out"


def _w(name, rows):
    keys = list(rows[0].keys())
    lines = ["\t".join(keys)]
    for r in rows:
        lines.append("\t".join(str(r.get(k, "")).replace("\n", "\\n") for k in keys))
    p = OUT / f"{name}.tsv"
    p.write_text("\n".join(lines))
    print(f"fixture   {p.name}  {len(rows)} row(s), {len(keys)} key(s)")


def record_summary():
    head = dict(
        recTitle="Dr. Jordan Quinn Rivera Jr.", recKicker="Person Summary Report",
        recSlug="Person 42", m1v="42", m2v="Person", m3v="Active", m4v="09/02/2026",
        t1v="2", t2v="2", t3v="2")
    body = [
        ("NAME", ["Dr. Jordan", "Rivera Jr.", "Quinn", "Active"]),
        ("ADDRESS", ["Home", "1200 Market Street\nApartment 4B", "Denver", "CO", "80202", "Active"]),
        ("ADDRESS", ["Mailing", "PO Box 1842", "Denver", "CO", "80201", "Inactive"]),
        ("TELEPHONE", ["Cell", "(303) 555-0142", "Active"]),
        ("TELEPHONE", ["Work", "(303) 555-0188", "Inactive"]),
        ("CONTACT", ["Email", "jordan.rivera@example.test", "Active"]),
        ("CONTACT", ["Emergency Contact", "Alex Rivera", "Active"]),
        ("IDENTIFICATION", ["DL (OK)", "D000042"]),
        ("IDENTIFICATION", ["SSN", "***-**-0042"]),
        ("AKA", ["DBA", "Rivera Consulting", "", ""]),
        ("AKA", ["AKA", "Jordy", "Q.", "Rivera"]),
        ("STATUS", ["Veteran", "02/15/2026",
                    "Documentation reviewed; status remains active until further notice."]),
    ]
    rows = []
    for sec, cols in body:
        r = dict(head, section=sec)
        for i in range(6):
            r[f"c{i+1}"] = cols[i] if i < len(cols) else ""
        rows.append(r)
    _w("JTI_Record_Summary", rows)


def tabular_list():
    payers = ["Dana Whitfield", "Marcus Ellery-Boone", "P. Nakamura",
              "Yolanda Bright", "Christopher Vandenberg III"]
    obligs = ["Court Costs", "Restitution", "DA Supervision Fee",
              "Bogus Check Fee", "Victim Compensation Assessment"]
    agencies = ["Tulsa County DA", "Payne County DA", "District 7"]
    rows = [dict(
        rptTitle="Payments Collected by Collecting Agency",
        rptSubtitle="01/01/2026 - 12/31/2026   ·   All agencies   ·   Tulsa County",
        rptSlug="Payments Report",
        c1=f"{(i % 12) + 1:02d}/{(i % 27) + 1:02d}/2026",
        c2=f"R-{100000 + i * 7}",
        c3=payers[i % 5],
        c4=obligs[i % 5],
        c5=agencies[i % 3],
        c6=f"${((i * 3750) % 400000) / 100:,.2f}",
    ) for i in range(1, 46)]
    _w("JTI_Tabular_List", rows)


def grouped_summary():
    groups = [("Tulsa County DA", ["Court Costs", "Restitution", "DA Supervision Fee"]),
              ("Payne County DA", ["Court Costs", "Bogus Check Fee"]),
              ("District 7", ["Restitution", "Victim Compensation Assessment",
                              "Court Costs", "DA Supervision Fee"])]
    rows, n = [], 0
    for g, items in groups:
        for it in items:
            n += 1
            rows.append(dict(
                rptTitle="Collections by Agency and Obligation Type",
                rptSubtitle="01/01/2026 - 12/31/2026   ·   All counties",
                rptSlug="Collections Summary",
                grp=g, c1=it, c2=str(12 * n), c3=f"${n * 1875.5:,.2f}",
                c4=f"${n * 402.25:,.2f}", amt=f"{n * 1875.5:.2f}"))
    _w("JTI_Grouped_Summary", rows)


def statement():
    items = [("02/14/2026", "Court Costs", "Case CF-2026-00184", "$250.00"),
             ("02/14/2026", "Restitution", "Payable to A. Rivera", "$1,400.00"),
             ("02/14/2026", "DA Supervision Fee", "Monthly - February", "$40.00"),
             ("02/14/2026", "Victim Compensation Assessment", "", "$75.00")]
    rows = [dict(
        rptTitle="Receipt", rptSlug="Receipt R-100294",
        docNo="R-100294", docDate="02/14/2026",
        toName="Dr. Jordan Quinn Rivera Jr.",
        toAddr="1200 Market Street, Apartment 4B\nDenver, CO 80202",
        fromName="Tulsa County District Attorney",
        fromAddr="500 S Denver Ave, Suite 900\nTulsa, OK 74103",
        totalLabel="Total Received", totalValue="$1,765.00",
        methodLabel="Method", methodValue="Check #4471",
        c1=d, c2=desc, c3=note, c4=amt) for d, desc, note, amt in items]
    _w("JTI_Statement", rows)


def wide_table():
    payers = ["Dana Whitfield", "Marcus Ellery-Boone", "P. Nakamura",
              "Yolanda Bright", "Christopher Vandenberg III"]
    obligs = ["Court Costs", "Restitution", "DA Supervision Fee",
              "Bogus Check Fee", "Victim Compensation Assessment"]
    agencies = ["Tulsa County DA", "Payne County DA", "District 7"]
    rows = []
    for i in range(1, 41):
        assessed = ((i * 4250) % 500000) / 100
        collected = round(assessed * 0.62, 2)
        rows.append(dict(
            rptTitle="Payment Detail by Obligation and Assessment Group",
            rptSubtitle="01/01/2026 - 12/31/2026   ·   All agencies   ·   All counties",
            rptSlug="Payment Detail",
            c1=f"{(i % 12) + 1:02d}/{(i % 27) + 1:02d}/2026",
            c2=f"R-{100000 + i * 7}",
            c3=f"CF-2026-{184 + i:05d}",
            c4=payers[i % 5],
            c5=obligs[i % 5],
            c6=agencies[i % 3],
            c7=f"${assessed:,.2f}",
            c8=f"${collected:,.2f}",
            c9=f"${assessed - collected:,.2f}",
            amt=f"{collected:.2f}"))
    _w("JTI_Wide_Table", rows)


def eseries_summary():
    """The screenshot this template was built from, plus the awkwardness the screen
    happened not to show: a long contact line and a long note wrapping in a grid."""
    head = dict(
        recTitle="Felony Citation ~ 26-132", recSubtitle="Mick Foley",
        recStatus="Open", recSlug="Case 26-132",
        bn1="Sex Offender", bn2="Brady Disclosure",
        hReceived="07/30/2026", hNext="N/A", hAttorney="N/A", hDefense="N/A",
        hJurisdiction="Central", hVerticalUnit="Auto Insurance",
        hRelated="Auto Insurance", hCrimeCategory="Juvenile Probation Violation",
        hLocation="Acton")
    body = [
        ("DEFENDANT", dict(dType="Defendant", dPerson="Foley, Mick",
                           dContact="132 Here and There, Beverly Hills, CA 90210 [Residence]",
                           dAppearance="")),
        ("ASSETS", dict(aDate="09/02/2026", aType="Currency", aName="gsddsfgsdf",
                        aNumber="", aDescription="sdfg", aMemo="sdfgsdfg")),
        ("PERSONNEL", dict(pRole="Investigator", pPerson="May, Jake", pStatus="Current",
                           pAssigned="08/26/2026", pRemoved="")),
        ("PERSONNEL", dict(pRole="Prosecuting DDA", pPerson="Robbins, Austin",
                           pStatus="Current", pAssigned="08/20/2026", pRemoved="")),
        ("PERSONNEL", dict(pRole="Investigator", pPerson="Robbins, Austin",
                           pStatus="Current", pAssigned="08/26/2026", pRemoved="")),
        ("PERSONNEL", dict(pRole="Filing DDA [Brady]", pPerson="Sanchez, Alma",
                           pStatus="Current", pAssigned="08/19/2026", pRemoved="")),
        ("PERSONNEL", dict(pRole="Event DDA", pPerson="Svensson, Beck", pStatus="Current",
                           pAssigned="08/21/2026", pRemoved="")),
        ("CASENUMBERS", dict(nType="Filing DR #", nNumber="1234",
                             nAgency="Whittier Police Dept.", nActive="", nLead="")),
        ("STATUSHISTORY", dict(sStatus="Queued", sBegin="07/30/2026", sEnd="08/25/2026",
                               sNote="")),
        ("STATUSHISTORY", dict(sStatus="Closed", sBegin="08/25/2026", sEnd="08/25/2026",
                               sNote="Closed at filing review; see the conviction "
                                     "integrity note for the full history.")),
        ("REVIEW", dict(rType="Conviction Integrity", rContent="dasddfas",
                        rStatus="Complete", rDate="08/05/2026")),
    ]
    keys = ["section", "recTitle", "recSubtitle", "recStatus", "recSlug", "bn1", "bn2",
            "hReceived", "hNext", "hAttorney", "hDefense", "hJurisdiction",
            "hVerticalUnit", "hRelated", "hCrimeCategory", "hLocation",
            "dType", "dPerson", "dContact", "dAppearance",
            "aDate", "aType", "aName", "aNumber", "aDescription", "aMemo",
            "pRole", "pPerson", "pStatus", "pAssigned", "pRemoved",
            "nType", "nNumber", "nAgency", "nActive", "nLead",
            "sStatus", "sBegin", "sEnd", "sNote",
            "rType", "rContent", "rStatus", "rDate"]
    rows = []
    for sec, vals in body:
        r = {k: "" for k in keys}
        r.update(head); r["section"] = sec; r.update(vals)
        rows.append(r)
    _w("JTI_ESeries_Summary", rows)


BUILDERS = {
    "JTI_Record_Summary": record_summary,
    "JTI_Tabular_List": tabular_list,
    "JTI_Grouped_Summary": grouped_summary,
    "JTI_Statement": statement,
    "JTI_Wide_Table": wide_table,
    "JTI_ESeries_Summary": eseries_summary,
}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    want = sys.argv[1] if len(sys.argv) > 1 else None
    for k, fn in BUILDERS.items():
        if want in (None, k):
            fn()
