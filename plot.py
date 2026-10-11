"""Render the call graph as Graphviz DOT and interactive HTML."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from pathlib import Path

import networkx as nx

GRAPH_PATH = Path("output/call_graph.json")
OUT_DIR = Path("output")
WEB_OUT_DIR = Path("dist")
WEB_DIR = Path(__file__).resolve().parent / "web"


def node_initials(name: str) -> str:
    """Short label for zoomed-out view, e.g. draw_window_preferences → dwp."""
    parts = re.split(r"[_:]+", name)
    letters: list[str] = []
    for part in parts:
        if not part:
            continue
        # Split CamelCase / ALLCAPS runs / digits inside a segment.
        chunks = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", part)
        if len(chunks) > 1:
            letters.extend(chunk[0].lower() for chunk in chunks if chunk)
        else:
            letters.append(part[0].lower())
    return "".join(letters) if letters else name[:3].lower()


def load_graph(path: Path) -> nx.DiGraph:
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = nx.DiGraph()
    for node in data["nodes"]:
        node_id = node["id"]
        attrs = {k: v for k, v in node.items() if k != "id"}
        graph.add_node(node_id, **attrs)
    for edge in data["edges"]:
        graph.add_edge(edge["source"], edge["target"], weight=int(edge["weight"]))
    return graph


def subgraph_from_root(graph: nx.DiGraph, root: str | None) -> nx.DiGraph:
    if root is None:
        return graph
    if root not in graph:
        raise SystemExit(f"Unknown root node: {root}")
    nodes = nx.descendants(graph, root) | {root}
    return graph.subgraph(nodes).copy()


def _node_dims(name: str, lines: int) -> tuple[float, float]:
    """Graphviz minimum width/height in inches from lines + label length."""
    lines = max(1, lines)
    width = max(0.9, 0.11 * len(name), 0.35 + 0.01 * math.sqrt(lines) * 4)
    height = max(0.45, 0.3 + 0.01 * math.sqrt(lines) * 3)
    return min(width, 4.5), min(height, 2.5)


def write_dot(graph: nx.DiGraph, path: Path) -> None:
    lines = ["digraph call_graph {"]
    lines.append("  graph [")
    lines.append("    rankdir=TB,")
    lines.append("    bgcolor=white,")
    lines.append("    nodesep=0.8,")
    lines.append("    ranksep=1.4,")
    lines.append("    overlap=false,")
    lines.append("    splines=true,")
    lines.append("    outputorder=edgesfirst,")
    lines.append("  ];")
    lines.append(
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11];'
    )
    lines.append('  edge [fontname="Helvetica", fontsize=9, color="#666666"];')

    for name, attrs in graph.nodes(data=True):
        n_lines = int(attrs.get("lines", 1) or 1)
        code_lines = int(attrs.get("code_lines", n_lines) or n_lines)
        kind = attrs.get("kind", "function")
        width, height = _node_dims(str(name), n_lines)
        fill = "#cfe8ff" if kind == "function" else "#ffe6b3"
        label = name.replace("\\", "\\\\").replace('"', '\\"')
        tip = f"{name}\\nlines={n_lines}, code_lines={code_lines}".replace('"', '\\"')
        # width/height are minima; omit fixedsize so labels stay readable.
        lines.append(
            f'  "{label}" ['
            f'label="{label}", '
            f"width={width:.3f}, height={height:.3f}, "
            f'fillcolor="{fill}", '
            f'tooltip="{tip}"'
            f"];"
        )

    for src, dst, attrs in graph.edges(data=True):
        weight = int(attrs.get("weight", 1))
        penwidth = min(6.0, 0.6 + 0.25 * math.sqrt(weight))
        src_l = str(src).replace('"', '\\"')
        dst_l = str(dst).replace('"', '\\"')
        lines.append(
            f'  "{src_l}" -> "{dst_l}" ['
            f'label="{weight}", '
            f"penwidth={penwidth:.2f}, "
            f'labeltooltip="{weight} calls"'
            f"];"
        )

    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Distinct categorical colors for Louvain communities (Wikipedia-map style).
_COMMUNITY_COLORS = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
    "#1f9e89",
    "#d67229",
    "#6b4c9a",
    "#86bcb6",
    "#8cd17d",
]


def detect_communities(graph: nx.DiGraph) -> dict[str, int]:
    from networkx.algorithms.community import louvain_communities

    undirected = graph.to_undirected()
    communities = louvain_communities(undirected, weight="weight", seed=42)
    ordered = sorted(communities, key=len, reverse=True)
    mapping: dict[str, int] = {}
    for idx, community in enumerate(ordered):
        for node in community:
            mapping[node] = idx
    return mapping


def write_interactive_html(graph: nx.DiGraph, out_dir: Path, *, suffix: str = "") -> Path:
    """Force-directed interactive map with community colors and zoom LOD.

    Writes index{suffix}.html, graph-data{suffix}.js, style.css, and script.js
    into out_dir (static assets copied from web/).
    """
    communities = detect_communities(graph)
    nodes_payload = []
    importances: list[float] = []

    for name, attrs in graph.nodes(data=True):
        n_lines = max(1, int(attrs.get("lines", 1) or 1))
        code_lines = int(attrs.get("code_lines", n_lines) or n_lines)
        kind = attrs.get("kind", "function")
        out_deg = graph.out_degree(name)
        out_calls = int(graph.out_degree(name, weight="weight"))
        in_deg = graph.in_degree(name)
        in_calls = int(graph.in_degree(name, weight="weight"))
        # Prefer large functions that fan out to many callees.
        importance = math.sqrt(n_lines) * (1.0 + out_deg) + 0.5 * in_deg
        if kind == "object_event":
            importance *= 1.35
        importances.append(importance)

        community = communities.get(name, 0)
        color = _COMMUNITY_COLORS[community % len(_COMMUNITY_COLORS)]
        size = max(6.0, 4.0 + math.sqrt(n_lines) * 2.2 + out_deg * 0.8)
        size = min(120.0, size)
        # Structured tooltip fields — rendered as HTML in the page (vis title is plain text).
        nodes_payload.append(
            {
                "id": name,
                "label": name,
                "initials": node_initials(name),
                "tooltip": {
                    "name": name,
                    "community": community,
                    "kind": kind,
                    "lines": n_lines,
                    "code_lines": code_lines,
                    "out_degree": out_deg,
                    "out_calls": out_calls,
                    "in_degree": in_deg,
                    "in_calls": in_calls,
                    "file": attrs.get("file", "") or "",
                },
                # Store community under a non-vis key. vis-network's `group` field
                # applies its own palette and would disagree with caller edge colors.
                "community": community,
                "color": {
                    "background": color,
                    "border": "#222222" if kind == "object_event" else color,
                    "highlight": {
                        "background": color,
                        "border": "#111111",
                    },
                },
                "size": size,
                "importance": importance,
                "font": {"face": "Helvetica"},
                "borderWidth": 3 if kind == "object_event" else 1,
            }
        )

    # Percentile thresholds for zoom LOD (high / mid / all).
    ranked = sorted(importances)

    def pct(p: float) -> float:
        if not ranked:
            return 0.0
        return ranked[min(len(ranked) - 1, int(p * (len(ranked) - 1)))]

    thresholds = {
        "high": pct(0.82),
        "mid": pct(0.55),
        "low": pct(0.0),
    }

    imp_by_id = {n["id"]: n["importance"] for n in nodes_payload}
    color_by_id = {n["id"]: n["color"]["background"] for n in nodes_payload}
    community_by_id = {n["id"]: n["community"] for n in nodes_payload}
    edges_payload = []
    for src, dst, attrs in graph.edges(data=True):
        weight = int(attrs.get("weight", 1))
        edges_payload.append(
            {
                "id": f"{src}->{dst}",
                "from": src,
                "to": dst,
                "value": weight,
                "title": f"{weight} calls",
                "width": min(7.0, 0.4 + 0.35 * math.sqrt(weight)),
                "importance": min(imp_by_id[src], imp_by_id[dst]),
                # Edge color follows the caller (source) community.
                "caller_color": color_by_id[src],
                "cross_community": community_by_id[src] != community_by_id[dst],
            }
        )

    data = {
        "nodes": nodes_payload,
        "edges": edges_payload,
        "thresholds": thresholds,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    data_name = f"graph-data{suffix}.js"
    html_path = out_dir / f"index{suffix}.html"
    (out_dir / data_name).write_text(
        f"window.GRAPH_DATA = {json.dumps(data, ensure_ascii=False)};\n",
        encoding="utf-8",
    )
    shutil.copy2(WEB_DIR / "style.css", out_dir / "style.css")
    shutil.copy2(WEB_DIR / "script.js", out_dir / "script.js")
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace(
        "__GRAPH_DATA_SRC__",
        data_name,
    )
    html_path.write_text(html, encoding="utf-8")
    return html_path



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph",
        type=Path,
        default=GRAPH_PATH,
        help="Path to call_graph.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_DIR,
        help="Directory for .dot and other non-web artifacts",
    )
    parser.add_argument(
        "--web-out",
        type=Path,
        default=WEB_OUT_DIR,
        help="Directory for interactive HTML site assets",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help="Optional root node; plot only that node and its descendants",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Skip interactive HTML",
    )
    args = parser.parse_args()

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    graph = subgraph_from_root(load_graph(args.graph), args.root)
    suffix = f"_{args.root.replace(':', '_')}" if args.root else ""

    dot_path = out_dir / f"call_graph{suffix}.dot"

    write_dot(graph, dot_path)
    print(
        f"Wrote {dot_path} ({graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)"
    )

    if not args.no_html:
        html_path = write_interactive_html(graph, args.web_out, suffix=suffix)
        print(f"Wrote {html_path} (+ style.css, script.js, graph-data{suffix}.js)")


if __name__ == "__main__":
    main()
