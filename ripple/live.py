"""Live mode: today's real events, simulated on Ripple's network.

Try it (needs internet):  python -m ripple.live

Two free sources, no key needed:

  - GDACS (UN / European Commission): tropical cyclones, earthquakes,
    tsunamis, floods and volcanoes, with a position and an alert level.
    An event touches the ports within a radius that depends on its kind.
  - Google News RSS search: headlines about strikes, closures and
    congestion. A headline touches the ports it names.

Each real event becomes a (:LiveAlert)-[:MENTIONS]->(:Port) in the workspace
graph (.ripple/workspace.relate, never in the committed store), so the last
news fetched stays available offline. The radar then asks the question it
would ask for a synthetic alert: what if these ports closed, on the network
as it stands on its own "today"? The ports and their positions are real; the
vessels, shipments and customers behind them remain synthetic.
"""

import email.utils
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta

import requests

from . import db, retrieval, workspace
from .agent import parse_days
from .generate import PORT_NAMES, SCENARIO_DATE
from .radar import DEFAULT_DAYS, impact_row

GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
NEWS_URL = "https://news.google.com/rss/search"
USER_AGENT = "Mozilla/5.0 (compatible; ripple-supply-chain-demo/1.0)"
TIMEOUT = 20
LOOKBACK_DAYS = 3

# How far from its centre a natural hazard can stop a port, in km.
HAZARD_RADIUS_KM = {"TC": 500, "TS": 500, "EQ": 300, "FL": 150, "VO": 100}
HAZARD_NAMES = {"TC": "tropical cyclone", "TS": "tsunami", "EQ": "earthquake", "FL": "flood", "VO": "volcano"}
# GDACS colours. Green events are routine and are not expected to close a port.
GDACS_SEVERITY = {"Red": "high", "Orange": "medium"}

NEWS_QUERIES = [
    "port strike",
    "port closed OR port closure OR port shut",
    "port congestion OR terminal suspended OR terminal outage",
    "typhoon port OR cyclone port OR storm port",
]
# The words a headline must contain to be about a disruption at all.
DISRUPTION = re.compile(
    r"\b(strikes?|striking|walk-?outs?|closed|closures?|clos(?:e|es|ing)|shut\w*|suspend\w*|halt\w*"
    r"|congest\w*|blockade\w*|outages?|cyber\w*|ransomware|typhoon|cyclone|hurricane|storm|flood\w*"
    r"|earthquake|fire|explosion|protest\w*|disrupt\w*|delays?)\b", re.IGNORECASE)
# A threat is not yet an outage: "strike looms", "could close", "braces for".
THREAT = re.compile(
    r"\b(looms?|looming|threat\w*|warn\w*|could|may|might|possible|risk|braces?|talks|vote|ballot"
    r"|planned|potential|countdown|ahead|prepare\w*|likely|prevent\w*)\b", re.IGNORECASE)
# Other names used in headlines for the ports of the graph.
ALIASES = {
    "USLAX": ["Los Angeles", "Long Beach", "San Pedro Bay", "LA-Long Beach", "Southern California port"],
    "CNSZX": ["Shenzhen", "Yantian", "Shekou"],
    "CNNGB": ["Ningbo", "Zhoushan"],
    "KRPUS": ["Busan", "Pusan"],
    "INNSA": ["Nhava Sheva", "JNPT", "Jawaharlal Nehru Port"],
    "EGPSD": ["Port Said", "Suez Canal"],
    "MAPTM": ["Tanger Med", "Tanger-Med", "Tangier"],
    "BEANR": ["Antwerp", "Antwerp-Bruges"],
    "VNSGN": ["Ho Chi Minh City", "Cat Lai", "Saigon port"],
    "ITGOA": ["Genoa", "Genova"],
    "USNYC": ["New York", "Port Newark", "New York and New Jersey"],
    "AEJEA": ["Jebel Ali"],
    "MYPKG": ["Port Klang", "Westports"],
    "THLCH": ["Laem Chabang"],
}


def port_patterns() -> dict:
    """code -> one regular expression matching any of its names."""
    names = {code: [name] for code, name, _, _ in PORT_NAMES}
    for code, extra in ALIASES.items():
        names[code] = list(dict.fromkeys(names[code] + extra))
    return {code: re.compile(r"\b(" + "|".join(re.escape(n) for n in ns) + r")\b") for code, ns in names.items()}


PATTERNS = port_patterns()
PORT_NAME = {code: name for code, name, _, _ in PORT_NAMES}


def _id(source: str, key: str) -> str:
    return f"{source}-" + hashlib.sha1(key.encode()).hexdigest()[:10]


# ------------------------------------------------------------------ sources

def hazards_from_gdacs(payload: dict, conn) -> list[dict]:
    """GDACS GeoJSON -> live alerts for orange and red events near a port."""
    alerts = []
    for feature in payload.get("features", []):
        p = feature["properties"]
        severity = GDACS_SEVERITY.get(p.get("alertlevel"))
        radius = HAZARD_RADIUS_KM.get(p.get("eventtype"))
        if not severity or not radius or feature["geometry"]["type"] != "Point":
            continue
        lon, lat = feature["geometry"]["coordinates"][:2]
        ports = retrieval.ports_near(conn, lat, lon, radius)
        if not ports:
            continue
        started = datetime.fromisoformat(p["fromdate"]).date()
        ended = datetime.fromisoformat(p["todate"]).date()
        alerts.append({
            "id": _id("gdacs", f"{p['eventtype']}{p['eventid']}"), "source": "GDACS",
            "kind": HAZARD_NAMES[p["eventtype"]], "severity": severity, "date": ended,
            "text": f"{p['alertlevel']} alert: {p.get('htmldescription') or p['name']}",
            "url": (p.get("url") or {}).get("report", ""),
            "days": max(1, (ended - started).days + 1),
            "ports": [r["code"] for r in ports],
        })
    return alerts


def classify(title: str) -> dict | None:
    """A headline -> the ports it names and how serious it sounds, or None."""
    headline = title.rsplit(" - ", 1)[0]  # drop " - Publisher"
    codes = [code for code, pattern in PATTERNS.items() if pattern.search(headline)]
    if not codes or not DISRUPTION.search(headline):
        return None
    severity = "medium" if THREAT.search(headline) else "high"
    return {"ports": codes, "severity": severity,
            "days": parse_days(headline) or DEFAULT_DAYS[severity], "headline": headline}


def headlines_from_rss(xml_text: str, today: date, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    """Google News RSS -> live alerts for recent headlines naming a port."""
    alerts = []
    for item in ET.fromstring(xml_text).iter("item"):
        title, link, published = item.findtext("title") or "", item.findtext("link") or "", item.findtext("pubDate")
        if not published:
            continue
        day = email.utils.parsedate_to_datetime(published).date()
        if not today - timedelta(days=lookback_days) <= day <= today:
            continue
        found = classify(title)
        if found:
            alerts.append({"id": _id("news", title), "source": item.findtext("source") or "News",
                           "kind": "news", "severity": found["severity"], "date": day,
                           "text": found["headline"], "url": link, "days": found["days"],
                           "ports": found["ports"]})
    return alerts


def fetch(conn, today: date | None = None) -> tuple[list[dict], list[str]]:
    """Ask both sources. Returns (alerts, problems); a source that fails is skipped."""
    today = today or datetime.now(UTC).date()
    alerts, problems, seen = [], [], set()
    headers = {"User-Agent": USER_AGENT}
    try:
        reply = requests.get(GDACS_URL, headers=headers, timeout=TIMEOUT, params={
            "eventlist": ";".join(HAZARD_RADIUS_KM), "alertlevel": "orange;red", "pagesize": 100,
            "fromdate": (today - timedelta(days=LOOKBACK_DAYS)).isoformat(), "todate": today.isoformat()})
        reply.raise_for_status()
        alerts += hazards_from_gdacs(reply.json() if reply.content else {}, conn)
    except (requests.RequestException, ValueError) as error:
        problems.append(f"GDACS: {error.__class__.__name__}")
    for query in NEWS_QUERIES:
        try:
            reply = requests.get(NEWS_URL, headers=headers, timeout=TIMEOUT,
                                 params={"q": f"{query} when:{LOOKBACK_DAYS}d", "hl": "en-US", "gl": "US",
                                         "ceid": "US:en"})
            reply.raise_for_status()
            for alert in headlines_from_rss(reply.text, today):
                if alert["id"] not in seen:
                    seen.add(alert["id"])
                    alerts.append(alert)
        except (requests.RequestException, ET.ParseError) as error:
            problems.append(f"Google News: {error.__class__.__name__}")
            break
    return alerts, problems


# ------------------------------------------------------- workspace storage

def store(alerts: list[dict]) -> None:
    """Write live alerts to the workspace graph, each linked to its ports."""
    if not alerts:
        return
    workspace.write("""
        UNWIND $rows AS r
        MERGE (a:LiveAlert {id: r.id})
        SET a.source = r.source, a.kind = r.kind, a.severity = r.severity, a.date = r.date,
            a.text = r.text, a.url = r.url, a.days = r.days, a.fetched_at = $now
        WITH a, r
        UNWIND r.ports AS code
        MATCH (p:Port {code: code})
        MERGE (a)-[:MENTIONS]->(p)
    """, {"rows": alerts, "now": datetime.now(UTC)})


def stored(today: date, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    return workspace.read("""
        MATCH (a:LiveAlert)-[:MENTIONS]->(p:Port)
        WHERE a.date >= $since AND a.date <= $today
        WITH a, p ORDER BY p.code
        RETURN a.id AS id, a.source AS source, a.kind AS kind, a.severity AS severity, a.date AS date,
               a.text AS text, a.url AS url, a.days AS days, collect(p.code) AS ports
        ORDER BY date DESC, id
    """, {"since": today - timedelta(days=lookback_days), "today": today})


def refresh(conn, today: date | None = None) -> list[str]:
    """Fetch the news and keep it in the workspace. Returns the problems met."""
    alerts, problems = fetch(conn, today)
    store(alerts)
    return problems


# -------------------------------------------------------------------- radar

def scan(conn, today: date | None = None) -> list[dict]:
    """One row per set of ports in the news, highest risk first.

    Several headlines about the same ports (ten articles on one strike) make
    one row, with the most serious reading and the longest duration. The
    closure is simulated from the network's own today, SCENARIO_DATE.
    """
    today = today or datetime.now(UTC).date()
    groups = {}
    for alert in stored(today):
        key = tuple(sorted(alert["ports"]))
        groups.setdefault(key, []).append(alert)
    rows = []
    for codes, alerts in groups.items():
        alerts.sort(key=lambda a: (a["severity"] != "high", -a["date"].toordinal()))
        days = max(a["days"] for a in alerts)
        names = [PORT_NAME[c] for c in codes]
        rows.append({
            **impact_row(conn, list(codes), names, days, SCENARIO_DATE),
            "id": alerts[0]["id"], "text": alerts[0]["text"], "severity": alerts[0]["severity"],
            "date": alerts[0]["date"], "source": alerts[0]["source"], "kind": alerts[0]["kind"],
            "port_codes": list(codes), "port_names": names, "days_total": days, "days_remaining": days,
            "headlines": [{"text": a["text"], "url": a["url"], "source": a["source"], "date": a["date"]}
                          for a in alerts[:3]],
            "articles": len(alerts),
        })
    rows.sort(key=lambda r: (-r["value_beyond_tolerance_usd"], -r["shipments"], r["id"]))
    return rows


if __name__ == "__main__":
    conn = db.connect()
    try:
        problems = refresh(conn)
        radar = scan(conn)
    finally:
        conn.close()
    for problem in problems:
        print("Skipped:", problem)
    print(f"\nLive radar, {datetime.now(UTC):%d %B %Y}: {len(radar)} real events touching the network "
          f"(impact simulated on the network of {SCENARIO_DATE})\n")
    for r in radar:
        print(f"  ${r['value_beyond_tolerance_usd']:>10,} beyond tolerance  {r['shipments']:>2} late  "
              f"{r['days_total']}d  {r['severity']:<6} {', '.join(r['port_names'])}: {r['text'][:70]} "
              f"({r['articles']} article{'s' * (r['articles'] > 1)})")
