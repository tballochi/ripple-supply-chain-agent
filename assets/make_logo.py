"""Draw the Ripple logo: python assets/make_logo.py  (writes logo.svg)

Three hops: a green node (the disruption) and three white nodes, each smaller
than the last, joined by one line, the way a disruption travels through the
graph and fades. Centred on a 128 grid. logo.png (the browser tab icon) is
rendered from the SVG with headless Chrome.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
GREEN, WHITE, BLACK = "#3BD671", "#FFFFFF", "#000000"
START = (37, 87, 12)                                  # the disruption: x, y, radius
HOPS = [(61, 63, 8), (81, 71, 7), (97, 35, 6)]        # each hop further and smaller
STROKE = 6


def marks(dx: float = 0, dy: float = 0) -> str:
    points = [START, *HOPS]
    line = "M" + " L".join(f"{x + dx} {y + dy}" for x, y, _ in points)
    nodes = "".join(f'<circle cx="{x + dx}" cy="{y + dy}" r="{r}" fill="{WHITE}"/>' for x, y, r in HOPS)
    x, y, r = START
    return (f'<path d="{line}" fill="none" stroke="{WHITE}" stroke-width="{STROKE}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>{nodes}'
            f'<circle cx="{x + dx}" cy="{y + dy}" r="{r}" fill="{GREEN}"/>')


def svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="Ripple">
  <title>Ripple</title>
  <rect width="128" height="128" rx="28" fill="{BLACK}"/>
  {marks()}
</svg>
"""


if __name__ == "__main__":
    (HERE / "logo.svg").write_text(svg())
    print("Wrote", HERE / "logo.svg")
