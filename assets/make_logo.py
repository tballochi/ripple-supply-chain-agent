"""Draw the Ripple logo: python assets/make_logo.py  (writes logo.svg)

One disruption (the node in the middle) sends rings outwards, like a stone
in water; the white path hops from ring to ring, the way Ripple follows a
port to its vessels, shipments and customers. logo.png is rendered from the SVG with
headless Chrome: python assets/make_logo.py --png.
"""

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEAL, MINT, NAVY_TOP, NAVY_BOTTOM = "#22D3EE", "#5EEAD4", "#14213D", "#070B17"
C = 64  # the disruption, in the middle
# radius, ring opacity, where the path crosses the ring (degrees)
RINGS = [(22, 0.9, 70), (38, 0.6, 22), (54, 0.35, 52)]


def on_ring(radius: float, degrees: float) -> tuple[float, float]:
    a = math.radians(degrees)
    return round(C + radius * math.cos(a), 1), round(C - radius * math.sin(a), 1)


def svg() -> str:
    rings = "".join(f'<circle cx="{C}" cy="{C}" r="{r}" stroke-opacity="{o}"/>' for r, o, _ in RINGS)
    hops = [on_ring(r, d) for r, _, d in RINGS]
    path = "M" + " L".join(f"{x} {y}" for x, y in [(C, C)] + hops)
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="{6.5 - i}"/>' for i, (x, y) in enumerate(hops))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="Ripple">
  <title>Ripple</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{NAVY_TOP}"/><stop offset="1" stop-color="{NAVY_BOTTOM}"/>
    </linearGradient>
    <linearGradient id="wave" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="{TEAL}"/><stop offset="1" stop-color="{MINT}"/>
    </linearGradient>
  </defs>
  <rect width="128" height="128" rx="30" fill="url(#bg)"/>
  <g fill="none" stroke="url(#wave)" stroke-width="3.5">{rings}</g>
  <path d="{path}" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <g fill="#FFFFFF">{dots}</g>
  <circle cx="{C}" cy="{C}" r="10" fill="url(#wave)" stroke="{NAVY_BOTTOM}" stroke-width="2.5"/>
</svg>
"""


if __name__ == "__main__":
    (HERE / "logo.svg").write_text(svg())
    print("Wrote", HERE / "logo.svg")
