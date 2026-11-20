"""Ripple web UI.  Run with:  streamlit run app.py

The page only displays what ripple/agent.py returns: the explanation, the
ranked list of impacted shipments, and for each one the graph path that
explains it. No analysis logic lives here.
"""

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

from ripple import agent, db, explore, geo, live, llm, mitigation, plain_rag, queries, radar, resilience, viz, workspace
from ripple.generate import SCENARIO_DATE

EXAMPLES = [
    "Port of Rotterdam closed for 3 days",
    "Typhoon near Shanghai, terminals shut for 5 days",
    "The ransomware attack in Korea",
    "A ship is stuck at the entrance of the Suez canal for a week",
    "MV Silver Spirit is out of service for 4 days",
]
COLORS = viz.COLORS
PAGES = ["Ask Ripple", "Network weak points", "Inside the graph"]

ASSETS = Path(__file__).resolve().parent / "assets"
st.set_page_config(page_title="Ripple · supply chain disruption agent", page_icon=str(ASSETS / "logo.png"),
                   layout="wide")

# A few styles on top of the theme in .streamlit/config.toml.
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');
.block-container {padding-top: 3.6rem; max-width: 1240px}
.rp-mono, .rp-eyebrow, .rp-big, .rp-num, .rp-pill {font-family: "JetBrains Mono", ui-monospace, monospace}
.rp-eyebrow {color: #8A8A8A; font-weight: 500; letter-spacing: .06em; text-transform: uppercase;
             font-size: .74rem; margin-bottom: .5rem}
.rp-hero {display: flex; align-items: center; gap: 40px; margin-bottom: .6rem;
          padding-bottom: 1.4rem; border-bottom: 1px solid #1C1C1C}
.rp-hero > div:first-child {flex: 1; min-width: 0}
.rp-hero svg {flex: none; width: 170px; height: 170px}
.rp-wordmark {font-size: 1.45rem; font-weight: 700; letter-spacing: -.03em; line-height: 1; color: #FFFFFF}
.rp-title {font-size: 2.6rem; line-height: 1.05; font-weight: 700; letter-spacing: -.035em; margin: 0 0 .8rem;
           color: #FFFFFF; text-wrap: balance}
.rp-title em {font-style: normal; color: #3BD671}
.rp-lead {color: #A3A3A3; font-size: 1.05rem; max-width: 46rem; margin-bottom: .4rem}
.rp-grid {display: grid; gap: 1px; margin: .6rem 0 1.6rem; background: #262626; border: 1px solid #262626;
          border-radius: 6px; overflow: hidden}
.rp-card {background: #000000; padding: 18px 20px}
.rp-big {font-size: 1.9rem; font-weight: 600; letter-spacing: -.03em; line-height: 1.1; color: #FFFFFF}
.rp-big small {font-size: .95rem; font-weight: 500; color: #6B6B6B}
.rp-label {color: #E5E5E5; font-weight: 600; margin-top: .35rem}
.rp-muted {color: #8A8A8A; font-size: .87rem; margin-top: .2rem}
.rp-accent, .rp-good {color: #3BD671}
.rp-bad {color: #FFFFFF; text-decoration: underline; text-decoration-color: #555; text-underline-offset: 4px}
.rp-step {display: flex; gap: 12px; align-items: flex-start}
.rp-num {flex: none; color: #3BD671; font-weight: 600; font-size: .85rem; padding-top: 2px}
.rp-verdict {background: #000000; border: 1px solid #333333; border-radius: 6px; padding: 22px 24px;
             margin: .3rem 0 1rem}
.rp-verdict h3 {margin: 0 0 1rem; font-size: 1.3rem; font-weight: 700; letter-spacing: -.02em}
.rp-verdict .rp-grid {border: 0; margin: 0; background: transparent; gap: 14px}
.rp-row {display: flex; flex-wrap: wrap; gap: 10px 28px; margin-top: 1rem; padding-top: 1rem;
         border-top: 1px solid #262626; color: #D4D4D4}
.rp-pill {display: inline-block; padding: 1px 8px; border-radius: 3px; font-size: .72rem; font-weight: 600;
          text-transform: uppercase; letter-spacing: .04em}
.rp-high {background: #FFFFFF; color: #000000}
.rp-medium {border: 1px solid #555555; color: #BDBDBD}
@media (max-width: 760px) {.rp-hero svg {display: none} .rp-title {font-size: 2rem}
                           .rp-grid {grid-template-columns: 1fr !important}}
</style>""", unsafe_allow_html=True)


# The logo's three waves, without the tile (same geometry as assets/make_logo.py).
HERO_ART = ('<svg viewBox="20 22 88 84" aria-hidden="true"><g fill="none" stroke-width="6" '
            'stroke-linecap="round">'
            '<path d="M28 44 q9 -10 18 0 t18 0 t18 0 t18 0" stroke="#3BD671"/>'
            '<path d="M28 66 q9 -10 18 0 t18 0 t18 0 t18 0" stroke="#FFFFFF"/>'
            '<path d="M28 88 q9 -10 18 0 t18 0 t18 0 t18 0" stroke="#6B6B6B"/></g></svg>')


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def card(big: str, label: str, note: str = "") -> str:
    return (f'<div class="rp-card"><div class="rp-big">{big}</div><div class="rp-label">{label}</div>'
            + (f'<div class="rp-muted">{note}</div>' if note else "") + "</div>")


def grid(cards: list[str], columns: int) -> None:
    html(f'<div class="rp-grid" style="grid-template-columns: repeat({columns}, minmax(0, 1fr))">'
         + "".join(cards) + "</div>")

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


# Map colours (RGB): a scale from white (hit hardest) to dark grey, and green for the way out.
HOT, WARM, COOL, COLD = [245, 245, 245], [165, 165, 165], [100, 100, 100], [58, 58, 58]
GREEN = [59, 214, 113]
# A map style with nothing but a black background, passed inline as a data URL: no tiles to
# download, and Streamlit does not substitute its default basemap as it does for an empty style.
BLANK_STYLE = "data:application/json," + quote(json.dumps({
    "version": 8, "sources": {},
    "layers": [{"id": "background", "type": "background", "paint": {"background-color": "#000000"}}]}))


@st.cache_data
def land() -> dict:
    """Coastlines drawn by the app itself (Natural Earth 1:110m, public domain): no tiles to fetch,
    black sea and dark land like the rest of the page."""
    return json.loads((Path(__file__).resolve().parent / "data" / "world_land.geojson").read_text())


def deck(layers: list, lon: float = 20.0, lat: float = 25.0, zoom: float = 0.9) -> pdk.Deck:
    # Scrolling the page must not zoom the map: zoom with the + and - buttons or a double click.
    view = pdk.View(type="MapView", controller={"scrollZoom": False, "dragPan": True, "doubleClickZoom": True},
                    repeat=False)
    ground = pdk.Layer("GeoJsonLayer", land(), filled=True, stroked=True, get_fill_color=[17, 17, 17],
                       get_line_color=[52, 52, 52], line_width_min_pixels=0.6)
    return pdk.Deck(layers=[ground, *layers], views=[view], map_provider="carto", map_style=BLANK_STYLE,
                    initial_view_state=pdk.ViewState(longitude=lon, latitude=lat, zoom=zoom, pitch=0),
                    tooltip={"html": "{tip}", "style": {"backgroundColor": "#0E0E0E", "color": "#F2F2F2",
                                                        "fontSize": "13px", "borderRadius": "4px",
                                                        "border": "1px solid #333"}})


def rings(position: list, color: list, radii=(8, 15, 23)) -> list:
    """The logo's ripple drawn on the map: a filled centre and widening rings (sizes in pixels)."""
    point = [{"position": position, "tip": ""}]
    layers = [pdk.Layer("ScatterplotLayer", point, get_position="position", radius_units="pixels",
                        get_radius=r, filled=False, stroked=True, get_line_color=color + [230 - 65 * i],
                        line_width_min_pixels=2) for i, r in enumerate(radii)]
    return layers + [pdk.Layer("ScatterplotLayer", point, get_position="position", radius_units="pixels",
                               get_radius=5, get_fill_color=color + [255])]


@st.cache_data(show_spinner=False)
def impact_map_data(result_json: str) -> dict:
    conn = db.connect()
    try:
        return geo.impact_map(conn, json.loads(result_json))
    finally:
        conn.close()


def show_impact_map(result: dict) -> None:
    m = impact_map_data(json.dumps(result, default=str))
    for s in m["shipments"]:
        s["tip"] = (f"<b>{s['shipment']}</b> for {escape(s['customer'])}<br>{s['from_name']} → {s['to_name']}"
                    f"<br>+{s['delay_days']} days" + (" · beyond tolerance" if s["beyond_tolerance"] else ""))
    for d in m["deliveries"]:
        d["tip"] = f"{d['customers']} late delivery(ies) to customers in {d['country']}"
    for r in m["ripple"]:
        r["tip"] = f"<b>{escape(r['customer'])}</b> is supplied by {escape(r['via'])}: hit {r['hops']} tier(s) later"
    for p in m["ports"]:
        p.update(position=[p["lon"], p["lat"]], tip=p["name"])
    for c in m["countries"]:
        c["tip"] = f"Customers in {c['country']}: {c['shipments']} late delivery(ies)"

    def arcs(rows: list, source: list, target: list, width: float) -> pdk.Layer:
        """Low arcs, dim where they start and bright where they land."""
        return pdk.Layer("ArcLayer", rows, get_source_position="from", get_target_position="to",
                         get_source_color=source, get_target_color=target, get_width=width,
                         get_height=0.35, pickable=True)

    layers = [
        pdk.Layer("ScatterplotLayer", m["ports"], get_position="position", radius_units="pixels", get_radius=2.5,
                  get_fill_color=COOL + [255], pickable=True),
        arcs(m["ripple"], COOL + [60], WARM + [170], 1),
        arcs(m["deliveries"], COLD + [120], COOL + [220], 1.2),
        arcs([s for s in m["shipments"] if not s["beyond_tolerance"]], COLD + [140], WARM + [230], 1.6),
        arcs([s for s in m["shipments"] if s["beyond_tolerance"]], COOL + [170], HOT + [255], 2.2),
        pdk.Layer("ScatterplotLayer", m["countries"], get_position="position", radius_units="pixels",
                  get_radius="2 + shipments * 0.6", get_fill_color=HOT + [235], stroked=True,
                  get_line_color=[0, 0, 0, 255], line_width_min_pixels=1, pickable=True),
    ]
    headline = [f"<b>{len(m['shipments'])}</b> late shipments to customers in <b>{len(m['countries'])}</b> countries"]
    if m["fallback"]:
        there = [m["fallback"]["lon"], m["fallback"]["lat"]]
        layers += rings(there, GREEN, radii=(9,))
        headline.append(f'best fallback: <b class="rp-good">{escape(m["fallback"]["name"])}</b>')
    if m["closed"]:
        here = [m["closed"]["lon"], m["closed"]["lat"]]
        layers += rings(here, HOT)
        headline.insert(0, f'<b class="rp-bad">{escape(m["closed"]["name"])}</b> closed')
    html('<div style="margin:.2rem 0 .5rem">' + " · ".join(headline) + "</div>")
    st.pydeck_chart(deck(layers, lon=10.0, lat=18.0, zoom=0.9), height=500)
    html('<div class="rp-muted" style="display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:.3rem">'
         '<span><span style="color:#F5F5F5">━</span> late shipment, beyond the customer\'s tolerance</span>'
         '<span><span style="color:#A5A5A5">━</span> late, still tolerated</span>'
         '<span><span style="color:#646464">━</span> on to the customer\'s country</span>'
         '<span><span style="color:#A5A5A5">╌</span> companies hit through their suppliers</span>'
         '<span><span style="color:#F5F5F5">●</span> customers, by country</span>'
         '<span><span class="rp-good">●</span> best fallback port</span>'
         '<span>Ports and routes are real places; customers sit at the centre of their country.</span></div>')


def show_result(result: dict, key: str) -> None:
    d, s = result["disruption"], result["summary"]
    what = "closed" if d["kind"] == "port_closure" else "out of service"
    st.subheader(f"{d['name']} {what} for {d['days']} days")

    cols = st.columns(5)
    cols[0].metric("Shipments late", s["shipments"], border=True)
    cols[1].metric("Customers affected", s["customers"], border=True)
    cols[2].metric("Beyond tolerance", s["sla_breaches"], border=True)
    cols[3].metric("Cargo value", agent.money(s["value_at_risk_usd"]), border=True)
    cols[4].metric("Customers via suppliers", s["downstream_customers"], border=True)

    impacted = result["impacted"]
    if not impacted:
        st.info("No vessel in the graph is scheduled to call there during that window.")
        return

    tab_map, tab_list, tab_graph, tab_downstream, tab_mitigation = st.tabs(
        ["Impact map", "Impacted shipments", "Impact graph", "Ripple effect",
         "Mitigation" if d["kind"] == "port_closure" else "Alternatives"])

    with tab_map:
        show_impact_map(result)

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
        legend = " &nbsp; ".join(f'<span style="color:{viz.BORDER.get(label, color)}">&#9632;</span> {label}'
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
                   delta_color="inverse", border=True)
    cols[1].metric("Delay days after", a["delay_days"], a["delay_days"] - b["delay_days"],
                   delta_color="inverse", border=True)
    cols[2].metric("Beyond tolerance after", a["sla_breaches"], a["sla_breaches"] - b["sla_breaches"],
                   delta_color="inverse", border=True)
    cols[3].metric("Value protected", agent.money(sim["value_protected_usd"]), border=True)
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
    html(f'<div style="display:flex;align-items:center;gap:12px;margin:.2rem 0 .3rem">'
         f'<img src="data:image/svg+xml;base64,{logo}" width="46" alt="">'
         f'<div><div class="rp-wordmark">Ripple</div>'
         f'<div class="rp-muted" style="margin:0">Disruption agent on a Relate graph</div></div></div>')
    st.radio("Page", PAGES, key="page", label_visibility="collapsed")
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
    if st.session_state.get("question"):
        st.button("← Home: risk radar and examples", on_click=lambda: ask(""), width="stretch")
    stats = graph_stats()
    st.markdown("**The graph**")
    st.caption(" · ".join(f"{n} {label}s" for label, n in stats["nodes"].items())
               + f" · {stats['relationships']} relationships. The ports and their positions "
                 "are real (Wikidata, Natural Earth); vessels, shipments and customers are synthetic. "
                 "The scenario's \"today\" is 1 December 2026.")

# ---------------------------------------------------------------------- main

@st.cache_data
def radar_rows() -> list:
    conn = db.connect()
    try:
        return radar.scan(conn)
    finally:
        conn.close()


def ask(question: str) -> None:
    """Button callback: run a question as a new scenario."""
    st.session_state["page"] = PAGES[0]
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


def show_radar_map(rows: list) -> None:
    conn = db.connect()
    try:
        points = geo.radar_map(conn, rows)
    finally:
        conn.close()
    layers = []
    top = max((p["value"] for p in points), default=1) or 1
    for p in points:
        color = HOT if p["severity"] == "high" else WARM
        size = 3 + 3.5 * (p["value"] / top) ** 0.5  # pixels: area grows with the cargo at risk
        p["tip"] = f"<b>{p['name']}</b> · {agent.money(p['value'])} beyond tolerance<br>{escape(p['text'])}"
        layers += [pdk.Layer("ScatterplotLayer", [p], get_position="position", radius_units="pixels",
                             get_radius=size * k, filled=False, stroked=True,
                             get_line_color=color + [200 - 70 * i], line_width_min_pixels=1.5)
                   for i, k in enumerate((2, 3.2))]  # hover a port for its name and alert
        layers.append(pdk.Layer("ScatterplotLayer", [p], get_position="position", radius_units="pixels",
                                get_radius=size, get_fill_color=color + [255], pickable=True))
    st.pydeck_chart(deck(layers, lon=10.0, lat=18.0, zoom=0.9), height=440)


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
                   f"vessels and shipments as of {SCENARIO_DATE:%d %B %Y}: the network's schedule is "
                   "frozen at that date so that every run gives the same answer to the same news.")
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
    if rows:
        show_radar_map(rows[:6])
    for i, r in enumerate(rows[:6]):
        with st.container(border=True):
            left, middle, right = st.columns([5, 4, 1.4])
            pill = f'<span class="rp-pill rp-{r["severity"]}">{r["severity"]}</span>'
            meta = f"{r['date']:%d %b}"
            if "headlines" in r:
                url = r["headlines"][0]["url"]
                source = (f'<a href="{escape(url)}" target="_blank">{escape(r["source"])}</a>' if url
                          else escape(r["source"]))
                meta += f" · {source}" + (f" · {r['articles']} articles" if r["articles"] > 1 else "")
            left.markdown(f"**{escape(', '.join(r['port_names']))}** &nbsp;{pill}&nbsp; "
                          f'<span class="rp-muted">{meta}</span>  \n{escape(r["text"])}', unsafe_allow_html=True)
            middle.markdown(f"**{agent.money(r['value_beyond_tolerance_usd'])}** beyond tolerance  \n"
                            f"{r['shipments']} shipments late, {r['customers']} customers, "
                            f"{r['ripple_customers']} via suppliers, "
                            + (f"simulated for {r['days_total']} day(s)" if "headlines" in r
                               else f"{r['days_remaining']} day(s) left"))
            right.button("Analyze", key=f"radar-{mode}-{i}", on_click=ask, args=(r["question"],), width="stretch")


@st.cache_data(show_spinner=False)
def proof() -> dict:
    """The landing page's evidence, computed live on the graph: one closure,
    what the graph finds, and what plain RAG finds on the same data."""
    conn = db.connect()
    try:
        question = "Port of Rotterdam closed for 3 days"
        result = queries.port_closure(conn, "NLRTM", 3)
        cmp = plain_rag.compare(conn, question, [result], 10)
        hops = max(len(r["path_rels"]) for r in result["impacted"])
        return {"graph": cmp["graph"], "rag": cmp["plain_rag"], "hops": hops,
                "supplier_hops": max((r["supplier_hops"] for r in result["downstream"]), default=0)}
    finally:
        conn.close()


def show_pitch() -> None:
    p = proof()
    g, r = p["graph"], p["rag"]
    grid([
        card(f'{g["shipments"]} <small>vs {r["shipments_found"]}</small>', "delayed shipments found",
             "Rotterdam closed 3 days: Ripple walks the graph, plain RAG retrieves the top 10 documents "
             "of the same data."),
        card(f'{p["hops"]} hops', "from the port to each customer",
             "Port, route, vessel, shipment, customer: every answer comes with that path."),
        card(f'{g["second_order_customers"]} <small>vs {r["second_order_found"]}</small>',
             "customers hit through their suppliers",
             f"A variable-length SUPPLIES path follows the ripple up to {p['supplier_hops']} tiers here."),
    ], 3)
    steps = [
        ("Understand", "Names, sea areas and radii, or hybrid search over the news when no port is named."),
        ("Walk the graph", "Multi-hop Cypher on the embedded Relate store, arrival dates computed per vessel."),
        ("Explain", "Ranked impact with the path behind each line, written by an LLM or by rules."),
        ("Act", "Simulate a diversion, keep the plan: it is written back to the graph."),
    ]
    grid([f'<div class="rp-card rp-step"><div class="rp-num">{i:02d}</div><div><b>{t}</b>'
          f'<div class="rp-muted">{d}</div></div></div>' for i, (t, d) in enumerate(steps, 1)], 4)


def show_verdict(out: dict) -> None:
    """The answer in one card, before the details."""
    results = out["results"]
    c = queries.combine(results)
    names = " and ".join(r["disruption"]["name"] for r in results)
    d = results[0]["disruption"]
    what = "closed" if d["kind"] == "port_closure" else "out of service"
    cmp = run_comparison(out["question"], results, 10)
    queries_run = sum(len(r.get("trace", [])) for r in results)
    ms = sum(step["ms"] for r in results for step in r.get("trace", []))
    best = results[0].get("best_diversion") if len(results) == 1 else None
    move = ""
    if best and best["shipments_rescued"]:
        move = (f'<span>Best move: <b class="rp-good">divert to {escape(best["fallback"]["name"])}</b>, '
                f'{best["shipments_rescued"]} shipments rescued, '
                f'<b>{agent.money(best["value_protected_usd"])}</b> protected</span>')
    html(f'''<div class="rp-verdict"><h3>{escape(names)} {what} for {d["days"]} days</h3>
      <div class="rp-grid" style="grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0">
        <div><div class="rp-big">{c["shipments"]}</div><div class="rp-muted">shipments late</div></div>
        <div><div class="rp-big">{c["customers"]}</div><div class="rp-muted">customers affected</div></div>
        <div><div class="rp-big rp-bad">{agent.money(c["value_beyond_tolerance_usd"])}</div>
             <div class="rp-muted">of cargo later than customers tolerate</div></div>
        <div><div class="rp-big">{c["downstream_customers"]}</div><div class="rp-muted">more customers hit
             through suppliers</div></div>
      </div>
      <div class="rp-row">{move}<span>Plain RAG on the same data finds
        <b>{cmp["plain_rag"]["shipments_found"]}</b> of the {c["shipments"]} late shipments</span>
        <span class="rp-muted" style="margin:0">{queries_run} Cypher queries on Relate, {ms:.0f} ms</span></div>
    </div>''')


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


def show_under_the_hood(results: list) -> None:
    """The Cypher queries Relate ran for this answer, with parameters, rows, time and a replay command."""
    steps = [step for r in results for step in r.get("trace", [])]
    if not steps:
        return
    total = sum(step["ms"] for step in steps)
    with st.expander(f"Under the hood: {len(steps)} Cypher queries ran on Relate in {total:.0f} ms"):
        st.markdown("Every number above comes from these queries on the embedded Relate store "
                    "(`data/ripple.relate`), not from the language model. Copy a command to replay the same "
                    "query read-only with Relate's own CLI and get the same rows.")
        for i, step in enumerate(steps, 1):
            st.markdown(f"**{i}. {step['name']}** · {step['rows']} rows · {step['ms']} ms")
            st.code(step["cypher"], language="cypher")
            params = {k: (v if isinstance(v, (int, float, str)) else str(v)) for k, v in step["params"].items()}
            if step["params"].get("late"):
                late = step["params"]["late"]
                params["late"] = f"{len(late)} late shipments, e.g. {late[0]}"
            st.caption("Parameters: " + ", ".join(f"`${k}` = {v}" for k, v in params.items()))
            st.code(queries.cli_command(step["cypher"], step["params"]), language="bash")


@st.cache_data(show_spinner="Simulating a closure of every port on the graph...")
def weak_points(days: int) -> dict:
    conn = db.connect()
    try:
        return resilience.rank_ports(conn, days)
    finally:
        conn.close()


def weak_points_page() -> None:
    html('<div class="rp-eyebrow">Before anything happens</div>'
         '<div class="rp-title" style="font-size:2.2rem">Where is the network weakest?</div>'
         '<div class="rp-lead">The radar reacts to today\'s news. This page looks ahead: Ripple closes every '
         'port of the graph in turn and measures the damage with the same multi-hop analysis as a question, '
         'plus one Cypher query that counts how many customers depend on each port, up to 3 supplier tiers '
         'away.</div>')
    days = st.select_slider("Closure length (days)", [1, 2, 3, 5, 7, 10, 14], value=3, key="wp_days")
    report = weak_points(days)
    ports = report["ports"]
    hit = [p for p in ports if p["shipments"]]
    customers = graph_stats()["nodes"]["Customer"]
    grid([
        card(f'{report["queries"]}', "Cypher queries on Relate",
             f'{report["ms"]:.0f} ms for the whole network, {len(ports)} ports closed one at a time.'),
        card(escape(ports[0]["name"]), "hurts most",
             f'{agent.money(ports[0]["value_beyond_tolerance_usd"])} of cargo later than customers tolerate, '
             f'{ports[0]["shipments"]} shipments late.'),
        card(f'{max(p["dependent_customers"] for p in ports)} <small>of {customers}</small>',
             "customers depend on the most central port",
             "Directly or up to 3 supplier tiers away, whatever the dates."),
    ], 3)
    top = max(p["value_beyond_tolerance_usd"] for p in ports) or 1
    points = []
    for rank, p in enumerate(ports, 1):
        share = p["value_beyond_tolerance_usd"] / top
        color = HOT if share > .5 else WARM if share > .2 else COOL if p["shipments"] else COLD
        points.append({"position": [p["lon"], p["lat"]], "radius": 3 + 9 * share ** .5, "color": color + [230],
                       "tip": f"<b>#{rank} {escape(p['name'])}</b><br>"
                              f"{agent.money(p['value_beyond_tolerance_usd'])} beyond tolerance · "
                              f"{p['shipments']} late<br>{p['dependent_customers']} customers depend on it"})
    layer = pdk.Layer("ScatterplotLayer", points, get_position="position", radius_units="pixels",
                      get_radius="radius", get_fill_color="color", stroked=True, get_line_color=[10, 15, 28, 255],
                      line_width_min_pixels=1, pickable=True)
    st.pydeck_chart(deck([layer], lon=10.0, lat=18.0, zoom=0.9), height=470)
    html('<div class="rp-muted"><span style="color:#F5F5F5">●</span> most exposed &nbsp; '
         '<span style="color:#A5A5A5">●</span> exposed &nbsp; <span style="color:#646464">●</span> some late '
         'cargo &nbsp; <span style="color:#3A3A3A">●</span> nothing due in that window. '
         'Size: cargo later than customers tolerate.</div>')
    st.dataframe(pd.DataFrame([{
        "Rank": i, "Port": p["name"], "Beyond tolerance": p["value_beyond_tolerance_usd"],
        "Shipments late": p["shipments"], "Customers hit": p["customers"], "Via suppliers": p["ripple_customers"],
        "Customers depending on it": p["dependent_customers"], "Routes": p["routes"], "Vessels": p["vessels"],
    } for i, p in enumerate(ports, 1)]), hide_index=True, width="stretch",
        column_config={"Beyond tolerance": st.column_config.NumberColumn(format="dollar"),
                       "Customers depending on it": st.column_config.ProgressColumn(
                           min_value=0, max_value=customers, format="%d")})
    st.markdown("**Analyze one of the five weakest ports**")
    for col, p in zip(st.columns(5), hit[:5], strict=False):  # fewer than 5 if few ports are hit
        col.button(p["name"], key=f"wp-{p['code']}", on_click=ask, args=(p["question"],), width="stretch")
    with st.expander(f"The dependence query ({report['dependence_ms']} ms on Relate)"):
        st.code(report["dependence_cypher"], language="cypher")
        st.code(queries.cli_command(report["dependence_cypher"], {}), language="bash")


@st.cache_data
def graph_model() -> dict:
    conn = db.connect()
    try:
        return explore.overview(conn)
    finally:
        conn.close()


def run_console(cypher: str) -> dict:
    conn = db.connect()
    try:
        return explore.run(conn, cypher)
    finally:
        conn.close()


def pick_example() -> None:
    st.session_state["console"] = explore.EXAMPLES[st.session_state["console_example"]].strip()


def graph_page() -> None:
    html('<div class="rp-eyebrow">Read live from the Relate store</div>'
         '<div class="rp-title" style="font-size:2.2rem">Inside the graph</div>'
         '<div class="rp-lead">The data model below is not drawn by hand: Ripple asks Relate for it '
         '(<code>CALL db.schema.nodeTypeProperties()</code>, one count over every relationship, '
         '<code>SHOW INDEXES</code>). Then try your own Cypher; anything that would write is refused.</div>')
    model = graph_model()
    grid([card(f'{item["count"]:,}', escape(item["label"]) + "s") for item in model["labels"]],
         len(model["labels"]))
    st.graphviz_chart(explore.schema_dot(model), width="stretch")
    left, right = st.columns(2)
    with left:
        st.markdown("**Indexes Relate maintains**")
        st.dataframe(pd.DataFrame(model["indexes"]).rename(columns={"name": "Index", "type": "Type", "on": "On"}),
                     hide_index=True, width="stretch")
    with right:
        st.markdown("**Properties by label**")
        for item in model["labels"]:
            st.caption(f"**{item['label']}**: " + ", ".join(item["properties"]))
    st.subheader("Cypher console")
    names = list(explore.EXAMPLES)
    st.session_state.setdefault("console", explore.EXAMPLES[names[0]].strip())
    st.selectbox("Start from an example", names, key="console_example", on_change=pick_example)
    cypher = st.text_area("Cypher (read-only)", key="console", height=170)
    if st.button("Run on Relate", type="primary"):
        try:
            result = run_console(cypher)
        except Exception as error:  # refused or invalid: say why, never crash the page
            st.error(f"Not run: {error}")
        else:
            st.caption(f"{len(result['rows'])} row(s){' (first 50)' if result['truncated'] else ''} · "
                       f"{result['ms']} ms on Relate · checked read-only with EXPLAIN first")
            st.dataframe(pd.DataFrame(result["rows"], columns=result["columns"]), hide_index=True,
                         width="stretch")
            st.code(queries.cli_command(result["cypher"], {}), language="bash")


def ask_page() -> None:
    # A link like  /?q=Port+of+Rotterdam+closed  opens the page with an answer.
    if "question" not in st.session_state and st.query_params.get("q"):
        st.session_state["question"] = st.query_params["q"]
    if st.session_state.get("question"):
        html('<div class="rp-eyebrow">What happens if...?</div>')
    else:
        html('<div class="rp-hero"><div>'
             '<div class="rp-eyebrow">Supply chain disruption agent · built on Relate</div>'
             '<div class="rp-title">A port closes.<br>Who is hit, <em>three hops later?</em></div>'
             '<div class="rp-lead">Describe a disruption in plain English. Ripple walks a Relate graph from the '
             'port to the vessels due there, the cargo on board, the customers waiting for it and the companies '
             'they supply, and shows the exact path behind every answer.</div></div>' + HERO_ART + '</div>')
    question = st.text_input("Describe a disruption in plain English, then ask follow-ups "
                             "(\"and if it lasts a week?\", \"what about Antwerp instead?\")", key="question",
                             placeholder="Describe a disruption, e.g. Port of Rotterdam closed for 3 days",
                             label_visibility="visible" if st.session_state.get("question") else "collapsed")
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

        if out["results"] and any(r["impacted"] for r in out["results"]):
            show_verdict(out)
        with st.container(border=True):
            html(f'<div class="rp-eyebrow">Ripple\'s analysis · '
                 f'{"written by the LLM from the graph paths" if out["explained_by"] == "llm" else "rule-based"}</div>')
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

        show_under_the_hood(out["results"])

        if out["results"]:
            tab_impact, tab_compare = st.tabs(["Impact", "Graph vs plain RAG"])
            with tab_impact:
                if len(out["results"]) > 1:
                    c = queries.combine(out["results"])
                    st.subheader(f"Combined: {len(out['results'])} disruptions at once")
                    cols = st.columns(5)
                    cols[0].metric("Unique shipments late", c["shipments"], border=True)
                    cols[1].metric("Unique customers", c["customers"], border=True)
                    cols[2].metric("Beyond tolerance (all)", c["sla_breaches"], border=True)
                    cols[3].metric("Cargo value (all)", agent.money(c["value_at_risk_usd"]), border=True)
                    cols[4].metric("Hit twice, counted once", c["double_counted"], border=True)
                    st.divider()
                for index, result in enumerate(out["results"]):
                    if index:
                        st.divider()
                    show_result(result, key=str(index))
            with tab_compare:
                show_comparison(question, out["results"])
    else:
        st.pills("Try", EXAMPLES, key="example", on_change=lambda: ask(st.session_state["example"] or ""),
                 label_visibility="collapsed")
        show_pitch()
        show_radar()
        show_decision_log()


page = st.session_state.get("page", PAGES[0])
if page == PAGES[1]:
    weak_points_page()
elif page == PAGES[2]:
    graph_page()
else:
    ask_page()
