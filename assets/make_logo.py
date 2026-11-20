"""Draw the Ripple logo: python assets/make_logo.py  (writes logo.svg)

A drop falls into water and the rings spread: one event, effects that travel
outwards. logo.png (the browser tab icon) is rendered from the SVG with
headless Chrome.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
BLUE, INDIGO = "#3B82F6", "#6366F1"


def svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="Ripple">
  <title>Ripple</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{INDIGO}"/>
    </linearGradient>
  </defs>
  <rect width="128" height="128" rx="30" fill="url(#bg)"/>
  <path d="M64 16 C64 16 44 42 44 56 a20 20 0 0 0 40 0 C84 42 64 16 64 16Z" fill="#FFFFFF"/>
  <g fill="none" stroke="#FFFFFF" stroke-linecap="round">
    <ellipse cx="64" cy="98" rx="20" ry="5.5" stroke-width="5"/>
    <path d="M26 98 a38 11 0 0 0 76 0" stroke-width="4" stroke-opacity="0.6"/>
    <path d="M14 99 a50 15 0 0 0 100 0" stroke-width="3" stroke-opacity="0.3"/>
  </g>
</svg>
"""


if __name__ == "__main__":
    (HERE / "logo.svg").write_text(svg())
    print("Wrote", HERE / "logo.svg")
