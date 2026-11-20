# Submission kit

## 1. Devpost description (draft, under 400 words)

### Inspiration
When a port closes, the first question is never "what do the news say about Rotterdam?" but
"whose goods are on which ship, and who is waiting for them?". The answer is three to six hops
away from the event: a graph question, and the test of connected context.

### What it does
Ripple takes a disruption in plain English ("Port of Rotterdam closed for 3 days", "the
ransomware attack in Korea") and walks a Relate graph of ports, routes, vessels, shipments and
customers. It draws the ripple on a world map, ranks every delayed shipment and affected customer,
shows the exact path behind each one, follows the ripple up to three supplier tiers, takes
follow-ups ("and if it lasts a week?") and simulates diverting vessels. A risk radar ranks today's
news, real events from GDACS and Google News included; a weak-points page closes every port in turn
to show where the network is fragile. A "Graph vs plain RAG" tab answers the same question with
top-k retrieval over the same data as text: for Rotterdam, 29 delayed shipments versus 1.

### How we built it
Python and the embedded Relate engine: multi-hop Cypher with path variables, variable-length
SUPPLIES chains, date arithmetic, point distances, COLLECT subqueries, and full-text and vector
indexes fused in one SEARCH query. Every answer lists the queries Relate ran, with a command to
replay them in Relate's CLI. Free questions get LLM-written Cypher, refused unless EXPLAIN says
read-only. An optional free LLM (Groq), a deterministic no-LLM mode, Streamlit and an MCP server
with 12 tools. The code was written with Claude Code.

### Challenges we ran into
Making the comparison with plain RAG fair rather than a strawman: the baseline gets every record
as a document and the same hybrid search, and the vessel-outage case shows where it does well.

### Accomplishments that we're proud of
Every answer is explainable by a path. Every one of the 30 ports gives a real answer. Retrieval is
measured on 33 questions (100% hybrid, 91% without the embedding model). 185 tests run in CI,
including one that regenerates the store and checks it matches the committed one.

### What we learned
Retrieval finds the starting point; relationships find the consequences.

### What's next for Ripple
Live vessel positions, inventory buffers at customers, and plans that update vessel schedules.

## 2. Demo video script (2 minutes)

Before recording: open the live app (or `streamlit run app.py`) so it is warm, zoom the browser to
110 %, and close other tabs. In LLM mode, leave about 20 seconds between questions (Groq's free
tier allows 8,000 tokens a minute); without a key, everything is instant.

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:15 | Home page: the **Risk radar** | "Before I ask anything, Ripple has read today's news and simulated it on a Relate graph of 30 ports, 40 vessels and 200 shipments. The Rotterdam strike is the worst: $5.8M of cargo late beyond tolerance." |
| 0:15 to 0:35 | Click **Analyze** on Rotterdam. Scroll the explanation. | "29 shipments late, 26 customers. 14 are on board, 15 not loaded yet. Here is the path for the most exposed one: Rotterdam, the route, the vessel, the shipment, the customer." |
| 0:35 to 0:50 | **Impact graph** tab, click Rotterdam, then a customer on the right | "One closure fanning out to every customer, and on to the companies they supply, up to two supplier tiers here." |
| 0:50 to 1:08 | **Graph vs plain RAG** tab | "Same data, same question, written as documents for classic RAG: 1 delayed shipment out of 29, none of the 9 customers reached through suppliers. The graph follows relationships." |
| 1:08 to 1:20 | **Mitigation** tab, Hamburg preselected, click **Save this plan** | "Divert to Hamburg: 13 shipments rescued, 8 of 14 tolerance breaches avoided, $2.9M protected. I keep it: it is written to the graph." |
| 1:20 to 1:32 | Type **and if it lasts a week?** | "A follow-up: same port, now 7 days, 39 shipments." |
| 1:32 to 1:50 | Click **The ransomware attack in Korea**, open **How the agent got there** | "No port in the question. Hybrid search finds the news alert, the alert MENTIONS Busan, and the graph does the rest: 13 shipments, 12 customers. Plain RAG: zero." |
| 1:50 to 2:00 | README with the MCP tools | "Everything is also an MCP server, so any agent can ask these questions. Thanks!" |

## 3. Checklist: what you do yourself

GitHub
- [ ] Check the **tests** badge is green on the README.
- [ ] Add the repo topics `relate` and `relate-neo4j-hackathon` (repo page → About → gear icon).
- [ ] Add a one-line repo description and the live demo URL in About.
- [ ] Keep the repo public until judging ends.

Live demo
- [x] Deploy following [DEPLOY.md](DEPLOY.md): <https://ripple-supply-chain.streamlit.app>
- [x] Replace the "Live demo: coming soon" line in the README with the URL, commit and push.
- [ ] Open the app the day judging starts so it is awake.

Video
- [ ] Record with the script above (QuickTime: File → New Screen Recording), under 2 minutes.
- [ ] Upload to YouTube as Public or Unlisted, check it plays logged out.

Devpost form
- [ ] Paste the description above (Inspiration ... What's next).
- [ ] Repo URL, video URL, live demo URL.
- [ ] Built with: `relate`, `python`, `cypher`, `streamlit`, `mcp`, `fastembed`, `groq`.
- [ ] Upload `docs/demo.gif` and the screenshots in `docs/` to the gallery.
- [ ] Confirm the "AI tools used" section is in the README (it is).
- [ ] Submit before **December 11, 2026, 6:00 PM PST**, then re-open the page to check it is
      saved.
