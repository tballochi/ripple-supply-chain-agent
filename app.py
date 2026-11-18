"""Ripple web UI.  Run with:  streamlit run app.py

The page only displays what ripple/agent.py returns: the explanation, the
ranked list of impacted shipments, and for each one the graph path that
explains it. No analysis logic lives here.
"""

import pandas as pd
import streamlit as st

from ripple import agent, db, llm, mitigation, plain_rag

EXAMPLES = [
    "Port of Rotterdam closed for 3 days",
    "Typhoon near Shanghai, terminals shut for 5 days",
    "The ransomware attack in Korea",
    "A ship is stuck at the entrance of the Suez canal for a week",
    "MV Silver Spirit is out of service for 4 days",
]
# One colour per node label, reused in every graph drawing.
COLORS = {"Port": "#E4572E", "Route": "#F3A712", "Vessel": "#4C9F70",
          "Shipment": "#3A7CA5", "Customer": "#7B5EA7"}

st.set_page_config(page_title="Ripple", page_icon="🌊", layout="wide")


def run_agent(question: str, use_llm: bool) -> dict:
    # A Relate connection belongs to the thread that opened it, and Streamlit
    # may run each interaction on a different thread: open one per question.
    conn = db.connect()
    try:
        return agent.answer(conn, question, use_llm=use_llm)
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
        {"": "Second-order customers found", "Ripple (graph)": g["second_order_customers"],
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
def graph_stats() -> dict:
    conn = db.connect()
    try:
        nodes = {r["label"]: r["n"] for r in conn.execute(
            "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label")}
        rels = conn.execute("MATCH ()-[r]->() RETURN count(r) AS n").fetchone()["n"]
    finally:
        conn.close()
    return {"nodes": nodes, "relationships": rels}


def path_to_dot(paths: list, horizontal: bool = True) -> str:
    """Draw one or several paths as a Graphviz diagram. Nodes shared by
    several paths (the port, a vessel...) are drawn once, so the fan-out
    from the disruption to the customers becomes visible."""
    lines = ["digraph {", f"rankdir={'LR' if horizontal else 'TB'};", 'bgcolor="transparent";',
             'node [style="filled,rounded", shape=box, fontname="Helvetica", fontsize=11, '
             'fontcolor=white, color="#00000000"];',
             'edge [fontname="Helvetica", fontsize=9, color="#888888", fontcolor="#888888"];']
    seen_nodes, seen_edges = set(), set()
    for nodes, rels in paths:
        for node in nodes:
            key = f"{node['label']}:{node['name']}"
            if key not in seen_nodes:
                seen_nodes.add(key)
                lines.append(f'"{key}" [label="{node["name"]}", fillcolor="{COLORS[node["label"]]}"];')
        for i, rel in enumerate(rels):
            a = f"{nodes[i]['label']}:{nodes[i]['name']}"
            b = f"{nodes[i + 1]['label']}:{nodes[i + 1]['name']}"
            if (a, b) not in seen_edges:
                seen_edges.add((a, b))
                # Lay the nodes out in the order the agent walked them, but
                # point the arrowhead the way the relationship is stored.
                direction = "forward" if rel["forward"] else "back"
                lines.append(f'"{a}" -> "{b}" [label="{rel["type"]}", dir={direction}];')
    return "\n".join(lines + ["}"])


def show_result(result: dict, key: str) -> None:
    d, s = result["disruption"], result["summary"]
    what = "closed" if d["kind"] == "port_closure" else "out of service"
    st.subheader(f"{d['name']} {what} for {d['days']} days")

    cols = st.columns(5)
    cols[0].metric("Shipments late", s["shipments"])
    cols[1].metric("Customers affected", s["customers"])
    cols[2].metric("Beyond tolerance", s["sla_breaches"])
    cols[3].metric("Cargo value", agent.money(s["value_at_risk_usd"]))
    cols[4].metric("Second-order customers", s["downstream_customers"])

    impacted = result["impacted"]
    if not impacted:
        st.info("No vessel in the graph is scheduled to call there during that window.")
        return

    tab_list, tab_graph, tab_downstream, tab_mitigation = st.tabs(
        ["Impacted shipments", "Impact graph", "Second-order impact",
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
        st.graphviz_chart(path_to_dot([(row["path_nodes"], row["path_rels"])]))
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
        st.graphviz_chart(path_to_dot(paths), width="stretch")
        legend = " &nbsp; ".join(f'<span style="color:{color}">&#9632;</span> {label}'
                                 for label, color in COLORS.items())
        st.markdown(f"One disruption on the left, every customer it reaches on the right. "
                    f"&nbsp; {legend}", unsafe_allow_html=True)

    with tab_downstream:
        if result["downstream"]:
            st.markdown("Buyers supplied by a manufacturer whose inputs arrive later than it tolerates.")
            st.dataframe(pd.DataFrame([{
                "Customer": r["customer"], "Tier": r["tier"], "Supplied by": r["via_customer"],
                "Late shipment": r["via_shipment"], "Exposure (days)": r["delay_days"], "Path": r["path"],
            } for r in result["downstream"]]), hide_index=True, width="stretch")
        else:
            st.info("No second-order impact.")

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
    fallback = st.selectbox("Divert the impacted vessels to", codes, index=default,
                            format_func=lambda c: names[c] + ("  ★ best" if best and c == best["fallback"]["code"] else ""),
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
                f"{sim['extra_road_km']:,} km by road. Before: {b['shipments_late']} late, "
                f"{b['sla_breaches']} beyond tolerance.")
    st.dataframe(pd.DataFrame([{
        "Shipment": r["shipment"], "Customer": r["customer"], "Delay before": r["delay_before"],
        "Delay after": r["delay_after"], "Tolerance": r["sla_days"],
        "Beyond tolerance after": "yes" if r["breach_after"] else "no", "How": r["how"],
    } for r in sim["shipments"]]), hide_index=True, width="stretch")
    st.caption("Model: no sea detour if the fallback is already on the vessel's route, otherwise "
               f"{mitigation.SEA_KM_PER_DAY} km/day plus a day in port; cargo loaded or unloaded at the "
               f"closed port goes by road at {mitigation.LAND_KM_PER_DAY} km/day; a shipment is diverted "
               "only when that is faster than waiting.")


# ------------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🌊 Ripple")
    st.caption("Supply chain disruption agent on a Relate graph")
    if llm.available():
        use_llm = st.toggle(f"Use LLM ({llm.provider()})", value=True)
    else:
        use_llm = False
        st.info("No API key found: running in rule-based mode. "
                "Add a Groq or Mistral key to `.env` to enable the LLM.")
    st.markdown("**Try an example**")
    for example in EXAMPLES:
        if st.button(example, width="stretch"):
            st.session_state["question"] = example
    stats = graph_stats()
    st.markdown("**The graph**")
    st.caption(" · ".join(f"{n} {label}s" for label, n in stats["nodes"].items())
               + f" · {stats['relationships']} relationships. All data is synthetic; "
                 "the scenario's \"today\" is 1 December 2026.")

# ---------------------------------------------------------------------- main
st.header("What happens if...?")
# A link like  /?q=Port+of+Rotterdam+closed  opens the page with an answer.
if "question" not in st.session_state and st.query_params.get("q"):
    st.session_state["question"] = st.query_params["q"]
question = st.text_input("Describe a disruption in plain English", key="question",
                         placeholder="Port of Rotterdam closed for 3 days")

if question:
    with st.spinner("Walking the graph..."):
        out = run_agent(question, use_llm)

    st.markdown(out["explanation"])
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
