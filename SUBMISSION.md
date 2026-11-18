# Submission kit

## 1. Devpost description (draft, under 400 words)

### Inspiration
When a port closes, the first question is never "what do the news say about Rotterdam?" but
"whose goods are on which ship, and who is waiting for them?". The answer is three to six hops
away from the event. That is a graph question, and a perfect test for connected context.

### What it does
Ripple takes a disruption in plain English ("Port of Rotterdam closed for 3 days", "the
ransomware attack in Korea") and walks a Relate graph of ports, routes, vessels, shipments,
products and customers. It lists every delayed shipment and affected customer, ranks them by
delay, priority and customer tier, and shows the exact path behind each answer. It follows one
more hop to buyers supplied by late manufacturers, then simulates diverting vessels to a nearby
port with before/after numbers. A "Graph vs plain RAG" tab answers the same question with
top-k retrieval over the same data written as text: for Rotterdam, 29 delayed shipments versus 1.

### How we built it
Python and the embedded Relate engine: a committed directory store, Cypher multi-hop patterns
with path variables, date arithmetic, COLLECT subqueries, and Relate's full-text and vector
indexes fused by reciprocal rank in a single SEARCH query. A local embedding model, an optional
free LLM (Groq or Mistral) that only chooses between fixed queries and writes from returned
paths, a deterministic no-LLM mode, a Streamlit UI and an MCP server with 8 read-only tools.
The code was written with Claude Code.

### Challenges we ran into
Making the comparison with plain RAG fair rather than a strawman: the baseline gets every record
as a document and the same hybrid search, and the vessel-outage case shows where it does well.
Also modelling cargo correctly: on board versus not loaded yet.

### Accomplishments that we're proud of
Every answer is explainable by a path. Every one of the 30 ports gives a real answer. 95 tests run
in CI, including one that regenerates the store and checks it matches the committed one.

### What we learned
Retrieval finds the starting point; relationships find the consequences. A news alert that names
no port still leads to the right customers through MENTIONS.

### What's next for Ripple
Live vessel positions, overlapping disruptions, inventory buffers at customers, and writing the
chosen mitigation back to the graph as a plan.

## 2. Demo video script (2 minutes)

Before recording: open the live app (or `streamlit run app.py`) so it is warm, zoom the browser to
110 %, and close other tabs.

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:12 | Empty app | "Ripple answers 'what happens if...' for a supply chain, on a Relate graph of 30 ports, 40 vessels, 200 shipments and 60 customers." |
| 0:12 to 0:40 | Click **Port of Rotterdam closed for 3 days**. Scroll the explanation. | "29 shipments are late, 26 customers. 14 are on board and wait with the ship, 15 are not loaded yet. Here is the path for the most exposed one: Rotterdam, the route, the vessel, the shipment, the customer." |
| 0:40 to 0:55 | **Impact graph** tab | "One closure, fanning out to every customer, and one more hop to the buyers those customers supply." |
| 0:55 to 1:15 | **Graph vs plain RAG** tab | "Same data, same question, written as documents for classic RAG: it finds 1 delayed shipment out of 29 and no second-order customer. The graph finds them because it follows relationships." |
| 1:15 to 1:30 | **Impact** tab, then **Mitigation**, Hamburg preselected | "Divert to Hamburg: 13 shipments rescued, 8 of 14 tolerance breaches avoided, $2.9M protected." |
| 1:30 to 1:50 | Click **The ransomware attack in Korea**, open **How the agent got there** | "No port in the question. Hybrid search finds the news alert, the alert MENTIONS Busan, and the graph does the rest: 13 shipments, 12 customers. Plain RAG: zero." |
| 1:50 to 2:00 | README with the MCP tools | "Everything is also an MCP server, so any agent can ask these questions. Thanks!" |

## 3. Checklist: what you do yourself

GitHub
- [ ] Check the **tests** badge is green on the README.
- [ ] Add the repo topics `relate` and `relate-neo4j-hackathon` (repo page → About → gear icon).
- [ ] Add a one-line repo description and the live demo URL in About.
- [ ] Keep the repo public until judging ends.

Live demo
- [ ] Deploy following [DEPLOY.md](DEPLOY.md).
- [ ] Replace the "Live demo: coming soon" line in the README with the URL, commit and push.
- [ ] Open the app the day judging starts so it is awake.

Video
- [ ] Record with the script above (QuickTime: File → New Screen Recording), under 2 minutes.
- [ ] Upload to YouTube as Public or Unlisted, check it plays logged out.

Devpost form
- [ ] Paste the description above (Inspiration ... What's next).
- [ ] Repo URL, video URL, live demo URL.
- [ ] Built with: `relate`, `python`, `cypher`, `streamlit`, `mcp`, `fastembed`, `groq`, `mistral`.
- [ ] Upload `docs/demo.gif` and the screenshots in `docs/` to the gallery.
- [ ] Confirm the "AI tools used" section is in the README (it is).
- [ ] Submit before **December 11, 2026, 6:00 PM PST**, then re-open the page to check it is
      saved.
