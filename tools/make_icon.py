"""
Generate the SafeClean application icon.

Draws at 1024px and downsamples, so the small sizes stay clean. The mark is a
progress ring around a checkmark: the ring says "disk usage", the check says
"nothing of yours was touched".

    python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "safeclean" / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]

BG = (18, 21, 28, 255)
BORDER = (44, 51, 66, 255)
RING_TRACK = (33, 39, 51, 255)
RING = (107, 138, 253, 255)
CHECK = (240, 243, 248, 255)


def build(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded tile
    radius = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius,
                        fill=BG, outline=BORDER, width=max(1, size // 128))

    # Progress ring, open at the bottom so it reads as a gauge
    pad = size * 0.20
    width = int(size * 0.085)
    box = [pad, pad, size - pad, size - pad]
    d.arc(box, start=125, end=55, fill=RING_TRACK, width=width)
    d.arc(box, start=125, end=340, fill=RING, width=width)

    # Checkmark
    cw = size * 0.075
    pts = [
        (size * 0.345, size * 0.505),
        (size * 0.455, size * 0.618),
        (size * 0.665, size * 0.383),
    ]
    d.line(pts, fill=CHECK, width=int(cw), joint="curve")
    for point in (pts[0], pts[-1]):
        r = cw / 2
        d.ellipse([point[0] - r, point[1] - r, point[0] + r, point[1] + r],
                  fill=CHECK)
    return img


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    master = build(1024)

    ico_path = OUT_DIR / "icon.ico"
    master.save(ico_path, format="ICO",
                sizes=[(s, s) for s in SIZES])

    png_path = OUT_DIR / "icon.png"
    master.resize((256, 256), Image.LANCZOS).save(png_path)

    print(f"wrote {ico_path}")
    print(f"wrote {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
