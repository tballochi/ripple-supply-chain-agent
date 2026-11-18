"""Draw the Ripple logo: a black app icon with a silver spider web, and one
red node where the disruption starts.

Run:  python assets/make_logo.py   -> writes assets/logo.svg
"""

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
RED = "#FF3B30"
SAG = 0.86  # silk between two spokes sags towards the centre

DEFS = f'''<defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#26282E"/><stop offset="1" stop-color="#050506"/>
    </linearGradient>
    <linearGradient id="silver" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/><stop offset="0.45" stop-color="#AEB5BF"/>
      <stop offset="0.7" stop-color="#E9ECF0"/><stop offset="1" stop-color="#7D848E"/>
    </linearGradient>
    <radialGradient id="glow">
      <stop offset="0" stop-color="{RED}" stop-opacity="0.75"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/>
    </radialGradient>
  </defs>'''


def web(cx, cy, rings, start_deg, sweep_deg, spokes):
    """Spokes from (cx, cy) and sagging rings between them."""
    def pt(r, k):
        a = math.radians(start_deg + sweep_deg / spokes * k)
        return cx + r * math.cos(a), cy + r * math.sin(a)

    out = [f'<line x1="{cx}" y1="{cy}" x2="{pt(rings[-1], k)[0]:.1f}" y2="{pt(rings[-1], k)[1]:.1f}"/>'
           for k in range(spokes)]
    for r in rings:
        d = ""
        for k in range(spokes):
            (x0, y0), (x1, y1) = pt(r, k), pt(r, k + 1)
            mx, my = pt(r * SAG, k + 0.5)
            qx, qy = 2 * mx - (x0 + x1) / 2, 2 * my - (y0 + y1) / 2
            d += (f"M{x0:.1f} {y0:.1f} " if k == 0 else "") + f"Q{qx:.1f} {qy:.1f} {x1:.1f} {y1:.1f} "
        out.append(f'<path d="{d}Z"/>')
    return "".join(out), pt


def icon() -> str:
    lines, pt = web(64, 64, (16, 32, 48), -90, 360, 8)
    x, y = pt(32, 1)  # the red node sits where a spoke crosses the middle ring
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="Ripple">
  <title>Ripple</title>
  {DEFS}
  <rect width="128" height="128" rx="28" fill="url(#bg)"/>
  <rect x="1" y="1" width="126" height="126" rx="27" fill="none"
        stroke="#FFFFFF" stroke-opacity="0.08" stroke-width="2"/>
  <g stroke="url(#silver)" stroke-width="2.6" stroke-linecap="round" fill="none">{lines}</g>
  <circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="url(#glow)"/>
  <circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{RED}"/>
</svg>
'''


if __name__ == "__main__":
    (HERE / "logo.svg").write_text(icon())
    print("wrote assets/logo.svg")
