<p align="center"><img src="assets/logo.svg" width="128" alt="Ripple logo: a disruption rippling across a spider web"></p>

# Ripple

[![tests](https://github.com/tballochi/ripple-supply-chain-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/tballochi/ripple-supply-chain-agent/actions/workflows/tests.yml)

**Describe a supply chain disruption in plain English. Ripple walks a [Relate](https://relatedb.ai)
graph of ports, vessels, shipments and customers, finds everyone affected several hops away,
shows the exact path behind each answer, and simulates the best diversion.**

![Ripple demo: Rotterdam closed for 3 days](docs/demo.gif)

**Live demo:** _coming soon (Streamlit Community Cloud)_ · Built for the Relate by Neo4j Hackathon ·
All data is synthetic.

## Why a graph

"Port of Rotterdam closed for 3 days." The shipments that will be late are not the ones whose
documents mention Rotterdam. They are the ones on **vessels** sailing **routes** that call at
Rotterdam **during those 3 days**, still carrying cargo to Rotterdam **or a later port**. Then come
the **customers** waiting for that cargo, and the **companies they supply**, up to three supplier
tiers away. That is a 4 to 7 hop question.

Ripple answers the same question both ways, on the same data, in the **Graph vs plain RAG** tab.
Plain RAG gets every record (shipments, vessels, routes, customers, ports, news) as a text
document and the same hybrid word + meaning search, and retrieves the top 10:

| Question | | Delayed shipments | Affected customers | Customers via suppliers | Explained by a path |
|---|---|---:|---:|---:|---:|
| Port of Rotterdam closed for 3 days | **Ripple** | **29** | **26** | **9** | **29** |
| | plain RAG | 1 | 3 | 0 | 0 |
| The ransomware attack in Korea | **Ripple** | **13** | **12** | **9** | **13** |
| | plain RAG | 0 | 0 | 0 | 0 |
| Typhoon near Shanghai, terminals shut for 5 days | **Ripple** | **17** | **15** | **10** | **17** |
| | plain RAG | 1 | 1 | 0 | 0 |
| Storm in the North Sea for 2 days (5 ports) | **Ripple** | **34** | **29** | **7** | **34** |
| | plain RAG | 0 | 0 | 0 | 0 |
| MV Silver Spirit is out of service for 4 days | **Ripple** | **5** | **5** | **8** | **5** |
| | plain RAG | 5 | 5 | 0 | 0 |

The last row is the honest control: a vessel's shipments are one hop away, so plain RAG finds
them too. It still cannot reach the companies those customers supply, or explain why. Run it
yourself: `python -m ripple.plain_rag "Port of Rotterdam closed for 3 days"`.

### And retrieval itself is measured

`python -m ripple.evaluate` runs 33 questions with known answers through four set-ups. The vector
index is what finds incidents described without any port name; the full-text index keeps the app
above 90% when the embedding model is unavailable (that fallback is checked in CI):

| Set-up | Port or vessel named | Country, sea area, radius | News incident, no port named | Pasted headline | Off-topic (must find nothing) | **All** |
|---|---:|---:|---:|---:|---:|---:|
| names only | 5/5 | 5/5 | 3/12 | 0/5 | 6/6 | **19/33 (58%)** |
| + full-text index | 5/5 | 5/5 | 9/12 | 5/5 | 6/6 | **30/33 (91%)** |
| + vector index | 5/5 | 5/5 | 12/12 | 5/5 | 6/6 | **33/33 (100%)** |
| hybrid (Ripple) | 5/5 | 5/5 | 12/12 | 5/5 | 6/6 | **33/33 (100%)** |

## What it does

1. **Understands the question.** It matches ports, vessels and countries by name, sea areas and
   radii with geospatial queries ("typhoon in the South China Sea", "within 500 km of Singapore"),
   and news incidents with hybrid retrieval (full-text + vector in Relate), then follows
   `(Alert)-[:MENTIONS]->(Port)`. "The ransomware attack in Korea" names no port; the alert does.
2. **Walks the graph.** A Cypher query goes `Port <- Route <- Vessel <- Shipment -> Customer`,
   checks the dates and the order of port calls, and tells cargo **on board** from cargo
   **not loaded yet**. A variable-length path, `-[:SUPPLIES*1..3]->`, follows the ripple to the
   companies those customers supply. Several ports at once are combined, each shipment counted once.
3. **Ranks and explains.** Score = days late × priority × customer tier, doubled beyond the
   customer's tolerance. Every line comes with its path, e.g.
   `Rotterdam <-[CALLS_AT]- North Europe Feeder <-[SAILS]- MV Northern Breeze <-[ON_VESSEL]- S0138 -[FOR]-> Tessera Retail`.
4. **Simulates a mitigation.** Pick a nearby port (`NEAR`) and see before/after: Rotterdam →
   Hamburg rescues 13 shipments, avoids 8 of 14 tolerance breaches and protects $2.9M of cargo.
5. **Holds a conversation.** "And if it lasts a week?", "what about Antwerp instead?", "and
   Hamburg too?" reuse, replace or extend the previous scenario. A sidebar form builds a scenario
   (port or vessel, duration, start date) without typing.
6. **Works with or without an LLM.** With a free Groq key, the LLM picks the query and writes the
   explanation from the returned paths only (a shipment it invents is rejected). It also answers
   free questions about the data ("which customers buy sneakers?") with Cypher it writes, which
   is checked with `EXPLAIN` and refused unless read-only. Without a key, a deterministic
   rule-based mode gives the same disruption analysis.
7. **Shows the graph.** An interactive view (drag, zoom, click a node to see its neighbours) of
   everything a disruption reaches.
8. **Serves any agent over MCP.** The graph is exposed as 8 read-only tools.

## Architecture

```mermaid
flowchart LR
    Q["Question in plain English<br/>(or a follow-up)"] --> R["Retrieval<br/>names, sea areas (point.distance)<br/>hybrid search over alerts (full-text + vector, RRF)"]
    R --> P{"Plan<br/>LLM, rules or follow-up"}
    P -->|port_closure| G["Graph queries (Cypher)<br/>multi-hop impact + paths<br/>ripple via SUPPLIES*1..3"]
    P -->|vessel_outage| G
    P -->|free question| L["LLM-written Cypher<br/>checked with EXPLAIN, read-only"]
    L --> UI
    G --> M["Mitigation<br/>best diversion via NEAR + CALLS_AT"]
    M --> E["Explanation<br/>LLM grounded on paths, or rules"]
    E --> UI["Streamlit UI"]
    G --> B["Plain RAG baseline<br/>same data as text, top-k"]
    B --> UI
    DB[("Relate store<br/>data/ripple.relate")] --- R
    DB --- G
    DB --- MCP["MCP server<br/>8 read-only tools"]
    MCP --> A["Any MCP agent<br/>Claude Code, Cursor..."]
```

## Graph model

423 nodes, 1,536 relationships, generated by `ripple/generate.py` with a fixed seed.

```mermaid
flowchart LR
    Shipment["Shipment (200)"] -->|ON_VESSEL| Vessel["Vessel (40)"]
    Vessel -->|SAILS| Route["Route (14)"]
    Route -->|"CALLS_AT {seq, day} (75)"| Port["Port (30)<br/>location: point"]
    Port -->|"NEAR {km} (102)"| Port
    Shipment -->|ORIGIN / DESTINATION| Port
    Shipment -->|FOR| Customer["Customer (60)"]
    Customer -->|"SUPPLIES (72)"| Customer
    Shipment -->|"CONTAINS {qty} (397)"| Product["Product (25)"]
    Alert["Alert (54)"] -->|"MENTIONS (50)"| Port
```

## Setup (5 commands)

```bash
git clone https://github.com/tballochi/ripple-supply-chain-agent.git && cd ripple-supply-chain-agent
python3 -m venv .venv && source .venv/bin/activate      # Python 3.12 or 3.13
pip install -r requirements.txt
python -m ripple.embeddings --download                  # optional: ~70 MB model for search by meaning
streamlit run app.py
```

No database to start and no key needed: the Relate store is committed in `data/ripple.relate`.
For the LLM mode, `cp .env.example .env` and add a free Groq key (or a Mistral key).
To rebuild the data: `python -m ripple.generate`. To run the 138 tests: `python -m pytest`.

## Example questions

- `Port of Rotterdam closed for 3 days`
- `Typhoon near Shanghai, terminals shut for 5 days`
- `The ransomware attack in Korea` (no port named: found through a news alert)
- `A ship is stuck at the entrance of the Suez canal for a week`
- `MV Silver Spirit is out of service for 4 days`
- `Typhoon in the South China Sea`, `storm within 500 km of Singapore` (geography)
- `Hurricane in the Gulf of Mexico` (no port of the graph there: Ripple says so and names the closest)
- `Strike in the Netherlands` or `ports in China closed for 2 days` (country matching)
- Follow-ups: `and if it lasts a week?`, `what about Antwerp instead?`, `and Hamburg too?`
- With an LLM key: `which customers buy sneakers?`, `which strategic customers are in Germany?`

The same analysis from the terminal:

```bash
python -m ripple.agent "Port of Rotterdam closed for 3 days"
python -m ripple.mitigation Rotterdam Hamburg 3
python -m ripple.plain_rag "The ransomware attack in Korea"
python -m ripple.evaluate                     # retrieval scores
```

## How Relate is used

| Relate feature | Where |
|---|---|
| Embedded store, directory layout with the readable JSON codec, opened read-only by the app | `ripple/db.py`, `data/ripple.relate` |
| Uniqueness constraints (one per label, backing the key lookups) | `ripple/db.py` |
| Batch loading with `UNWIND $rows ... CREATE` | `ripple/generate.py` |
| Typed vectors: `vector(r.vector, 384, FLOAT32)` | `ripple/generate.py` |
| `CREATE VECTOR INDEX` and `CREATE FULLTEXT INDEX` on alerts | `ripple/db.py` |
| `SEARCH ... IN (VECTOR INDEX / FULLTEXT INDEX ...) SCORE AS`, fused by reciprocal rank in `CALL () { ... UNION ALL ... }` | `ripple/retrieval.py` |
| Multi-hop pattern with a path variable, `nodes(p)`, `relationships(p)`, `startNode()` to return the explanation | `ripple/queries.py` |
| Variable-length path `-[:SUPPLIES*1..3]->` with `length(p)` for the ripple through suppliers | `ripple/queries.py` |
| Date arithmetic: `v.voyage_start + duration({days: call.day})`, `duration.inDays()` | `ripple/queries.py` |
| Spatial values `point({latitude, longitude})`, `CREATE POINT INDEX`, `point.distance()` | `ripple/generate.py`, `ripple/db.py`, `ripple/retrieval.py` |
| `EXPLAIN` to check LLM-written Cypher (syntax and read-only query type) before it runs | `ripple/lookup.py` |
| `COLLECT { ... }` and `EXISTS { ... }` subqueries | `ripple/queries.py`, `ripple/plain_rag.py`, `ripple/mitigation.py` |
| `CALL db.schema.nodeTypeProperties()` for the schema given to agents and the LLM | `ripple/mcp_server.py`, `ripple/lookup.py` |

### MCP

Register the server in any MCP client (a `.mcp.json` is included for Claude Code):

```json
{ "mcpServers": { "ripple": { "command": ".venv/bin/python", "args": ["-m", "ripple.mcp_server"] } } }
```

Tools: `analyze_disruption`, `port_closure_impact`, `vessel_outage_impact`, `simulate_diversion`,
`compare_with_plain_rag`, `search_alerts`, `get_schema`, `read_cypher`. All are read-only.
Relate also ships its own generic MCP server with the `relate` CLI
(`relate serve --mcp stdio --database data/ripple.relate --read-only`); Ripple's server adds the
domain tools on top.

## Project layout

```
ripple/generate.py     synthetic data + load into Relate
ripple/queries.py      multi-hop impact queries, paths, ranking
ripple/retrieval.py    free text -> ports / vessels (names, geography, hybrid alert search)
ripple/mitigation.py   diversion simulator
ripple/plain_rag.py    plain RAG baseline for the comparison
ripple/agent.py        understand -> query -> explain, LLM or rules, follow-ups
ripple/lookup.py       free questions: LLM-written, checked, read-only Cypher
ripple/evaluate.py     retrieval scores on 33 questions
ripple/viz.py          static and interactive graph drawings
ripple/mcp_server.py   MCP tools
app.py                 Streamlit UI
tests/                 138 tests, run in CI on every push
```

## Limitations and next steps

- **Synthetic data.** Real port names and coordinates, invented everything else. The scenario's
  "today" is fixed at 1 December 2026 so every run gives the same answers.
- **A deliberately simple delay model.** A vessel waits until the port reopens; no berth queues,
  no capacity, no knock-on congestion after reopening. Diversions use fixed speeds (800 km/day at
  sea, 500 km/day by road or feeder, transfers up to 600 km).
- **Current voyages only.** The graph holds the vessels' current voyages, so a closure starting
  later than early December finds fewer vessels scheduled.
- **Several disruptions at once** are combined with each shipment's largest delay, not the sum.
- **Next:** live AIS vessel positions, inventory buffers at customers, and writing the chosen
  mitigation back to the graph as a plan.

## AI tools used

- **The code, tests and documentation were written with [Claude Code](https://claude.com/claude-code)**
  (Anthropic), working under my direction milestone by milestone.
- **At runtime, optionally:** an LLM through the free tier of Groq (`openai/gpt-oss-120b`), or
  Mistral (`mistral-small-latest`), for planning, explanations and free questions.
- **Embeddings:** `BAAI/bge-small-en-v1.5`, run locally with fastembed.

## License

MIT, see [LICENSE](LICENSE).
