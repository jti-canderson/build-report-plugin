#!/usr/bin/env python3
"""Search the eProsecutor Entity reference PDFs for a field or relation.

The domain model is documented as per-entity PDFs (Case, Invoice, Party, Payment, PayPlan,
Person, Receipt, Restitution, Trust, Voucher, ...), normally under
MyReports/Entities. They are the only offline source of truth for what a property is
called and what type it is, and they are worth checking before writing a traversal --
guessing a path costs a full deploy-and-run cycle to disprove.

`pdftotext` is generally NOT installed on these machines, so this uses PyMuPDF.

Usage:
  entity_field.py county                       # search the default Entities directory
  entity_field.py payPlan --dir /path/to/Entities
  entity_field.py 'balance|amount' --regex
  entity_field.py --list                       # which entities are documented

Output shows the matching line plus the following line, because these PDFs put the
property name and its data type / description on consecutive lines.
"""

import argparse
import glob
import os
import re
import sys

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("PyMuPDF not installed. Try: python3 -m pip install pymupdf")

DEFAULT_DIR = os.path.expanduser("~/JaspersoftWorkspace/MyReports/Entities")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('term', nargs='?', help='field or relation name to look for')
    ap.add_argument('--dir', default=DEFAULT_DIR)
    ap.add_argument('--regex', action='store_true', help='treat term as a regex')
    ap.add_argument('--list', action='store_true', help='list documented entities')
    args = ap.parse_args()

    pdfs = sorted(glob.glob(os.path.join(args.dir, '*.pdf')))
    if not pdfs:
        sys.exit(f'No entity PDFs found in {args.dir} -- pass --dir')

    if args.list:
        for p in pdfs:
            print(os.path.basename(p))
        return
    if not args.term:
        sys.exit('Give a search term, or use --list')

    pattern = re.compile(args.term if args.regex else re.escape(args.term), re.I)

    for path in pdfs:
        lines = []
        for page in fitz.open(path):
            lines.extend(page.get_text().splitlines())
        lines = [l.strip() for l in lines]

        hits = [i for i, l in enumerate(lines) if l and pattern.search(l)]
        if not hits:
            continue

        print('=' * 74)
        print(os.path.basename(path))
        for i in hits:
            nxt = lines[i + 1] if i + 1 < len(lines) else ''
            print(f'  {lines[i]}   ||   {nxt}')


if __name__ == '__main__':
    main()
