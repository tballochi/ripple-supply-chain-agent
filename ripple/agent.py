"""The agent: from a question in plain English to an explained answer.

Try it:  python -m ripple.agent "Port of Rotterdam closed for 3 days"
         python -m ripple.agent --no-llm "the ransomware attack in Korea"

Three steps, the same in both modes:

  1. UNDERSTAND  Which port or vessel is hit, and for how long?
                 Retrieval (ripple/retrieval.py) proposes candidates from the
                 graph. In LLM mode the model then picks the tool and its
                 arguments; in rule-based mode a few rules do.
  2. QUERY       Run the matching graph query (ripple/queries.py). The LLM
                 never writes Cypher: it only chooses between two fixed,
                 tested queries. Whatever it answers is checked against the
                 graph before anything runs.
  3. EXPLAIN     Write the answer from the paths the query returned. In LLM
                 mode the model writes it, from those facts only; if it cites
                 a shipment that is not in the results, its text is dropped
                 and the rule-based text is used.

Any LLM failure (no key, network error, bad answer) falls back to the
rule-based mode, so the agent always answers.
"""

import json
import math
import re
import sys

from . import db, llm, mitigation, plain_rag, queries, retrieval

DEFAULT_DAYS = 3
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
DURATION = re.compile(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")[\s-]*(hour|day|week)s?\b", re.IGNORECASE)


def parse_days(text: str) -> int | None:
    """'3 days' -> 3, 'a week' -> 7, '48 hours' -> 2. None if no duration."""
    match = DURATION.search(text)
    if not match:
        return None
    amount = match.group(1).lower()
    number = int(amount) if amount.isdigit() else NUMBER_WORDS[amount]
    unit = match.group(2).lower()
    days = {"hour": math.ceil(number / 24), "day": number, "week": number * 7}[unit]
    return max(1, min(days, 60))


# ---------------------------------------------------------------- understand

def plan_with_rules(question: str, found: dict) -> dict:
    """Rule-based plan: trust what retrieval matched, read the duration."""
    days = parse_days(question)
    return {
        "ports": [p["code"] for p in found["ports"]],
        "vessels": [v["imo"] for v in found["vessels"]],
        "days": days or DEFAULT_DAYS,
        "days_assumed": days is None,
        "reasoning": None,
    }


PLAN_SYSTEM = """You are the planning step of a supply chain disruption agent.
You do not answer the user. You choose which graph query to run.

Two tools exist:
- port_closure(port_codes, days): a port is closed or unusable.
- vessel_outage(vessel_imos, days): a vessel is out of service.

You receive the user's question, the list of ports in the graph, and what
retrieval found (candidate ports, candidate vessels, related news alerts with
the ports they mention). Use ONLY port codes and vessel IMOs that appear in
that input. If the question names no duration, set days to null.
If the question is not about a disruption to a port or a vessel, return
empty lists.

Reply with JSON only:
{"port_codes": [...], "vessel_imos": [...], "days": <integer or null>,
 "reasoning": "<one sentence: why these entities>"}"""


def plan_with_llm(conn, question: str, found: dict) -> dict:
    """LLM plan. Its answer is validated against the graph before use."""
    all_ports = [dict(r) for r in conn.execute(
        "MATCH (p:Port) RETURN p.code AS code, p.name AS name, p.country AS country ORDER BY name")]
    context = {
        "question": question,
        # One short string per port keeps the prompt small (free tiers count tokens).
        "ports_in_graph": [f"{p['code']} {p['name']} ({p['country']})" for p in all_ports],
        "retrieval_candidate_ports": found["ports"],
        "retrieval_candidate_vessels": found["vessels"],
        "related_alerts": [{"text": a["text"], "ports": a["ports"]} for a in found["alerts"]],
    }
    answer = llm.chat_json(PLAN_SYSTEM, json.dumps(context, default=str))

    known_ports = {p["code"] for p in all_ports}
    known_vessels = {v["imo"] for v in found["vessels"]}
    ports = [c for c in answer.get("port_codes") or [] if c in known_ports]
    vessels = [i for i in answer.get("vessel_imos") or [] if i in known_vessels]
    days = answer.get("days")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 60:
        days = parse_days(question)
    return {
        "ports": ports, "vessels": vessels,
        "days": days or DEFAULT_DAYS, "days_assumed": days is None,
        "reasoning": str(answer.get("reasoning") or "")[:300] or None,
    }


# ------------------------------------------------------------------- explain

def money(amount: int) -> str:
    return f"${amount / 1_000_000:.1f}M" if amount >= 1_000_000 else f"${amount:,}"


def extra_distance(sim: dict) -> str:
    parts = [f"+{sim['extra_sea_km']:,} km at sea" if sim["extra_sea_km"] else "",
             f"+{sim['extra_road_km']:,} km by road or feeder" if sim["extra_road_km"] else ""]
    parts = [p for p in parts if p]
    return "for " + " and ".join(parts) if parts else "with no extra distance (the vessels already call there)"


def explain_with_rules(results: list, plan: dict) -> str:
    """Deterministic explanation, built only from the query results."""
    parts = []
    for result in results:
        d, s = result["disruption"], result["summary"]
        what = "closed" if d["kind"] == "port_closure" else "out of service"
        lines = [f"**{d['name']} {what} for {d['days']} days** ({d['start']} to {d['reopen']})."]
        if not result["impacted"]:
            lines.append("No vessel in the graph is scheduled to call there during that window, "
                         "so no shipment is delayed.")
            parts.append("\n".join(lines))
            continue
        lines.append(
            f"{s['shipments']} shipments on {s['vessels']} vessel(s) are delayed by up to "
            f"{s['max_delay_days']} days, affecting {s['customers']} customers and "
            f"{money(s['value_at_risk_usd'])} of cargo. {s['sla_breaches']} of them exceed the delay "
            f"the customer tolerates.")
        if d["kind"] == "port_closure":
            on_board = sum(r["reason"] == queries.ON_BOARD for r in result["impacted"])
            lines.append(f"{on_board} are already on board and wait with the vessel; "
                         f"{s['shipments'] - on_board} are not loaded yet and wait on the quay "
                         "for a vessel that arrives late.")
        top = result["impacted"][0]
        lines.append(
            f"Most exposed: shipment {top['shipment']} for {top['customer']} ({top['tier']} customer, "
            f"{top['priority']} priority), {top['delay_days']} days late ({top['reason']}). "
            f"New ETA {top['new_eta']} instead of {top['eta']}.")
        lines.append(f"Path followed: `{top['path']}`")
        direct = {r["customer_id"] for r in result["impacted"]}
        only_downstream = [r for r in result["downstream"] if r["customer_id"] not in direct]
        if only_downstream:
            first = only_downstream[0]
            lines.append(
                f"Second-order effect: {s['downstream_customers']} more customer(s) depend on a "
                f"manufacturer whose inputs are late, for example `{first['path']}`.")
        best = result.get("best_diversion")
        if best and not best["breaches_avoided"]:
            lines.append(
                f"Best mitigation: divert to {best['fallback']['name']} ({best['fallback']['km']} km away). "
                f"It shortens the delay of {best['shipments_rescued']} shipments but avoids none of the "
                f"{best['before']['sla_breaches']} tolerance breaches.")
        elif best:
            lines.append(
                f"Best mitigation: divert to {best['fallback']['name']} ({best['fallback']['km']} km away). "
                f"It rescues {best['shipments_rescued']} shipments, avoids {best['breaches_avoided']} of "
                f"{best['before']['sla_breaches']} tolerance breaches and protects "
                f"{money(best['value_protected_usd'])} of cargo, {extra_distance(best)}.")
        elif result["alternatives"]:
            lines.append(f"Diverting to a nearby port (closest: {result['alternatives'][0]['name']}) "
                         "would not be faster than waiting for the port to reopen.")
        elif d["kind"] == "port_closure":
            lines.append("No alternative port within range in the graph.")
        parts.append("\n\n".join(lines))
    text = "\n\n---\n\n".join(parts)
    if plan["days_assumed"]:
        text += f"\n\n_No duration was given, so {plan['days']} days was assumed._"
    return text


EXPLAIN_SYSTEM = """You explain the result of a supply chain impact analysis.
You receive JSON facts computed from a graph database. Rules:
- Use ONLY the facts provided. Never invent a shipment, customer, date or number.
- Start with the headline: what is disrupted and the overall impact.
- Then name the 2 or 3 most exposed shipments. For each, quote its `path`
  exactly, in backticks, to show how the disruption reaches the customer.
- Mention `second_order_customers` (reached only through a supplier), and the best diversion
  (`best_diversion`) with what it saves, when present.
- If `days_assumed` is true, say the duration was assumed.
- Plain language, under 180 words, Markdown allowed."""


def second_order_examples(result: dict, limit: int = 3) -> list:
    """Customers reached ONLY through SUPPLIES (not directly hit), one line each."""
    direct = {row["customer_id"] for row in result["impacted"]}
    seen, out = set(), []
    for row in result["downstream"]:
        if row["customer_id"] in direct or row["customer_id"] in seen:
            continue
        seen.add(row["customer_id"])
        out.append({k: row[k] for k in ("customer", "via_customer", "delay_days", "path")})
    return out[:limit]


def facts_for_llm(results: list, plan: dict) -> dict:
    """A compact copy of the results: enough to explain, small enough to send."""
    keep = ("shipment", "customer", "tier", "priority", "delay_days", "eta", "new_eta",
            "sla_breached", "reason", "value_usd", "products", "path")
    return {
        "days_assumed": plan["days_assumed"],
        "analyses": [{
            "disruption": r["disruption"],
            "summary": r["summary"],
            "most_exposed_shipments": [{k: row[k] for k in keep} for row in r["impacted"][:5]],
            "second_order_customers": second_order_examples(r),
            "alternatives": [{k: a[k] for k in ("name", "km", "shared_routes")}
                             for a in r["alternatives"][:3]],
            "best_diversion": r.get("best_diversion") and {
                k: r["best_diversion"][k] for k in ("fallback", "before", "after", "shipments_rescued",
                                                    "breaches_avoided", "value_protected_usd",
                                                    "extra_sea_km", "extra_road_km")},
        } for r in results],
    }


def explain_with_llm(results: list, plan: dict) -> str:
    text = llm.chat(EXPLAIN_SYSTEM, json.dumps(facts_for_llm(results, plan), default=str)).strip()
    # Groundedness check: every shipment id in the text must be a real result.
    known = {row["shipment"] for r in results for row in r["impacted"]}
    invented = set(re.findall(r"\bS\d{4}\b", text)) - known
    if invented or not text:
        raise ValueError(f"explanation cites unknown shipments: {sorted(invented)}")
    return text


# --------------------------------------------------------------------- agent

def llm_reason(error: Exception) -> str:
    """A short, user-facing reason for an LLM fallback."""
    return str(error) if isinstance(error, (llm.LLMError, ValueError)) else type(error).__name__


def answer(conn, question: str, use_llm: bool | None = None) -> dict:
    """Run the three steps. `use_llm=None` means: use the LLM if a key is set."""
    use_llm = llm.available() if use_llm is None else (use_llm and llm.available())
    steps = []  # a readable trace of what the agent did, shown in the UI

    # 1. Understand
    found = retrieval.resolve(conn, question)
    steps.append(f"Retrieval ({found['mode']} search): "
                 + (", ".join(f"{p['name']} via {p['matched_by']}" for p in found["ports"])
                    or ", ".join(v["name"] for v in found["vessels"]) or "no entity matched"))
    plan, planned_by = None, "rules"
    if use_llm:
        try:
            plan, planned_by = plan_with_llm(conn, question, found), "llm"
        except Exception as error:
            steps.append(f"LLM planning failed ({llm_reason(error)}), using rules")
    if plan is None:
        plan = plan_with_rules(question, found)
    steps.append(f"Plan ({planned_by}): ports={plan['ports']} vessels={plan['vessels']} "
                 f"days={plan['days']}{' (assumed)' if plan['days_assumed'] else ''}")

    # 2. Query the graph
    results = [queries.port_closure(conn, code, plan["days"]) for code in plan["ports"]]
    results += [queries.vessel_outage(conn, imo, plan["days"]) for imo in plan["vessels"]]
    for r in results:
        if r["disruption"]["kind"] == "port_closure":
            r["best_diversion"] = mitigation.best_diversion(conn, r)
        steps.append(f"Graph query {r['disruption']['kind']}({r['disruption']['name']}): "
                     f"{r['summary']['shipments']} shipments, {r['summary']['customers']} customers")

    # 3. Explain
    explained_by = "rules"
    if not results:
        explanation = ("I could not link this to a port or a vessel in the graph. "
                       "Try naming a port (\"Port of Rotterdam closed for 3 days\"), a vessel, "
                       "a country, or an incident from the news alerts.")
    else:
        explanation = None
        if use_llm:
            try:
                explanation, explained_by = explain_with_llm(results, plan), "llm"
            except Exception as error:
                steps.append(f"LLM explanation not used ({llm_reason(error)}), using rules")
        if explanation is None:
            explanation = explain_with_rules(results, plan)
    steps.append(f"Explanation written by: {explained_by}")

    return {"question": question, "planned_by": planned_by, "explained_by": explained_by,
            "plan": plan, "retrieval": found, "results": results,
            "explanation": explanation, "steps": steps}


def compare_with_plain_rag(conn, question: str, k: int = 10) -> dict:
    """Same question, two answers: Ripple's graph walk and a plain RAG
    top-k search over the same data written as text (ripple/plain_rag.py)."""
    out = answer(conn, question, use_llm=False)
    return plain_rag.compare(conn, question, out["results"], k)


if __name__ == "__main__":
    args = sys.argv[1:]
    no_llm = "--no-llm" in args
    question = " ".join(a for a in args if a != "--no-llm") or "Port of Rotterdam closed for 3 days"
    conn = db.connect()
    try:
        out = answer(conn, question, use_llm=False if no_llm else None)
    finally:
        conn.close()
    print(f"\nQ: {question}\n")
    for step in out["steps"]:
        print(f"  - {step}")
    print("\n" + out["explanation"] + "\n")
