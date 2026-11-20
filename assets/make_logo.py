"""Draw the Ripple logo: python assets/make_logo.py  (writes logo.svg)

Three waves on a 128 grid: the first in green (the disruption), the next two
fading to white and grey as the ripple travels. Same stroke, same period and
the same height for each wave, centred on the tile. logo.png (the browser tab
icon) is rendered from the SVG with headless Chrome.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
GREEN, WHITE, GREY, BLACK = "#3BD671", "#FFFFFF", "#6B6B6B", "#000000"
LEFT, PERIOD, AMPLITUDE, STROKE = 28, 18, 10, 8   # four half-periods from x=28 to x=100
ROWS = [(44, GREEN), (66, WHITE), (88, GREY)]       # baseline y of each wave, top to bottom


def wave(y: float) -> str:
    """One wave: a quadratic curve, then smooth repeats of it."""
    return f"M{LEFT} {y} q{PERIOD / 2:g} {-AMPLITUDE} {PERIOD} 0" + f" t{PERIOD} 0" * 3


def waves() -> str:
    return "".join(f'<path d="{wave(y)}" stroke="{colour}"/>' for y, colour in ROWS)


def svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="Ripple">
  <title>Ripple</title>
  <rect width="128" height="128" rx="28" fill="{BLACK}"/>
  <g fill="none" stroke-width="{STROKE}" stroke-linecap="round">{waves()}</g>
</svg>
"""


if __name__ == "__main__":
    (HERE / "logo.svg").write_text(svg())
    print("Wrote", HERE / "logo.svg")
