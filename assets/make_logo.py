"""Draw the Ripple logo: python assets/make_logo.py  (writes logo.svg)

Three circles touching at one point, each larger than the last: a ripple
drawn with a compass, in black and white with one green disc, the point
where the disruption starts. logo.png (the browser tab icon) is rendered
from the SVG with headless Chrome.
"""

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOUCH = (30, 98)  # the point all three circles share, bottom left
# radius, colour, filled or drawn as a ring, largest first
CIRCLES = [(50, "#FFFFFF", False), (33, "#8A8A8A", False), (16, "#3BD671", True)]
RING = 6
BACKGROUND = ("#000000", "#000000")


def svg() -> str:
    # Each centre sits on the diagonal through TOUCH, one radius away from it,
    # so every circle is tangent to the others at that point.
    step = 1 / math.sqrt(2)
    circles = "".join(
        f'<circle cx="{TOUCH[0] + r * step:.1f}" cy="{TOUCH[1] - r * step:.1f}" r="{r if filled else r - RING / 2}" '
        + (f'fill="{c}"/>' if filled else f'fill="none" stroke="{c}" stroke-width="{RING}"/>')
        for r, c, filled in CIRCLES)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="Ripple">
  <title>Ripple</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BACKGROUND[0]}"/><stop offset="1" stop-color="{BACKGROUND[1]}"/>
    </linearGradient>
  </defs>
  <rect width="128" height="128" rx="28" fill="url(#bg)"/>
  {circles}
</svg>
"""


if __name__ == "__main__":
    (HERE / "logo.svg").write_text(svg())
    print("Wrote", HERE / "logo.svg")
