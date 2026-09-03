#!/usr/bin/env python3
"""Rebuild the tables on an eProsecutor Case Financials print-to-PDF.

Why this exists: the case screen is the only ground truth you can reach without the
database, and its PDF text extraction is column-fragmented -- reading it in raw text order
interleaves labels, amounts and statuses so badly that hand-summing gives wrong answers.
Grouping words by their y coordinate rebuilds the visual rows, after which the obligations
and pay plan installments parse cleanly.

Usage:
  case_pdf_tables.py FILE.pdf --rows                 # every reconstructed row (start here)
  case_pdf_tables.py FILE.pdf --obligations          # label, PP flag, balances, due date
  case_pdf_tables.py FILE.pdf --installments         # pay plan installments with status
  case_pdf_tables.py FILE.pdf --obligations --match 'Bogus'   # filter and subtotal

--match filters by label substring (case-insensitive) and prints a subtotal of current
balances, which is what you need to compare against a report row that is scoped to one
collecting agency / item group.
"""

import argparse
import re
import sys
from collections import defaultdict

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("PyMuPDF not installed. Try: python3 -m pip install pymupdf")

MONEY = r'\$([\d,]+\.\d\d)'
DATE = r'(\d\d/\d\d/\d{4})'


def money(s):
    return float(s.replace(',', ''))


def visual_rows(path, tolerance=3):
    """Words grouped by y coordinate, so each entry is one visual row of the page."""
    doc = fitz.open(path)
    out = []
    for pno, page in enumerate(doc):
        buckets = defaultdict(list)
        for x0, y0, _x1, _y1, word, *_ in page.get_text("words"):
            buckets[round(y0 / tolerance)].append((x0, word))
        for key in sorted(buckets):
            text = " ".join(w for _, w in sorted(buckets[key]))
            out.append((pno + 1, text))
    return out


def parse_obligations(rows):
    """Obligation rows look like: <label> [PP] $cur $org MM/DD/YYYY ..."""
    pattern = re.compile(rf'^(?P<label>.*?)\s*(?P<pp>\bPP\b)?\s*{MONEY}\s+{MONEY}\s+{DATE}')
    found = []
    for pno, text in rows:
        m = pattern.match(text)
        if not m or not m.group('label').strip():
            continue
        # installment rows start with a date and have no label -- skip them here
        if re.match(rf'^{DATE}', text):
            continue
        found.append({
            'page': pno,
            'label': m.group('label').strip(),
            'on_pay_plan': bool(m.group('pp')),
            'current': money(m.group(3)),
            'original': money(m.group(4)),
            'due': m.group(5),
        })
    return found


def parse_installments(rows):
    """Installment rows look like: MM/DD/YYYY $cur $org <Status>.

    The status matters: only Past Due installments belong in an amount-past-due figure, and
    a plan commonly has many Scheduled rows after them. Plan header rows (No. PPxxxx ...)
    are captured too so installments can be attributed to a plan.
    """
    inst = re.compile(rf'^{DATE}\s+{MONEY}\s+{MONEY}\s*(?P<status>Past Due|Scheduled|Paid|Void\w*)?', re.I)
    header = re.compile(rf'^No\.\s+(?P<plan>\S+.*?)\s*(?P<status>Past Due|Scheduled|Paid)?\s*{MONEY}\s+{MONEY}\s*$')
    out, plan = [], None
    for pno, text in rows:
        h = header.match(text)
        if h:
            plan = h.group('plan').strip()
            out.append({'page': pno, 'kind': 'plan', 'plan': plan,
                        'status': (h.group('status') or '').strip(),
                        'current': money(h.group(3)), 'original': money(h.group(4))})
            continue
        m = inst.match(text)
        if m:
            out.append({'page': pno, 'kind': 'installment', 'plan': plan,
                        'due': m.group(1), 'current': money(m.group(2)),
                        'original': money(m.group(3)),
                        'status': (m.group('status') or '').strip()})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('--rows', action='store_true', help='dump every reconstructed row')
    ap.add_argument('--obligations', action='store_true')
    ap.add_argument('--installments', action='store_true')
    ap.add_argument('--match', help='filter by label substring and subtotal')
    args = ap.parse_args()

    rows = visual_rows(args.pdf)

    if args.rows:
        for pno, text in rows:
            print(f'p{pno} {text}')

    if args.obligations:
        obs = parse_obligations(rows)
        if args.match:
            obs = [o for o in obs if args.match.lower() in o['label'].lower()]
        print(f'{"label":42s} {"PP":3s} {"current":>12s} {"original":>12s}  due')
        for o in obs:
            print(f'{o["label"][:42]:42s} {"Y" if o["on_pay_plan"] else "N":3s} '
                  f'{o["current"]:12,.2f} {o["original"]:12,.2f}  {o["due"]}')
        print(f'{"SUBTOTAL current":42s} {"":3s} {sum(o["current"] for o in obs):12,.2f}'
              f'   ({len(obs)} rows)')

    if args.installments:
        items = parse_installments(rows)
        for it in items:
            if it['kind'] == 'plan':
                print(f'\nPLAN {it["plan"]}  [{it["status"]}]  '
                      f'current={it["current"]:,.2f} original={it["original"]:,.2f}')
            else:
                print(f'   {it["due"]}  {it["current"]:10,.2f} {it["original"]:10,.2f}  {it["status"]}')
        overdue = [i for i in items
                   if i['kind'] == 'installment' and i['status'].lower() == 'past due']
        print(f'\nPast Due installments: {len(overdue)}  '
              f'sum current = {sum(i["current"] for i in overdue):,.2f}')


if __name__ == '__main__':
    main()
