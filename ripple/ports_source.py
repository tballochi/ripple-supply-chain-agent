"""Real port positions, from open data: writes data/ports.csv.

Run once (needs internet):  python -m ripple.ports_source

The generator reads the committed CSV, so the setup itself stays offline and
every run builds the same graph. Each port is pinned to one record:

  - Wikidata (CC0): the item of the port itself ("Port of Rotterdam",
    found by its UN/LOCODE, property P1937), not the city.
  - Natural Earth ports (public domain, derived from the World Port Index):
    for the ports Wikidata only knows as a city.

The record id is written next to the coordinates, so every position can be
checked by hand: https://www.wikidata.org/wiki/<id>.
"""

import csv
import json
import re
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "ports.csv"
USER_AGENT = "ripple-supply-chain-demo/1.0 (open-data port positions)"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
NATURAL_EARTH = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                 "v5.1.2/geojson/ne_10m_ports.geojson")

# code -> (source, record): a Wikidata item, or a Natural Earth port name.
SOURCES = {
    "CNSHA": ("Natural Earth", "Shanghai"),
    "CNNGB": ("Wikidata", "Q1703245"),     # Port of Ningbo-Zhoushan
    "CNSZX": ("Natural Earth", "Yantian"),  # Shenzhen's main container port
    "HKHKG": ("Natural Earth", "Hong Kong"),
    "KRPUS": ("Wikidata", "Q12438381"),    # Port of Busan
    "JPTYO": ("Wikidata", "Q1139888"),     # Port of Tokyo
    "TWKHH": ("Wikidata", "Q713449"),      # Port of Kaohsiung
    "SGSIN": ("Wikidata", "Q1421994"),     # Port of Singapore
    "VNSGN": ("Wikidata", "Q1076388"),     # Saigon Port
    "MYPKG": ("Wikidata", "Q11155122"),    # Port Klang
    "THLCH": ("Natural Earth", "Laem Chabang"),
    "LKCMB": ("Natural Earth", "Colombo"),
    "INNSA": ("Wikidata", "Q1984452"),     # Nhava Sheva
    "AEJEA": ("Wikidata", "Q509588"),      # Port of Jebel Ali
    "EGPSD": ("Natural Earth", "Port Said"),
    "NLRTM": ("Wikidata", "Q1027807"),     # Port of Rotterdam
    "BEANR": ("Wikidata", "Q662529"),      # Port of Antwerp
    "DEHAM": ("Wikidata", "Q3964"),        # Port of Hamburg
    "DEBRV": ("Natural Earth", "Bremerhaven"),
    "FRLEH": ("Wikidata", "Q1129891"),     # Port of Le Havre
    "GBFXT": ("Wikidata", "Q3398484"),     # Port of Felixstowe
    "ESVLC": ("Wikidata", "Q2069059"),     # Port of Valencia
    "ESALG": ("Natural Earth", "Algeciras"),
    "ITGOA": ("Wikidata", "Q1515803"),     # Port of Genoa
    "GRPIR": ("Wikidata", "Q82310"),       # Port of Piraeus
    "MAPTM": ("Wikidata", "Q518888"),      # Tanger-Med
    "USLAX": ("Wikidata", "Q1308991"),     # Port of Los Angeles
    "USNYC": ("Wikidata", "Q1995529"),     # Port of New York and New Jersey
    "USSAV": ("Wikidata", "Q7231261"),     # Port of Savannah
    "BRSSZ": ("Wikidata", "Q16460"),       # Port of Santos
}


def from_wikidata(items: list[str]) -> dict:
    query = ("SELECT ?item ?coord WHERE { VALUES ?item { "
             + " ".join(f"wd:{q}" for q in items) + " } ?item wdt:P625 ?coord }")
    reply = requests.get(WIKIDATA_SPARQL, params={"query": query, "format": "json"},
                         headers={"User-Agent": USER_AGENT}, timeout=60)
    reply.raise_for_status()
    found = {}
    for row in reply.json()["results"]["bindings"]:
        lon, lat = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", row["coord"]["value"]).groups()
        found.setdefault(row["item"]["value"].rsplit("/", 1)[1], (float(lat), float(lon)))
    return found


def from_natural_earth(names: list[str]) -> dict:
    reply = requests.get(NATURAL_EARTH, headers={"User-Agent": USER_AGENT}, timeout=60)
    reply.raise_for_status()
    found = {}
    # The most important entry wins when a name appears twice (Piraeus has three).
    features = sorted(json.loads(reply.text)["features"], key=lambda f: -(f["properties"]["natlscale"] or 0))
    for feature in features:
        name = feature["properties"]["name"]
        if name in names and name not in found:
            lon, lat = feature["geometry"]["coordinates"]
            found[name] = (lat, lon)
    return found


def main() -> None:
    wikidata = from_wikidata([r for s, r in SOURCES.values() if s == "Wikidata"])
    natural_earth = from_natural_earth([r for s, r in SOURCES.values() if s == "Natural Earth"])
    rows = []
    for code, (source, record) in SOURCES.items():
        lat, lon = (wikidata if source == "Wikidata" else natural_earth)[record]
        rows.append({"code": code, "latitude": round(lat, 4), "longitude": round(lon, 4),
                     "source": source, "record": record})
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} ports to {OUT}")


if __name__ == "__main__":
    main()
