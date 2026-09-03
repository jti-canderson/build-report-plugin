#!/usr/bin/env python3
"""pdfraster.py — rasterise every page of a report PDF, next to the PDF.

    python3 pdfraster.py sample_full.pdf            -> sample_full_p1.png, _p2.png, ...
    python3 pdfraster.py sample_full.pdf --scale 3  bigger, for reading small type

Why this is wired into run.sh rather than run by hand: the rasters are the only artifact a
human actually looks at, and a hand-run step silently goes stale. On 2026-09-01 the Case
Summary Report's PNGs were three hours older than its PDFs and still showed a defect that
had already been fixed - a picture of the bug, sitting in the folder, looking current.

Stale pages of a previous, longer render are deleted, so the folder cannot hold page 4 of a
report that now runs to three pages.
"""
import sys, pathlib

try:
    import fitz
except ImportError:
    sys.exit("PyMuPDF not available: python3 -m pip install pymupdf")


def main():
    argv = sys.argv[1:]
    if not argv:
        sys.exit(__doc__)
    path = pathlib.Path(argv[0])
    scale = 2
    if "--scale" in argv:
        scale = float(argv[argv.index("--scale") + 1])

    doc = fitz.open(path)
    stem, out_dir = path.stem, path.parent
    written = []
    for i, page in enumerate(doc, 1):
        png = out_dir / f"{stem}_p{i}.png"
        page.get_pixmap(matrix=fitz.Matrix(scale, scale)).save(png)
        written.append(png.name)

    # A shorter render must not leave the tail of a longer one behind.
    stale = [p for p in out_dir.glob(f"{stem}_p*.png") if p.name not in written]
    for p in stale:
        p.unlink()

    note = f"  (removed {len(stale)} stale: {', '.join(sorted(x.name for x in stale))})" if stale else ""
    print(f"rastered {len(written)} page(s) at {scale}x: {', '.join(written)}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
