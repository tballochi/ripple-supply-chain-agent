# Ripple

A supply chain disruption agent built on a [Relate](https://relatedb.ai) graph.
Describe a disruption in plain English and Ripple walks the graph of ports,
routes, vessels, shipments and customers to find who is affected, and shows
the exact path it followed.

Work in progress for the Relate by Neo4j Hackathon. Full README comes with the
final milestone.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m ripple.generate   # optional: the store is already in data/ripple.relate
```

## Try it

```bash
python -m ripple.queries Rotterdam 3          # port closed for 3 days
python -m ripple.queries "MV Silver Spirit" 4  # vessel out of service for 4 days
python -m ripple.retrieval "the ransomware attack in Korea"   # free text -> alert -> port
python -m pytest                               # run the checks
```

Each impacted shipment is printed with the graph path that explains it, e.g.
`Rotterdam <-[CALLS_AT]- North Europe Feeder <-[SAILS]- MV Amber Harbor <-[ON_VESSEL]- S0148 -[FOR]-> Kingsley Trading`.

All data is synthetic and produced by `ripple/generate.py` with a fixed seed.
