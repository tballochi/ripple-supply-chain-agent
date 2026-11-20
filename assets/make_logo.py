"""Draw the Ripple logo: python assets/make_logo.py  (writes logo.svg)

Three circles touching at one point, each larger than the last: a ripple
drawn with a compass. The white circle is the disruption, the blue ones are
what it reaches, hop after hop. logo.png (the browser tab icon) is rendered
from the SVG with headless Chrome.
"""

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOUCH = (34, 94)  # the point all three circles share, bottom left
CIRCLES = [(54, "#1E40AF"), (36, "#2563EB"), (18, "#FFFFFF")]  # radius, colour, largest first
BACKGROUND = ("#0F1B3D", "#060A16")


def svg() -> str:
    # Each centre sits on the diagonal through TOUCH, one radius away from it,
    # so every circle is tangent to the others at that point.
    step = 1 / math.sqrt(2)
    circles = "".join(f'<circle cx="{TOUCH[0] + r * step:.1f}" cy="{TOUCH[1] - r * step:.1f}" r="{r}" fill="{c}"/>'
                      for r, c in CIRCLES)
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
