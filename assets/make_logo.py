"""Draw the Ripple logo: a minimal spider web, with a disruption at the
centre (red) rippling out along one thread to a customer at the edge.

Run:  python assets/make_logo.py   -> writes assets/logo.svg
"""

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRAY = "#8B93A1"
RED, ORANGE, PURPLE = "#E4572E", "#F3A712", "#7B5EA7"  # Port, Route, Customer colours in app.py
C = 64            # centre of the 128 x 128 canvas
RINGS = (26, 52)  # two rings of silk
SPOKES = 6
SAG = 0.88        # silk between two spokes sags towards the centre


def point(r: float, k: float) -> tuple[float, float]:
    angle = math.radians(-60 + 360 / SPOKES * k)
    return C + r * math.cos(angle), C + r * math.sin(angle)


def ring(r: float) -> str:
    """A closed ring made of curves that sag between the spokes."""
    d = ""
    for k in range(SPOKES):
        (x0, y0), (x1, y1) = point(r, k), point(r, k + 1)
        mx, my = point(r * SAG, k + 0.5)
        cx, cy = 2 * mx - (x0 + x1) / 2, 2 * my - (y0 + y1) / 2  # the curve passes through (mx, my)
        d += (f"M{x0:.1f} {y0:.1f} " if k == 0 else "") + f"Q{cx:.1f} {cy:.1f} {x1:.1f} {y1:.1f} "
    return f'<path d="{d}Z"/>'


def logo() -> str:
    spokes = "".join(f'<line x1="{C}" y1="{C}" x2="{point(RINGS[-1], k)[0]:.1f}" '
                     f'y2="{point(RINGS[-1], k)[1]:.1f}"/>' for k in range(SPOKES))
    rings = "".join(ring(r) for r in RINGS)
    (x1, y1), (x2, y2) = point(RINGS[0], 0), point(RINGS[1], 0)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="Ripple">
  <title>Ripple</title>
  <g stroke="{GRAY}" stroke-width="4" stroke-linecap="round" fill="none">{spokes}{rings}</g>
  <line x1="{C}" y1="{C}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{ORANGE}" stroke-width="7" stroke-linecap="round"/>
  <circle cx="{C}" cy="{C}" r="12" fill="{RED}"/>
  <circle cx="{x1:.1f}" cy="{y1:.1f}" r="8" fill="{ORANGE}"/>
  <circle cx="{x2:.1f}" cy="{y2:.1f}" r="9" fill="{PURPLE}"/>
</svg>
'''


if __name__ == "__main__":
    (HERE / "logo.svg").write_text(logo())
    print("wrote assets/logo.svg")
