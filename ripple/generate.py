"""Generate a synthetic supply chain and load it into Relate.

Run with:  python -m ripple.generate

Everything is invented. Port names and coordinates are real places, but the
routes, vessels, shipments, customers and news alerts are random. The random
seed is fixed, so every run produces exactly the same graph.

The script has two halves:
  1. build_dataset()  -> plain Python lists of dicts (no database involved)
  2. load()           -> writes those lists into Relate with Cypher
"""

import math
import random
import shutil
from datetime import date, timedelta

from . import db

SEED = 42
# The story's "today". Fixed so the data does not change from day to day.
SCENARIO_DATE = date(2026, 12, 1)

N_VESSELS = 40
N_SHIPMENTS = 200
N_CUSTOMERS = 60
NEAR_KM = 1500  # two ports closer than this can stand in for each other

# code, name, country, region, latitude, longitude
PORTS = [
    ("CNSHA", "Shanghai", "China", "East Asia", 31.23, 121.47),
    ("CNNGB", "Ningbo", "China", "East Asia", 29.87, 121.55),
    ("CNSZX", "Shenzhen", "China", "East Asia", 22.54, 114.05),
    ("HKHKG", "Hong Kong", "Hong Kong", "East Asia", 22.30, 114.17),
    ("KRPUS", "Busan", "South Korea", "East Asia", 35.10, 129.04),
    ("JPTYO", "Tokyo", "Japan", "East Asia", 35.62, 139.77),
    ("TWKHH", "Kaohsiung", "Taiwan", "East Asia", 22.61, 120.28),
    ("SGSIN", "Singapore", "Singapore", "Southeast Asia", 1.26, 103.82),
    ("VNSGN", "Ho Chi Minh City", "Vietnam", "Southeast Asia", 10.77, 106.70),
    ("MYPKG", "Port Klang", "Malaysia", "Southeast Asia", 3.00, 101.39),
    ("THLCH", "Laem Chabang", "Thailand", "Southeast Asia", 13.08, 100.88),
    ("LKCMB", "Colombo", "Sri Lanka", "South Asia", 6.95, 79.85),
    ("INNSA", "Nhava Sheva", "India", "South Asia", 18.95, 72.95),
    ("AEJEA", "Jebel Ali", "United Arab Emirates", "Middle East", 25.01, 55.06),
    ("EGPSD", "Port Said", "Egypt", "Middle East", 31.26, 32.30),
    ("NLRTM", "Rotterdam", "Netherlands", "North Europe", 51.95, 4.14),
    ("BEANR", "Antwerp", "Belgium", "North Europe", 51.26, 4.40),
    ("DEHAM", "Hamburg", "Germany", "North Europe", 53.54, 9.98),
    ("DEBRV", "Bremerhaven", "Germany", "North Europe", 53.54, 8.58),
    ("FRLEH", "Le Havre", "France", "North Europe", 49.48, 0.11),
    ("GBFXT", "Felixstowe", "United Kingdom", "North Europe", 51.96, 1.35),
    ("ESVLC", "Valencia", "Spain", "Mediterranean", 39.44, -0.32),
    ("ESALG", "Algeciras", "Spain", "Mediterranean", 36.13, -5.44),
    ("ITGOA", "Genoa", "Italy", "Mediterranean", 44.40, 8.92),
    ("GRPIR", "Piraeus", "Greece", "Mediterranean", 37.94, 23.63),
    ("MAPTM", "Tanger Med", "Morocco", "Mediterranean", 35.89, -5.50),
    ("USLAX", "Los Angeles", "United States", "North America", 33.73, -118.26),
    ("USNYC", "New York", "United States", "North America", 40.67, -74.04),
    ("USSAV", "Savannah", "United States", "North America", 32.08, -81.09),
    ("BRSSZ", "Santos", "Brazil", "South America", -23.96, -46.30),
]

# id, name, ordered list of port calls
ROUTES = [
    ("R01", "Asia - North Europe Express", ["CNSHA", "CNNGB", "SGSIN", "EGPSD", "NLRTM", "DEHAM"]),
    ("R02", "Asia - North Europe Loop 2", ["KRPUS", "CNSZX", "MYPKG", "LKCMB", "EGPSD", "BEANR", "GBFXT"]),
    ("R03", "Asia - Mediterranean", ["CNSHA", "HKHKG", "SGSIN", "EGPSD", "GRPIR", "ITGOA", "ESVLC"]),
    ("R04", "Transpacific South", ["CNSZX", "HKHKG", "TWKHH", "USLAX"]),
    ("R05", "Transpacific North", ["CNSHA", "KRPUS", "JPTYO", "USLAX"]),
    ("R06", "Transatlantic", ["NLRTM", "BEANR", "FRLEH", "USNYC", "USSAV"]),
    ("R07", "Intra-Asia", ["JPTYO", "KRPUS", "CNSHA", "TWKHH", "VNSGN", "THLCH", "SGSIN"]),
    ("R08", "India - Gulf - Europe", ["INNSA", "AEJEA", "EGPSD", "ESALG", "NLRTM"]),
    ("R09", "Europe - South America", ["DEHAM", "NLRTM", "FRLEH", "ESALG", "BRSSZ"]),
    ("R10", "Mediterranean - US East", ["ITGOA", "ESVLC", "ESALG", "MAPTM", "USNYC"]),
    ("R11", "Asia - US East via Suez", ["SGSIN", "LKCMB", "EGPSD", "MAPTM", "USNYC", "USSAV"]),
    ("R12", "North Europe Feeder", ["GBFXT", "NLRTM", "DEBRV", "DEHAM"]),
    ("R13", "Southeast Asia - India - Gulf", ["SGSIN", "MYPKG", "LKCMB", "INNSA", "AEJEA"]),
    ("R14", "China - Southeast Asia", ["CNNGB", "CNSZX", "VNSGN", "THLCH", "MYPKG"]),
]

# sku, name, category
PRODUCTS = [
    ("P001", "Lithium battery cells", "Components"),
    ("P002", "Semiconductor wafers", "Components"),
    ("P003", "Display panels", "Components"),
    ("P004", "Electric motors", "Components"),
    ("P005", "Steel coils", "Raw materials"),
    ("P006", "Aluminium ingots", "Raw materials"),
    ("P007", "Cotton yarn", "Raw materials"),
    ("P008", "Plastic resin pellets", "Raw materials"),
    ("P009", "Smartphones", "Electronics"),
    ("P010", "Laptops", "Electronics"),
    ("P011", "E-bikes", "Mobility"),
    ("P012", "Car parts", "Mobility"),
    ("P013", "Tyres", "Mobility"),
    ("P014", "Washing machines", "Appliances"),
    ("P015", "Air conditioners", "Appliances"),
    ("P016", "Sneakers", "Apparel"),
    ("P017", "Winter jackets", "Apparel"),
    ("P018", "Denim jeans", "Apparel"),
    ("P019", "Office furniture", "Home"),
    ("P020", "LED lighting", "Home"),
    ("P021", "Toys", "Consumer goods"),
    ("P022", "Coffee beans", "Food"),
    ("P023", "Frozen seafood", "Food"),
    ("P024", "Pharmaceutical ingredients", "Healthcare"),
    ("P025", "Medical devices", "Healthcare"),
]
# What manufacturers buy (inputs) versus what everybody else buys.
INPUT_CATEGORIES = {"Components", "Raw materials"}

VESSEL_WORDS_A = ["Coral", "Northern", "Pacific", "Silver", "Amber", "Baltic", "Crimson",
                  "Golden", "Iron", "Jade", "Polar", "Royal", "Sapphire", "Emerald", "Ocean"]
VESSEL_WORDS_B = ["Heron", "Star", "Pioneer", "Horizon", "Falcon", "Voyager", "Tide",
                  "Lotus", "Summit", "Breeze", "Meridian", "Harbor", "Crest", "Spirit"]

COMPANY_WORDS = ["Nordwind", "Altamira", "Kestrel", "Brightwell", "Solvane", "Orchard", "Halcyon",
                 "Verdant", "Castellan", "Ironbark", "Lumen", "Tessera", "Windrose", "Marlowe",
                 "Quillon", "Sablewood", "Fennick", "Arclight", "Bellhaven", "Corvane", "Dunmore",
                 "Eastlake", "Greyfield", "Hollis", "Juniper", "Kingsley", "Larkspur", "Meridia",
                 "Oakhurst", "Pinecrest"]
MAKER_SUFFIXES = ["Manufacturing", "Industries", "Works", "Assembly"]
BUYER_SUFFIXES = ["Retail", "Trading", "Distribution", "Stores", "Supply"]
CUSTOMER_COUNTRIES = ["Germany", "France", "Netherlands", "United Kingdom", "Spain", "Italy",
                      "United States", "Brazil", "Japan", "Singapore", "India", "United Arab Emirates"]

# Each template mentions exactly one port, so we know which Port node to link.
ALERT_TEMPLATES = [
    ("high", "Dock workers at the port of {port} begin a 72-hour strike; all container terminals closed."),
    ("high", "Typhoon warning issued near {port}: port authority suspends vessel movements until further notice."),
    ("high", "Port of {port} closed after a crane collapse at the main container terminal."),
    ("medium", "Severe congestion at {port}: average waiting time at anchorage rises to four days."),
    ("medium", "Dense fog halts pilotage at {port}, berthing delays of 24 to 36 hours expected."),
    ("medium", "Customs IT outage in {port} slows cargo clearance and gate operations."),
    ("medium", "Labour talks stall in {port}; unions threaten a walkout next week."),
    ("low", "{port} reports record monthly throughput and opens a new automated berth."),
    ("low", "Scheduled dredging at {port} to restrict deep-draft vessels overnight for one week."),
]
# Alerts about no port at all: retrieval must learn to ignore these.
NOISE_ALERTS = [
    ("low", "Bunker fuel prices fall for the third consecutive week."),
    ("low", "Global container freight rates remain flat ahead of the holiday season."),
    ("medium", "Low water levels reduce transits through the Panama Canal."),
    ("low", "New emissions rules for ocean carriers take effect next quarter."),
    ("low", "Shipping alliance announces a reshuffle of its transpacific services."),
    ("medium", "Container shortage reported by exporters across inland depots."),
]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance between two points on Earth."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(a))


def build_dataset() -> dict:
    rng = random.Random(SEED)
    coords = {code: (lat, lon) for code, _, _, _, lat, lon in PORTS}

    ports = [dict(code=c, name=n, country=co, region=r, lat=lat, lon=lon)
             for c, n, co, r, lat, lon in PORTS]

    # NEAR: pairs of ports close enough to be an alternative for each other.
    near = []
    for i, a in enumerate(PORTS):
        for b in PORTS[i + 1:]:
            km = haversine_km(a[4], a[5], b[4], b[5])
            if km <= NEAR_KM:
                near.append(dict(a=a[0], b=b[0], km=round(km)))

    # Routes: sailing time between two calls is derived from the distance
    # (about 800 km per day), plus one day in port.
    routes, calls = [], []
    day_at = {}  # (route id, port code) -> day of the voyage the vessel arrives
    for rid, name, stops in ROUTES:
        day = 0
        for seq, code in enumerate(stops):
            if seq > 0:
                km = haversine_km(*coords[stops[seq - 1]], *coords[code])
                day += max(1, round(km / 800)) + 1
            day_at[(rid, code)] = day
            calls.append(dict(route=rid, port=code, seq=seq + 1, day=day))
        routes.append(dict(id=rid, name=name, transit_days=day))

    # Vessels: every route gets at least two, the rest are spread at random.
    route_ids = [r[0] for r in ROUTES]
    assigned = route_ids * 2 + [rng.choice(route_ids) for _ in range(N_VESSELS - 2 * len(route_ids))]
    names = rng.sample([f"MV {a} {b}" for a in VESSEL_WORDS_A for b in VESSEL_WORDS_B], N_VESSELS)
    stops_of = {rid: stops for rid, _, stops in ROUTES}
    transit = {r["id"]: r["transit_days"] for r in routes}
    vessels = []
    for i, (rid, name) in enumerate(zip(assigned, names)):
        # Most voyages started some days ago, so on SCENARIO_DATE the vessel is
        # mid-route. A negative value means the voyage starts in the coming
        # days, so first ports of call (Shanghai, ...) also have arrivals ahead.
        started = SCENARIO_DATE - timedelta(days=rng.randint(-6, max(3, transit[rid] - 3)))
        vessels.append(dict(imo=f"IMO{9300000 + i * 137}", name=name, route=rid,
                            capacity_teu=rng.choice([4000, 8000, 12000, 16000, 20000]),
                            voyage_start=started))

    products = [dict(sku=s, name=n, category=c) for s, n, c in PRODUCTS]
    inputs = [p["sku"] for p in products if p["category"] in INPUT_CATEGORIES]
    finished = [p["sku"] for p in products if p["category"] not in INPUT_CATEGORIES]

    # Customers: the first 20 are manufacturers, the other 40 buy finished goods.
    customers = []
    for i in range(N_CUSTOMERS):
        maker = i < 20
        word = COMPANY_WORDS[i % len(COMPANY_WORDS)]
        suffix = rng.choice(MAKER_SUFFIXES if maker else BUYER_SUFFIXES)
        customers.append(dict(
            id=f"C{i + 1:03d}", name=f"{word} {suffix}",
            kind="manufacturer" if maker else "buyer",
            tier=rng.choices(["strategic", "key", "standard"], weights=[2, 3, 5])[0],
            country=rng.choice(CUSTOMER_COUNTRIES),
            sla_days=rng.choice([0, 1, 2, 3, 5]),  # delay the customer tolerates
        ))
    makers = [c["id"] for c in customers if c["kind"] == "manufacturer"]
    buyers = [c["id"] for c in customers if c["kind"] == "buyer"]

    # SUPPLIES: a manufacturer feeds 1 to 3 buyers. If its inputs arrive
    # late, those buyers are exposed too. This is the second-order "ripple".
    supplies = [dict(a=m, b=b) for m in makers for b in rng.sample(buyers, rng.randint(1, 3))]

    # Shipments: each one travels on a vessel between two calls of its route.
    shipments, contains = [], []
    for i in range(N_SHIPMENTS):
        v = rng.choice(vessels)
        stops = stops_of[v["route"]]
        o = rng.randrange(len(stops) - 1)
        d = rng.randrange(o + 1, len(stops))
        departure = v["voyage_start"] + timedelta(days=day_at[(v["route"], stops[o])])
        eta = v["voyage_start"] + timedelta(days=day_at[(v["route"], stops[d])])
        if eta < SCENARIO_DATE:
            status = "delivered"
        elif departure <= SCENARIO_DATE:
            status = "in_transit"
        else:
            status = "booked"
        customer = rng.choice(customers)
        sid = f"S{i + 1:04d}"
        shipments.append(dict(
            id=sid, vessel=v["imo"], origin=stops[o], destination=stops[d],
            customer=customer["id"], departure=departure, eta=eta, status=status,
            priority=rng.choices(["standard", "express", "critical"], weights=[6, 3, 1])[0],
            value_usd=rng.randrange(20_000, 900_000, 5_000),
        ))
        pool = inputs if customer["kind"] == "manufacturer" else finished
        for sku in rng.sample(pool, rng.randint(1, 3)):
            contains.append(dict(shipment=sid, sku=sku, qty=rng.randrange(50, 2000, 50)))

    # News alerts: the text part of the dataset, used for retrieval in M3.
    port_name = {p["code"]: p["name"] for p in ports}
    alerts, mentions = [], []
    port_cycle = rng.sample(list(port_name), len(port_name))
    for i in range(42):
        code = port_cycle[i % len(port_cycle)]
        severity, text = rng.choice(ALERT_TEMPLATES)
        aid = f"A{i + 1:03d}"
        alerts.append(dict(id=aid, text=text.format(port=port_name[code]), severity=severity,
                           date=SCENARIO_DATE - timedelta(days=rng.randint(0, 20))))
        mentions.append(dict(alert=aid, port=code))
    for j, (severity, text) in enumerate(NOISE_ALERTS):
        alerts.append(dict(id=f"A{43 + j:03d}", text=text, severity=severity,
                           date=SCENARIO_DATE - timedelta(days=rng.randint(0, 20))))

    return dict(ports=ports, near=near, routes=routes, calls=calls, vessels=vessels,
                products=products, customers=customers, supplies=supplies,
                shipments=shipments, contains=contains, alerts=alerts, mentions=mentions)


# Each statement receives a list of dicts as $rows and loops over it with
# UNWIND, so one call creates all nodes (or relationships) of one kind.
LOAD_STEPS = [
    ("ports", "UNWIND $rows AS r CREATE (:Port {code: r.code, name: r.name, country: r.country, "
              "region: r.region, lat: r.lat, lon: r.lon})"),
    ("routes", "UNWIND $rows AS r CREATE (:Route {id: r.id, name: r.name, transit_days: r.transit_days})"),
    ("products", "UNWIND $rows AS r CREATE (:Product {sku: r.sku, name: r.name, category: r.category})"),
    ("customers", "UNWIND $rows AS r CREATE (:Customer {id: r.id, name: r.name, kind: r.kind, "
                  "tier: r.tier, country: r.country, sla_days: r.sla_days})"),
    ("alerts", "UNWIND $rows AS r CREATE (:Alert {id: r.id, text: r.text, severity: r.severity, date: r.date})"),
    ("calls", "UNWIND $rows AS r MATCH (rt:Route {id: r.route}), (p:Port {code: r.port}) "
              "CREATE (rt)-[:CALLS_AT {seq: r.seq, day: r.day}]->(p)"),
    ("near", "UNWIND $rows AS r MATCH (a:Port {code: r.a}), (b:Port {code: r.b}) "
             "CREATE (a)-[:NEAR {km: r.km}]->(b), (b)-[:NEAR {km: r.km}]->(a)"),
    ("vessels", "UNWIND $rows AS r MATCH (rt:Route {id: r.route}) "
                "CREATE (:Vessel {imo: r.imo, name: r.name, capacity_teu: r.capacity_teu, "
                "voyage_start: r.voyage_start})-[:SAILS]->(rt)"),
    ("supplies", "UNWIND $rows AS r MATCH (a:Customer {id: r.a}), (b:Customer {id: r.b}) "
                 "CREATE (a)-[:SUPPLIES]->(b)"),
    ("shipments", "UNWIND $rows AS r "
                  "MATCH (v:Vessel {imo: r.vessel}), (o:Port {code: r.origin}), "
                  "(d:Port {code: r.destination}), (c:Customer {id: r.customer}) "
                  "CREATE (s:Shipment {id: r.id, departure: r.departure, eta: r.eta, status: r.status, "
                  "priority: r.priority, value_usd: r.value_usd}), "
                  "(s)-[:ON_VESSEL]->(v), (s)-[:ORIGIN]->(o), (s)-[:DESTINATION]->(d), (s)-[:FOR]->(c)"),
    ("contains", "UNWIND $rows AS r MATCH (s:Shipment {id: r.shipment}), (p:Product {sku: r.sku}) "
                 "CREATE (s)-[:CONTAINS {qty: r.qty}]->(p)"),
    ("mentions", "UNWIND $rows AS r MATCH (a:Alert {id: r.alert}), (p:Port {code: r.port}) "
                 "CREATE (a)-[:MENTIONS]->(p)"),
]


def load(data: dict) -> None:
    # Always rebuild from scratch so the store matches the script exactly.
    if db.STORE_PATH.exists():
        shutil.rmtree(db.STORE_PATH)
    conn = db.connect(read_only=False)
    try:
        db.create_schema(conn)
        for key, cypher in LOAD_STEPS:
            conn.execute(cypher, {"rows": data[key]})
        print("Nodes:")
        for row in conn.execute("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label"):
            print(f"  {row['label']:<10}{row['n']:>5}")
        print("Relationships:")
        for row in conn.execute("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n ORDER BY type"):
            print(f"  {row['type']:<12}{row['n']:>5}")
    finally:
        conn.close()  # close() checkpoints: the graph is written to disk here
    print(f"Store written to {db.STORE_PATH}")


if __name__ == "__main__":
    load(build_dataset())
