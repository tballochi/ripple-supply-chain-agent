"""Drawing the paths the agent returns: a static Graphviz diagram (works
offline) and an interactive vis-network graph (loaded from a CDN)."""

import json

# One colour per node label, reused in every graph drawing.
COLORS = {"Port": "#E4572E", "Route": "#F3A712", "Vessel": "#4C9F70",
          "Shipment": "#3A7CA5", "Customer": "#7B5EA7"}


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


VIS_NETWORK = "https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js"


def path_to_vis_html(paths: list, height: int = 560) -> str:
    """The same paths as an interactive vis-network graph: drag, zoom, hover
    for details, click a node to highlight its neighbours. Nodes keep the
    column where they first appear (disruption on the left, customers and the
    companies they supply further right)."""
    nodes, edges = {}, {}
    for path_nodes, rels in paths:
        # A ripple path starts at a shipment already drawn: continue from its column.
        first = f"{path_nodes[0]['label']}:{path_nodes[0]['name']}"
        base = nodes[first]["level"] if first in nodes else 0
        for index, node in enumerate(path_nodes):
            key, level = f"{node['label']}:{node['name']}", base + index
            if key not in nodes:
                nodes[key] = {"id": key, "label": node["name"], "level": level,
                              "title": f"{node['label']}: {node['name']}",
                              "color": COLORS[node["label"]], "font": {"color": "#ffffff"}}
        for i, rel in enumerate(rels):
            a = f"{path_nodes[i]['label']}:{path_nodes[i]['name']}"
            b = f"{path_nodes[i + 1]['label']}:{path_nodes[i + 1]['name']}"
            start, end = (a, b) if rel["forward"] else (b, a)  # the direction stored in the graph
            edges[(start, end, rel["type"])] = {"from": start, "to": end, "label": rel["type"],
                                                "arrows": "to"}
    data = json.dumps({"nodes": list(nodes.values()), "edges": list(edges.values())})
    return f"""<div id="g" style="height:{height - 10}px"></div>
<script src="{VIS_NETWORK}"></script>
<script>
const data = {data};
const nodes = new vis.DataSet(data.nodes), edges = new vis.DataSet(data.edges);
const network = new vis.Network(document.getElementById("g"), {{nodes, edges}}, {{
  layout: {{hierarchical: {{direction: "LR", levelSeparation: 170, nodeSpacing: 40}}}},
  physics: false,
  nodes: {{shape: "box", margin: 8, borderWidth: 0, shapeProperties: {{borderRadius: 6}}, font: {{size: 13}}}},
  edges: {{color: {{color: "#888888", highlight: "#bbbbbb"}}, font: {{size: 10, color: "#999999", strokeWidth: 0}},
          smooth: {{type: "cubicBezierHorizontal"}}}},
  interaction: {{hover: true, tooltipDelay: 80}},
}});
// Show the whole graph, also when the tab holding it opens (it starts hidden, 0 px wide).
network.once("afterDrawing", () => network.fit({{animation: false}}));
network.on("resize", () => network.fit({{animation: false}}));
// Click a node: keep it and its neighbours in colour, dim the rest.
network.on("click", (event) => {{
  const keep = event.nodes.length ? new Set([event.nodes[0], ...network.getConnectedNodes(event.nodes[0])]) : null;
  nodes.update(data.nodes.map(n => ({{id: n.id, opacity: !keep || keep.has(n.id) ? 1 : 0.15}})));
}});
</script>"""
