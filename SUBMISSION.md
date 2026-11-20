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

**One message, said three times:** a port closes; the graph finds 29 late shipments, plain RAG on
the same data finds 1. Everything else in the video supports that sentence.

Before recording: open <https://ripple-supply-chain.streamlit.app> (or `streamlit run app.py`) a
few minutes early so it is awake, zoom the browser to 110 %, close other tabs, collapse nothing.
In LLM mode leave about 20 seconds between questions (Groq's free tier allows 8,000 tokens a
minute); in rule-based mode everything is instant.

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:12 | Home page, the title | "When a port closes, the question is who is hit three hops later: which vessels, whose cargo, which customers. That answer is not written in any document. It is in the relationships." |
| 0:12 to 0:30 | Click **Port of Rotterdam closed for 3 days**. The verdict card. | "Ripple walks a Relate graph: 29 shipments late, 26 customers, $5.8 million of cargo later than they tolerate. And on the same data, plain RAG finds one." |
| 0:30 to 0:45 | **Graph vs plain RAG** tab | "That is the whole point. Every record turned into a document, the same word and meaning search: 1 shipment out of 29, 0 of the 9 customers hit through their suppliers. Retrieval finds the start; relationships find the consequences." |
| 0:45 to 0:58 | **Impact** tab, **Impact map** | "One closure in Rotterdam, late cargo landing in eleven countries. In green, the way out." |
| 0:58 to 1:10 | **Mitigation** tab, Hamburg preselected, **Save this plan** | "Divert to Hamburg: 13 shipments rescued, $2.9 million protected. I keep the plan; it is written back to the graph." |
| 1:10 to 1:22 | Open **Under the hood** | "No number here comes from the language model. Three Cypher queries on Relate, a few milliseconds, and a command to replay each one with Relate's own CLI." |
| 1:22 to 1:38 | Type **the ransomware attack in Korea** | "No port in the question. Hybrid search finds the news alert, the alert mentions Busan, the graph does the rest: 13 shipments late. Plain RAG: none." |
| 1:38 to 1:50 | Sidebar: **Network weak points** | "Before anything happens: every port closed in turn, 91 queries in a fraction of a second. Rotterdam is the weakest link." |
| 1:50 to 2:00 | Home, **Live news** | "And it reads today's real news. Ripple, on Relate. Thanks." |

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
