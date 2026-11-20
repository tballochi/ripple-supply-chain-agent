"""Ripple web UI.  Run with:  streamlit run app.py

The page only displays what ripple/agent.py returns: the explanation, the
ranked list of impacted shipments, and for each one the graph path that
explains it. No analysis logic lives here.
"""

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ripple import agent, db, live, llm, mitigation, plain_rag, queries, radar, viz, workspace
from ripple.generate import SCENARIO_DATE

EXAMPLES = [
    "Port of Rotterdam closed for 3 days",
    "Typhoon near Shanghai, terminals shut for 5 days",
    "The ransomware attack in Korea",
    "A ship is stuck at the entrance of the Suez canal for a week",
    "MV Silver Spirit is out of service for 4 days",
]
COLORS = viz.COLORS

ASSETS = Path(__file__).resolve().parent / "assets"
st.set_page_config(page_title="Ripple", page_icon=str(ASSETS / "logo.png"), layout="wide")

# On Streamlit Community Cloud the API keys come from the app's Secrets
# instead of a .env file. Without any key the app runs in rule-based mode.
try:
    for name in ("GROQ_API_KEY", "MISTRAL_API_KEY", "RIPPLE_LLM_PROVIDER"):
        if name in st.secrets:
            os.environ.setdefault(name, str(st.secrets[name]))
except Exception:  # no secrets file at all: nothing to copy
    pass


@st.cache_data(max_entries=50, show_spinner=False)
def run_agent(question: str, use_llm: bool, previous: str = "") -> dict:
    # Cached per question: Streamlit re-runs the whole page on every click
    # (picking a fallback port, moving a slider), and without the cache each
    # click would call the LLM again and hit the free tier's rate limit.
    # A Relate connection belongs to the thread that opened it, and Streamlit
    # may run each interaction on a different thread: open one per question.
    conn = db.connect()
    try:
        return agent.answer(conn, question, use_llm=use_llm,
                            previous=json.loads(previous) if previous else None, remember=True)
    finally:
        conn.close()


def run_comparison(question: str, results: list, k: int) -> dict:
    conn = db.connect()
    try:
        return plain_rag.compare(conn, question, results, k)
    finally:
        conn.close()


def show_comparison(question: str, results: list) -> None:
    st.markdown("Same data, same question. **Plain RAG** turns every record (shipments, vessels, "
                "routes, customers, ports, news) into a text document and retrieves the closest "
                "ones with the same word + meaning search. **Ripple** walks the relationships.")
    k = st.select_slider("Documents plain RAG retrieves (top k)", [5, 10, 20, 50], value=10)
    cmp = run_comparison(question, results, k)
    g, r = cmp["graph"], cmp["plain_rag"]
    st.dataframe(pd.DataFrame([
        {"": "Delayed shipments found", "Ripple (graph)": g["shipments"], "Plain RAG": r["shipments_found"]},
        {"": "Shipments named but not delayed", "Ripple (graph)": 0, "Plain RAG": r["shipments_wrong"]},
        {"": "Affected customers found", "Ripple (graph)": g["customers"], "Plain RAG": r["customers_found"]},
        {"": "Customers reached via suppliers", "Ripple (graph)": g["second_order_customers"],
         "Plain RAG": r["second_order_found"]},
        {"": "Answers explained by a path", "Ripple (graph)": g["paths"], "Plain RAG": r["paths"]},
    ]), hide_index=True, width="stretch")
    missed = cmp["missed_shipments"]
    if missed:
        by_id = {row["shipment"]: row for res in results for row in res["impacted"]}
        example = by_id[missed[0]]
        st.markdown(f"**Missed by plain RAG ({len(missed)}):** for example {example['shipment']} "
                    f"for {example['customer']}. No single document links it to the disruption; "
                    "the graph does, in several hops:")
        st.code(example["path"], language=None)
    with st.expander(f"The {k} documents plain RAG retrieved ({cmp['mode']} search)"):
        for d in cmp["documents"]:
            st.markdown(f"- `{d['kind']}` {d['text']}")


@st.cache_data
def graph_names() -> dict:
    """Port and vessel names for the scenario builder."""
    conn = db.connect()
    try:
        return {"ports": [r["n"] for r in conn.execute("MATCH (p:Port) RETURN p.name AS n ORDER BY n")],
                "vessels": [r["n"] for r in conn.execute("MATCH (v:Vessel) RETURN v.name AS n ORDER BY n")]}
    finally:
        conn.close()


@st.cache_data
def graph_stats() -> dict:
    conn = db.connect()
    try:
        nodes = {r["label"]: r["n"] for r in conn.execute(
            "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label")}
        rels = conn.execute("MATCH ()-[r]->() RETURN count(r) AS n").fetchone()["n"]
    finally:
        conn.close()
    return {"nodes": nodes, "relationships": rels}


def show_result(result: dict, key: str) -> None:
    d, s = result["disruption"], result["summary"]
    what = "closed" if d["kind"] == "port_closure" else "out of service"
    st.subheader(f"{d['name']} {what} for {d['days']} days")

    cols = st.columns(5)
    cols[0].metric("Shipments late", s["shipments"])
    cols[1].metric("Customers affected", s["customers"])
    cols[2].metric("Beyond tolerance", s["sla_breaches"])
    cols[3].metric("Cargo value", agent.money(s["value_at_risk_usd"]))
    cols[4].metric("Customers via suppliers", s["downstream_customers"])

    impacted = result["impacted"]
    if not impacted:
        st.info("No vessel in the graph is scheduled to call there during that window.")
        return

    tab_list, tab_graph, tab_downstream, tab_mitigation = st.tabs(
        ["Impacted shipments", "Impact graph", "Ripple effect",
         "Mitigation" if d["kind"] == "port_closure" else "Alternatives"])

    with tab_list:
        table = pd.DataFrame([{
            "Score": r["score"], "Shipment": r["shipment"], "Customer": r["customer"],
            "Tier": r["tier"], "Priority": r["priority"], "Delay (days)": r["delay_days"],
            "ETA": r["eta"], "New ETA": r["new_eta"],
            "Beyond tolerance": "yes" if r["sla_breached"] else "no",
            "Cargo value": f"${r['value_usd']:,}", "Vessel": r["vessel"],
        } for r in impacted])
        st.dataframe(table, hide_index=True, width="stretch")

        st.markdown("**Why is a shipment impacted? Pick one to see the path the agent followed.**")
        labels = [f"{r['shipment']}  ·  {r['customer']}  ·  +{r['delay_days']}d" for r in impacted]
        choice = st.selectbox("Shipment", range(len(impacted)), format_func=lambda i: labels[i],
                              key=f"pick-{key}", label_visibility="collapsed")
        row = impacted[choice]
        st.graphviz_chart(viz.path_to_dot([(row["path_nodes"], row["path_rels"])]))
        st.code(row["path"], language=None)
        left, right = st.columns(2)
        left.markdown(
            f"- **Reason:** {row['reason']}\n"
            f"- **Route:** {row['route']} ({row['origin']} to {row['destination']})\n"
            f"- **Cargo:** {', '.join(row['products'])}")
        alt = row["alternative"]
        alt_text = "none within range"
        if alt:
            alt_text = f"{alt['name']} ({alt['km']} km away" + (
                ", already on this vessel's route)" if alt["on_same_route"] else ", needs a detour)")
        right.markdown(
            f"- **Customer tolerance:** {row['sla_days']} days, delay is {row['delay_days']}\n"
            f"- **Score:** {row['score']} = delay x priority x tier"
            f"{' x 2 (beyond tolerance)' if row['sla_breached'] else ''}\n"
            f"- **Fallback port:** {alt_text}")

    with tab_graph:
        count = len(impacted)
        if count > 3:  # a slider needs a real range
            count = st.slider("Shipments shown (highest score first)", 3, min(30, count),
                              min(12, count), key=f"n-{key}")
        shown = impacted[:count]
        ids = {r["shipment"] for r in shown}
        paths = [(r["path_nodes"], r["path_rels"]) for r in shown]
        paths += [(r["path_nodes"], r["path_rels"]) for r in result["downstream"] if r["via_shipment"] in ids]
        if st.toggle("Interactive view (drag, zoom, click a node)", value=True, key=f"vis-{key}",
                     help="Loads the vis-network library from a CDN; turn off to work offline."):
            components.html(viz.path_to_vis_html(paths), height=560)
        else:
            st.graphviz_chart(viz.path_to_dot(paths), width="stretch")
        legend = " &nbsp; ".join(f'<span style="color:{color}">&#9632;</span> {label}'
                                 for label, color in COLORS.items())
        st.markdown(f"One disruption on the left, every customer it reaches on the right. "
                    f"&nbsp; {legend}", unsafe_allow_html=True)

    with tab_downstream:
        if result["downstream"]:
            st.markdown("Companies supplied by a customer whose delivery is later than it tolerates, "
                        "followed up to 3 supplier tiers with a variable-length path "
                        "(`-[:SUPPLIES*1..3]->`).")
            st.dataframe(pd.DataFrame([{
                "Customer": r["customer"], "Tier": r["tier"], "Supplier tiers away": r["supplier_hops"],
                "Supplied by": r["via_customer"], "Late shipment": r["via_shipment"],
                "Exposure (days)": r["delay_days"], "Path": r["path"],
            } for r in result["downstream"]]), hide_index=True, width="stretch")
        else:
            st.info("No ripple effect: no late customer supplies another company.")

    with tab_mitigation:
        if result["alternatives"]:
            show_mitigation(result, key)
        elif d["kind"] == "port_closure":
            st.info("No alternative port within range in the graph.")
        else:
            st.info("A vessel outage has no fallback port to simulate.")


def run_diversion(result: dict, fallback: str) -> dict:
    conn = db.connect()
    try:
        d = result["disruption"]
        return mitigation.simulate_diversion(conn, d["code"], fallback, d["days"], result)
    finally:
        conn.close()


def show_mitigation(result: dict, key: str) -> None:
    alternatives = result["alternatives"]
    best = result.get("best_diversion")
    codes = [a["code"] for a in alternatives]
    default = codes.index(best["fallback"]["code"]) if best else 0
    names = {a["code"]: f"{a['name']} ({a['km']} km, " + (
        f"shares route(s) {', '.join(a['shared_routes'])})" if a["shared_routes"] else "on none of the same routes)")
             for a in alternatives}
    best_code = best["fallback"]["code"] if best else None
    fallback = st.selectbox("Divert the impacted vessels to", codes, index=default,
                            format_func=lambda c: names[c] + ("  ★ best" if best and c == best_code else ""),
                            key=f"fallback-{key}")
    sim = run_diversion(result, fallback)
    b, a = sim["before"], sim["after"]
    cols = st.columns(4)
    cols[0].metric("Late after diversion", a["shipments_late"], a["shipments_late"] - b["shipments_late"],
                   delta_color="inverse")
    cols[1].metric("Delay days after", a["delay_days"], a["delay_days"] - b["delay_days"],
                   delta_color="inverse")
    cols[2].metric("Beyond tolerance after", a["sla_breaches"], a["sla_breaches"] - b["sla_breaches"],
                   delta_color="inverse")
    cols[3].metric("Value protected", agent.money(sim["value_protected_usd"]))
    st.markdown(f"**{sim['shipments_rescued']} shipments rescued** by diverting to "
                f"{sim['fallback']['name']}; extra distance: {sim['extra_sea_km']:,} km at sea and "
                f"{sim['extra_road_km']:,} km by road or feeder. Before: {b['shipments_late']} late, "
                f"{b['sla_breaches']} beyond tolerance.")
    if sim["shipments_rescued"] and st.button("Save this plan to the decision log", key=f"save-{key}",
                                              help="Writes a Plan node into the workspace graph, linked to "
                                                   "both ports and to every shipment it rescues."):
        plan_id = workspace.save_plan(sim, st.session_state.get("question", ""))
        st.success(f"Saved {plan_id}: divert {sim['closed']['name']} to {sim['fallback']['name']}. "
                   "It is in the decision log on the home page.")
    st.dataframe(pd.DataFrame([{
        "Shipment": r["shipment"], "Customer": r["customer"], "Delay before": r["delay_before"],
        "Delay after": r["delay_after"], "Tolerance": r["sla_days"],
        "Beyond tolerance after": "yes" if r["breach_after"] else "no", "How": r["how"],
    } for r in sim["shipments"]]), hide_index=True, width="stretch")
    st.caption("Model: no sea detour if the fallback is already on the vessel's route, otherwise "
               f"{mitigation.SEA_KM_PER_DAY} km/day plus a day in port; cargo loaded or unloaded at the "
               f"closed port goes by truck or feeder at {mitigation.LAND_KM_PER_DAY} km/day up to "
               f"{mitigation.MAX_TRANSFER_KM} km; a shipment is diverted "
               "only when that is faster than waiting.")


# ------------------------------------------------------------------- sidebar
with st.sidebar:
    # The logo (assets/make_logo.py) inlined as SVG so it stays sharp.
    logo = base64.b64encode((ASSETS / "logo.svg").read_bytes()).decode()
    st.markdown(f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:.4rem">'
                f'<img src="data:image/svg+xml;base64,{logo}" width="56" alt="">'
                f'<span style="font-size:2rem;font-weight:700">Ripple</span></div>',
                unsafe_allow_html=True)
    st.caption("Supply chain disruption agent on a Relate graph")
    if llm.available():
        use_llm = st.toggle(f"Use LLM ({llm.provider()})", value=True)
    else:
        use_llm = False
        st.info("No API key found: running in rule-based mode. "
                "Add a Groq or Mistral key to `.env` to enable the LLM.")
    with st.expander("Build a scenario", expanded=False), st.form("scenario", border=False):
        kind = st.radio("What is disrupted?", ["Port closure", "Vessel outage"], horizontal=True)
        names = graph_names()
        target = st.selectbox("Port or vessel", names["ports"] if kind == "Port closure" else names["vessels"])
        days = st.slider("Duration (days)", 1, 14, 3)
        start = st.date_input("Starting on", value=SCENARIO_DATE, min_value=SCENARIO_DATE,
                              max_value=SCENARIO_DATE + timedelta(days=6),
                              help="The graph holds the vessels' current voyages, so the later the "
                                   "start, the fewer vessels are scheduled.")
        if st.form_submit_button("Run scenario", width="stretch"):
            what = f"Port of {target} closed" if kind == "Port closure" else f"{target} out of service"
            st.session_state["question"] = f"{what} for {days} days from {start.isoformat()}"
            st.session_state["history"] = []  # a new scenario, not a follow-up
    st.markdown("**Try an example**")
    for example in EXAMPLES:
        if st.button(example, width="stretch"):
            st.session_state["question"] = example
            st.session_state["history"] = []
    stats = graph_stats()
    st.markdown("**The graph**")
    st.caption(" · ".join(f"{n} {label}s" for label, n in stats["nodes"].items())
               + f" · {stats['relationships']} relationships. The ports and their positions "
                 "are real (Wikidata, Natural Earth); vessels, shipments and customers are synthetic. "
                 "The scenario's \"today\" is 1 December 2026.")

# ---------------------------------------------------------------------- main
st.header("What happens if...?")
# A link like  /?q=Port+of+Rotterdam+closed  opens the page with an answer.
if "question" not in st.session_state and st.query_params.get("q"):
    st.session_state["question"] = st.query_params["q"]
question = st.text_input("Describe a disruption in plain English, then ask follow-ups "
                         "(\"and if it lasts a week?\", \"what about Antwerp instead?\")", key="question",
                         placeholder="Port of Rotterdam closed for 3 days")

@st.cache_data
def radar_rows() -> list:
    conn = db.connect()
    try:
        return radar.scan(conn)
    finally:
        conn.close()


def ask(question: str) -> None:
    """Button callback: run a question as a new scenario."""
    st.session_state["history"] = []
    st.session_state["question"] = question


@st.cache_data(ttl=1800, show_spinner="Reading today's news (GDACS, Google News)...")
def live_rows(day: str) -> tuple[list, list]:
    """Fetch real events (at most every 30 minutes) and simulate them on the graph."""
    conn = db.connect()
    try:
        problems = live.refresh(conn)
        return live.scan(conn), problems
    finally:
        conn.close()


def show_radar() -> None:
    mode = st.segmented_control("News source", ["Scenario news", "Live news"], default="Scenario news",
                                key="radar_mode", label_visibility="collapsed")
    if mode == "Live news":
        try:
            rows, problems = live_rows(datetime.now(UTC).date().isoformat())
        except Exception as error:  # the network or the workspace: never break the page
            rows, problems = [], [f"live mode unavailable ({error.__class__.__name__})"]
        rows = [r for r in rows if r["shipments"]]
        st.subheader(f"Live risk radar, {datetime.now(UTC):%d %B %Y}")
        st.caption("Real events of the last 3 days from GDACS (cyclones, earthquakes, floods) and "
                   "Google News (strikes, closures, cyber incidents) that touch a port of the graph. The "
                   "ports and their positions are real; the closure is simulated on Ripple's synthetic "
                   f"vessels and shipments as of {SCENARIO_DATE:%d %B %Y}.")
        for problem in problems:
            st.caption(f"Skipped: {problem}. Showing the news fetched earlier, if any.")
        if not rows:
            st.info("No real event touches a port of the graph right now.")
    else:
        rows = [r for r in radar_rows() if r["shipments"]]
        st.subheader(f"Risk radar, {SCENARIO_DATE:%d %B %Y}")
        st.caption("Before you ask: every serious news alert of the last 3 days that names a port, "
                   "with what is left of it simulated on the graph, ranked by the cargo that would arrive "
                   "later than customers tolerate.")
    for i, r in enumerate(rows[:6]):
        with st.container(border=True):
            left, middle, right = st.columns([5, 4, 1.4])
            if "headlines" in r:
                more = f" · {r['articles']} articles" if r["articles"] > 1 else ""
                source = f"[{r['source']}]({r['headlines'][0]['url']})" if r["headlines"][0]["url"] else r["source"]
                left.markdown(f"**{', '.join(r['port_names'])}** · {r['severity']} · {r['date']:%d %b} · "
                              f"{source}{more}  \n{r['text']}")
            else:
                left.markdown(f"**{', '.join(r['port_names'])}** · {r['severity']} · {r['date']:%d %b}  \n"
                              f"{r['text']}")
            middle.markdown(f"**{agent.money(r['value_beyond_tolerance_usd'])}** beyond tolerance  \n"
                            f"{r['shipments']} shipments late, {r['customers']} customers, "
                            f"{r['ripple_customers']} via suppliers, "
                            + (f"simulated for {r['days_total']} day(s)" if "headlines" in r
                               else f"{r['days_remaining']} day(s) left"))
            right.button("Analyze", key=f"radar-{mode}-{i}", on_click=ask, args=(r["question"],), width="stretch")


def show_decision_log() -> None:
    try:
        plans = workspace.list_plans()
    except Exception as error:  # the workspace is optional: never break the page
        st.caption(f"Decision log unavailable ({type(error).__name__}).")
        return
    if not plans:
        return
    st.subheader("Decision log")
    st.caption("Diversions you kept, stored as Plan nodes in the workspace graph and linked to the "
               "ports and the shipments they rescue.")
    st.dataframe(pd.DataFrame([{
        "Plan": p["id"], "Saved": f"{p['created_at']:%d %b %H:%M}", "Divert": f"{p['closed']} → {p['fallback']}",
        "Days": p["days"], "Shipments rescued": p["shipments_rescued"],
        "Breaches avoided": p["breaches_avoided"], "Value protected": agent.money(p["value_protected_usd"]),
        "Customers protected": ", ".join(p["customers_protected"]),
    } for p in plans]), hide_index=True, width="stretch")
    if st.button("Clear the decision log and the agent's memory"):
        workspace.clear()
        st.rerun()


def new_scenario() -> None:
    st.session_state["history"] = []
    st.session_state["question"] = ""


if question:
    # The conversation so far: a follow-up ("and if it lasts a week?") reuses
    # the plan of the previous question.
    history = st.session_state.setdefault("history", [])
    if history and history[-1]["question"] == question:  # same question, page re-run
        previous = history[-2] if len(history) > 1 else None
    else:
        previous = history[-1] if history else None
    with st.spinner("Walking the graph..."):
        out = run_agent(question, use_llm, json.dumps(previous, default=str) if previous else "")
    if not history or history[-1]["question"] != question:
        history.append({"question": question, "plan": json.loads(json.dumps(out["plan"], default=str))})

    if out["plan"].get("follow_up_of"):
        left, right = st.columns([4, 1])
        left.caption(f"↪ Follow-up of “{out['plan']['follow_up_of']}”: same scenario, with what you changed.")
        right.button("New scenario", on_click=new_scenario, width="stretch")

    st.markdown(out["explanation"])
    if out.get("data_answer") and len(out["data_answer"]["rows"]) > 10:
        with st.expander(f"All {len(out['data_answer']['rows'])} rows"):
            st.dataframe(pd.DataFrame(out["data_answer"]["rows"]), hide_index=True, width="stretch")
    with st.expander("How the agent got there"):
        for step in out["steps"]:
            st.markdown(f"- {step}")
        if out["plan"]["reasoning"]:
            st.markdown(f"- LLM reasoning: {out['plan']['reasoning']}")
        alerts = out["retrieval"]["alerts"]
        if alerts:
            st.markdown("**Related news alerts** (ranked by fusing a word search and a meaning search)")
            st.dataframe(pd.DataFrame([{
                "Fused score": a["rrf"], "Rank by meaning": a["vector_rank"], "Rank by words": a["fulltext_rank"],
                "Alert": a["text"], "Mentions": ", ".join(p["name"] for p in a["ports"]),
            } for a in alerts]), hide_index=True, width="stretch")

    if out["results"]:
        tab_impact, tab_compare = st.tabs(["Impact", "Graph vs plain RAG"])
        with tab_impact:
            if len(out["results"]) > 1:
                c = queries.combine(out["results"])
                st.subheader(f"Combined: {len(out['results'])} disruptions at once")
                cols = st.columns(5)
                cols[0].metric("Unique shipments late", c["shipments"])
                cols[1].metric("Unique customers", c["customers"])
                cols[2].metric("Beyond tolerance (all)", c["sla_breaches"])
                cols[3].metric("Cargo value (all)", agent.money(c["value_at_risk_usd"]))
                cols[4].metric("Hit twice, counted once", c["double_counted"])
                st.divider()
            for index, result in enumerate(out["results"]):
                if index:
                    st.divider()
                show_result(result, key=str(index))
        with tab_compare:
            show_comparison(question, out["results"])
else:
    st.markdown("Ask about a port, a vessel, a country, or an incident from the news. "
                "Ripple finds every shipment and customer affected, several hops away, "
                "and shows the path it followed.")
    show_radar()
    show_decision_log()
