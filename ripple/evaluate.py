"""Measure retrieval: does the question land on the right ports or vessel?

Run:  python -m ripple.evaluate

Each question has the answer a person would expect. Four set-ups are
compared on the same questions:

  - names only:   port, vessel, country and sea-area names in the text, no alert search
  - + full-text:  plus the full-text index over the news alerts (shared words)
  - + vector:     plus the vector index over the news alerts (similar meaning)
  - hybrid:       both, fused by reciprocal rank (what Ripple uses)

A question counts as correct when the set of ports (or vessels) found is
exactly the expected one; for off-topic questions, when nothing is found.
"""

import os

from . import db, embeddings, retrieval

# (category, question, expected port codes or vessel names; empty = nothing)
QUESTIONS = [
    # The text names the port or vessel.
    ("named", "Port of Rotterdam closed for 3 days", {"NLRTM"}),
    ("named", "Typhoon near Shanghai, terminals shut for 5 days", {"CNSHA"}),
    ("named", "strike in Antwerp", {"BEANR"}),
    ("named", "Los Angeles port shut down", {"USLAX"}),
    ("named", "MV Silver Spirit is out of service for 4 days", {"MV Silver Spirit"}),
    # A country, a region or a sea area.
    ("place", "ports in China closed for 2 days", {"CNSHA", "CNNGB", "CNSZX"}),
    ("place", "strike in the Netherlands", {"NLRTM"}),
    ("place", "typhoon in the South China Sea", {"VNSGN", "HKHKG", "CNSZX"}),
    ("place", "storm in the North Sea", {"DEBRV", "NLRTM", "GBFXT", "DEHAM", "BEANR"}),
    ("place", "storm within 500 km of Singapore", {"SGSIN", "MYPKG"}),
    # An incident from the news, with no port named: only the alerts lead to it.
    ("incident", "the ransomware attack in Korea", {"KRPUS"}),
    ("incident", "hackers took down a terminal's computer systems", {"KRPUS"}),
    ("incident", "a ship is stuck at the canal entrance", {"EGPSD"}),
    ("incident", "a vessel ran aground and blocks the canal", {"EGPSD"}),
    ("incident", "Dutch dockers on strike", {"NLRTM"}),
    ("incident", "dock workers walked out over pay", {"NLRTM"}),
    ("incident", "the earthquake in Tokyo Bay", {"JPTYO"}),
    ("incident", "a strong quake shook the Japanese capital's harbour", {"JPTYO"}),
    ("incident", "the oil spill in the Strait of Gibraltar", {"ESALG", "MAPTM"}),
    ("incident", "oil leak halts ships near Gibraltar", {"ESALG", "MAPTM"}),
    ("incident", "Typhoon Mira", {"CNSHA", "CNNGB"}),
    ("incident", "a big storm is about to hit the Chinese coast near Yangshan", {"CNSHA", "CNNGB"}),
    # A fragment pasted from a news wire.
    ("headline", "northbound convoys suspended", {"EGPSD"}),
    ("headline", "Yangshan terminals will suspend operations", {"CNSHA", "CNNGB"}),
    ("headline", "quay walls damaged, berth inspections under way", {"JPTYO"}),
    ("headline", "terminal operating system knocked out, all gates closed", {"KRPUS"}),
    ("headline", "berthing delays of 24 to 36 hours", {"BRSSZ"}),
    # Off-topic or too vague: the right answer is nothing.
    ("off-topic", "what is the weather like today", set()),
    ("off-topic", "fuel prices", set()),
    ("off-topic", "how are my shipments doing", set()),
    ("off-topic", "strike", set()),
    ("off-topic", "port closed", set()),
    ("off-topic", "hello", set()),
]

SETUPS = {"names only": (), "+ full-text": ("fulltext",), "+ vector": ("vector",),
          "hybrid": ("vector", "fulltext")}


def found_set(result: dict) -> set:
    return {p["code"] for p in result["ports"]} | {v["name"] for v in result["vessels"]}


def run() -> dict:
    """{setup: {category: (correct, total)}} plus the misses of each setup."""
    has_model = embeddings.embed(["probe"]) is not None
    conn = db.connect()
    scores, misses = {}, {}
    try:
        for setup, modes in SETUPS.items():
            if "vector" in modes and not has_model:
                continue
            by_category, wrong = {}, []
            for category, question, expected in QUESTIONS:
                got = found_set(retrieval.resolve(conn, question, modes=modes))
                ok, total = by_category.get(category, (0, 0))
                by_category[category] = (ok + (got == expected), total + 1)
                if got != expected:
                    wrong.append((question, sorted(expected), sorted(got)))
            scores[setup], misses[setup] = by_category, wrong
    finally:
        conn.close()
    return {"scores": scores, "misses": misses, "has_model": has_model}


def as_markdown(report: dict) -> str:
    categories = list(dict.fromkeys(c for c, _, _ in QUESTIONS))
    header = "| Set-up | " + " | ".join(categories) + " | **All** |"
    lines = [header, "|---|" + "---:|" * (len(categories) + 1)]
    for setup, by_category in report["scores"].items():
        cells = [f"{by_category[c][0]}/{by_category[c][1]}" for c in categories]
        ok = sum(v[0] for v in by_category.values())
        total = sum(v[1] for v in by_category.values())
        lines.append(f"| {setup} | " + " | ".join(cells) + f" | **{ok}/{total} ({ok / total:.0%})** |")
    return "\n".join(lines)


if __name__ == "__main__":
    os.environ.pop("RIPPLE_NO_EMBEDDINGS", None)
    report = run()
    if not report["has_model"]:
        print("Embedding model unavailable: vector set-ups skipped "
              "(run `python -m ripple.embeddings --download`).\n")
    print(as_markdown(report))
    for setup, wrong in report["misses"].items():
        if wrong:
            print(f"\nMissed by {setup}:")
            for question, expected, got in wrong:
                print(f"  {question!r}: expected {expected or 'nothing'}, got {got or 'nothing'}")
