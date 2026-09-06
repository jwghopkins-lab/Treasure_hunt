#!/usr/bin/env python3
"""A contact sheet of a hunt's stencils over their photographs.

    python3 pipeline/sheet.py content/<slug>.json out.jpg

One tile per stencil in the hunt's order, each the preview stencil.py wrote
beside the PNG (app/img/<slug>/<id>-stencil-preview.jpg), labelled with the
id, three to a row. For looking at, and for the report of a new hunt; the
previews are not committed, so run stencil.py first. Needs Pillow, like
stencil.py; not part of the build.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app"

TILE = (390, 520)
GAP = 12
LABEL = 26
PAPER = (236, 235, 231)
INK = (25, 27, 28)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    hunt = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out = Path(argv[1])
    stencils = hunt.get("stencils") or []
    if not stencils:
        print("sheet: the hunt has no stencils", file=sys.stderr)
        return 1
    cols = min(3, len(stencils))
    rows = (len(stencils) + cols - 1) // cols
    w, h = TILE
    sheet = Image.new("RGB", (cols * (w + GAP) + GAP, rows * (h + GAP + LABEL) + GAP), PAPER)
    draw = ImageDraw.Draw(sheet)
    for n, s in enumerate(stencils):
        src = Path(s["src"])
        preview = APP / src.parent / (src.name.replace("-stencil.png", "-stencil-preview.jpg"))
        x = GAP + (n % cols) * (w + GAP)
        y = GAP + (n // cols) * (h + GAP + LABEL)
        if preview.is_file():
            with Image.open(preview) as im:
                im = im.convert("RGB")
                im.thumbnail(TILE)
                sheet.paste(im, (x + (w - im.width) // 2, y + (h - im.height) // 2))
        else:
            draw.rectangle([x, y, x + w, y + h], outline=INK)
            draw.text((x + 8, y + 8), "no preview: run stencil.py", fill=INK)
            print(f"sheet: no preview at {preview}", file=sys.stderr)
        draw.text((x + 2, y + h + 6), s["id"], fill=INK)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=86)
    print(f"wrote {out} with {len(stencils)} stencils", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
