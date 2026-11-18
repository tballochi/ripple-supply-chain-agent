"""Draw the Ripple logo: a spider web where a disruption at the centre
ripples out, node by node, in the app's colours (Port, Route, Vessel,
Shipment, Customer).

Run:  python assets/make_logo.py   -> writes assets/logo.svg and assets/icon.svg
"""

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
COLORS = ["#E4572E", "#F3A712", "#4C9F70", "#3A7CA5", "#7B5EA7"]  # same as app.py
GRAY = "#8B93A1"
C = 64  # centre of the 128 x 128 canvas
SAG = 0.86  # silk between two spokes sags towards the centre


def draw(rings, spokes, line, path_width, knot, node, halo):
    def pt(r, k):
        a = math.radians(-90 + 22.5 + 360 / spokes * k)
        return C + r * math.cos(a), C + r * math.sin(a)

    def curve(r, k0, k1):
        """Control point so a quadratic curve between two spokes sags."""
        (x0, y0), (x1, y1) = pt(r, k0), pt(r, k1)
        mx, my = pt(r * SAG, (k0 + k1) / 2)
        return 2 * mx - (x0 + x1) / 2, 2 * my - (y0 + y1) / 2

    f = lambda v: f"{v:.1f}"  # noqa: E731
    web = []
    for k in range(spokes):
        x, y = pt(rings[-1] + 6, k)
        web.append(f'<line x1="{C}" y1="{C}" x2="{f(x)}" y2="{f(y)}"/>')
    for r in rings:
        d = ""
        for k in range(spokes):
            (x0, y0), (x1, y1), (cx, cy) = pt(r, k), pt(r, k + 1), curve(r, k, k + 1)
            d += (f"M{f(x0)} {f(y0)} " if k == 0 else "") + f"Q{f(cx)} {f(cy)} {f(x1)} {f(y1)} "
        web.append(f'<path d="{d}Z"/>')

    # The ripple: out along spoke 0, then along the silk to spoke 1, then out again.
    hops = [(0, 0)] + [(r, 0) for r in rings[:2]] + [(rings[1], 1)] + [(r, 1) for r in rings[2:]]
    points = [(C, C)] + [pt(r, k) for r, k in hops[1:]]
    segments = []
    for i in range(1, len(points)):
        (x0, y0), (x1, y1) = points[i - 1], points[i]
        color = COLORS[min(i, len(COLORS) - 1)]
        if hops[i][1] != hops[i - 1][1]:  # along the silk
            cx, cy = curve(hops[i][0], hops[i - 1][1], hops[i][1])
            segments.append(f'<path d="M{f(x0)} {f(y0)} Q{f(cx)} {f(cy)} {f(x1)} {f(y1)}" stroke="{color}"/>')
        else:
            segments.append(f'<line x1="{f(x0)}" y1="{f(y0)}" x2="{f(x1)}" y2="{f(y1)}" stroke="{color}"/>')
    on_path = set(hops)
    knots = "".join(f'<circle cx="{f(pt(r, k)[0])}" cy="{f(pt(r, k)[1])}" r="{knot}"/>'
                    for r in rings for k in range(spokes) if knot and (r, k) not in on_path)
    nodes = "".join(f'<circle cx="{f(x)}" cy="{f(y)}" r="{node * (1.3 if i == 0 else 1)}" '
                    f'fill="{COLORS[min(i, len(COLORS) - 1)]}"/>' for i, (x, y) in enumerate(points))
    halo_ring = (f'<circle cx="{C}" cy="{C}" r="{halo}" fill="none" stroke="{COLORS[0]}" '
                 f'stroke-width="1.6" opacity="0.45"/>') if halo else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="Ripple">
  <title>Ripple</title>
  <g stroke="{GRAY}" stroke-width="{line}" stroke-linecap="round" fill="none">{"".join(web)}</g>
  <g fill="{GRAY}">{knots}</g>
  <g stroke-width="{path_width}" stroke-linecap="round" fill="none">{"".join(segments)}</g>
  {halo_ring}{nodes}
</svg>
'''


if __name__ == "__main__":
    # Full logo: three rings, eight spokes, small knots where the silk crosses.
    (HERE / "logo.svg").write_text(draw(rings=(17, 35, 55), spokes=8, line=2.2, path_width=4.2,
                                        knot=2.6, node=5.6, halo=13))
    # Tab icon: fewer, thicker threads so it still reads at 16 to 32 pixels.
    (HERE / "icon.svg").write_text(draw(rings=(24, 52), spokes=6, line=6, path_width=10,
                                        knot=0, node=11, halo=0))
    print("wrote assets/logo.svg and assets/icon.svg")
