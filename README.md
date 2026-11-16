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

All data is synthetic and produced by `ripple/generate.py` with a fixed seed.
