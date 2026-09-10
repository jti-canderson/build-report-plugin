#!/usr/bin/env python3
"""
Stamp each rendered example with its menu letter, for the template picker.

    python3 label_examples.py

Reads examples/<NAME>.png and writes examples/labeled/<LETTER>_<NAME>.png with a navy
caption band above the page: a big letter in a square, then the template name.

The band sits ABOVE the page rather than on top of it - a badge overlaid on the corner
covers the masthead, which is the part of a JTI report a person recognises first, and the
whole point of the picker is to show what the page looks like.

The ORIGINALS ARE NEVER TOUCHED. They are the true render, and the true render is what
gets compared against when a template changes.
"""
import pathlib
from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "examples"
OUT = SRC / "labeled"

NAVY = (28, 57, 113)          # jti_style.NAVY #1C3971
WHITE = (255, 255, 255)
BAND = 72
PAD = 18

TEMPLATES = [
    ("A", "JTI_Record_Summary", "Record Summary"),
    ("B", "JTI_ESeries_Summary", "eSeries Screen"),
    ("C", "JTI_Tabular_List", "List"),
    ("D", "JTI_Grouped_Summary", "Grouped Summary"),
    ("E", "JTI_Statement", "Statement"),
    ("F", "JTI_Wide_Table", "Wide Table (landscape)"),
]

# PIL will not fall back to a scalable font on its own: load_default() ignores the size and
# renders unreadably small next to a 612px page, so a real TTF has to be found.
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/Helvetica.ttc",
         "/Library/Fonts/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def font(size):
    for f in FONTS:
        if pathlib.Path(f).exists():
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
    return ImageFont.load_default()


def label(letter, stem, name):
    src = SRC / f"{stem}.png"
    if not src.exists():
        print(f"  skip   {stem}.png (not rendered)")
        return None
    page = Image.open(src).convert("RGB")
    w, h = page.size
    out = Image.new("RGB", (w, h + BAND), WHITE)
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, w, BAND], fill=NAVY)

    box = BAND - 2 * PAD
    d.rectangle([PAD, PAD, PAD + box, PAD + box], fill=WHITE)
    lf = font(int(box * 0.78))
    lw = d.textbbox((0, 0), letter, font=lf)
    d.text((PAD + box / 2 - (lw[2] - lw[0]) / 2 - lw[0],
            PAD + box / 2 - (lw[3] - lw[1]) / 2 - lw[1]), letter, font=lf, fill=NAVY)

    nf = font(26)
    nb = d.textbbox((0, 0), name, font=nf)
    d.text((PAD + box + 16, BAND / 2 - (nb[3] - nb[1]) / 2 - nb[1]), name, font=nf, fill=WHITE)

    out.paste(page, (0, BAND))
    OUT.mkdir(exist_ok=True)
    dest = OUT / f"{letter}_{stem}.png"
    out.save(dest)
    print(f"  wrote  {dest.relative_to(HERE)}  ({dest.stat().st_size // 1024} KB)")
    return dest


if __name__ == "__main__":
    for letter, stem, name in TEMPLATES:
        label(letter, stem, name)
