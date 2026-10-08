"""Render the call graph as a large PNG (Graphviz) and interactive HTML (pyvis)."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import deque
from pathlib import Path

import networkx as nx

GRAPH_PATH = Path("output/call_graph.json")
OUT_DIR = Path("output")


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


def render_with_graphviz(dot_path: Path, out_path: Path, fmt: str) -> None:
    """Render via pygraphviz (wheels bundle Graphviz; no system `dot` install needed)."""
    import pygraphviz as pgv

    # SVG stays full-resolution (cairo PNG downscales huge graphs).
    # PNG uses a modest DPI; Graphviz may still scale if the bitmap exceeds limits.
    graph = pgv.AGraph(filename=str(dot_path))
    args = "-Gdpi=150" if fmt == "png" else ""
    graph.draw(path=str(out_path), format=fmt, prog="dot", args=args)


def render_png_matplotlib_fallback(graph: nx.DiGraph, png_path: Path) -> None:
    """Layered + spring refine when Graphviz is unavailable."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    layers = _assign_layers(graph)
    nx.set_node_attributes(graph, layers, "layer")
    pos = nx.multipartite_layout(graph, subset_key="layer", align="horizontal")
    # Stretch layers horizontally so wide ranks are less crushed.
    for node, (x, y) in list(pos.items()):
        pos[node] = (x * (1.0 + 0.15 * layers[node]), y)
    pos = nx.spring_layout(graph, pos=pos, iterations=40, seed=42, weight=None, k=2.0)

    sizes = [
        min(5000, max(100, 14 * max(1, int(graph.nodes[n].get("lines", 1)))))
        for n in graph.nodes
    ]
    colors = [
        "#ffe6b3" if graph.nodes[n].get("kind") == "object_event" else "#cfe8ff"
        for n in graph.nodes
    ]

    plt.figure(figsize=(48, 28))
    nx.draw_networkx_nodes(graph, pos, node_size=sizes, node_color=colors, alpha=0.95)
    nx.draw_networkx_labels(graph, pos, font_size=6)
    nx.draw_networkx_edges(
        graph,
        pos,
        arrows=True,
        arrowsize=10,
        width=0.5,
        alpha=0.3,
        node_size=sizes,
    )
    edge_labels = {(u, v): d.get("weight", 1) for u, v, d in graph.edges(data=True)}
    nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=5)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(png_path, dpi=200, bbox_inches="tight")
    plt.close()


def _assign_layers(graph: nx.DiGraph) -> dict[str, int]:
    roots = [
        n
        for n, attrs in graph.nodes(data=True)
        if attrs.get("kind") == "object_event" or graph.in_degree(n) == 0
    ]
    if not roots:
        roots = [next(iter(graph.nodes))]

    layers: dict[str, int | None] = {n: None for n in graph.nodes}
    queue: deque[str] = deque()
    for root in roots:
        layers[root] = 0
        queue.append(root)

    while queue:
        node = queue.popleft()
        assert layers[node] is not None
        next_layer = layers[node] + 1
        for succ in graph.successors(node):
            if layers[succ] is None or next_layer < layers[succ]:
                layers[succ] = next_layer
                queue.append(succ)

    max_layer = max(
        (layer for layer in layers.values() if layer is not None), default=0
    )
    return {
        n: (max_layer + 1 if layer is None else layer) for n, layer in layers.items()
    }


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


def write_interactive_html(graph: nx.DiGraph, html_path: Path) -> None:
    """Force-directed interactive map with community colors and zoom LOD."""
    communities = detect_communities(graph)
    nodes_payload = []
    importances: list[float] = []

    for name, attrs in graph.nodes(data=True):
        n_lines = max(1, int(attrs.get("lines", 1) or 1))
        code_lines = int(attrs.get("code_lines", n_lines) or n_lines)
        kind = attrs.get("kind", "function")
        out_deg = graph.out_degree(name)
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

    html = _INTERACTIVE_HTML_TEMPLATE.replace(
        "__GRAPH_DATA__",
        json.dumps(data, ensure_ascii=False),
    )
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")


_INTERACTIVE_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>NBS call graph</title>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <style>
    html, body { margin: 0; height: 100%; background: #f7f5f0; font-family: Helvetica, Arial, sans-serif; }
    #graph { width: 100%; height: 100%; }
    #hud {
      position: fixed; left: 12px; top: 12px; z-index: 5;
      background: rgba(255,255,255,0.92); border: 1px solid #ccc;
      border-radius: 8px; padding: 10px 12px; max-width: 340px;
      font-size: 13px; line-height: 1.35; color: #222;
      box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    }
    #hud .hud-header {
      display: flex; align-items: center; justify-content: space-between; gap: 8px;
    }
    #hud .title { font-weight: 700; flex: 1; min-width: 0; }
    #hud #hudToggle {
      margin: 0; padding: 2px 7px; font-size: 11px; line-height: 1.2;
      cursor: pointer; border: 1px solid #bbb; border-radius: 4px; background: #fff;
      flex: 0 0 auto;
    }
    #hudBody {
      display: grid;
      grid-template-rows: 1fr;
      transition: grid-template-rows 200ms ease-in-out;
    }
    #hud.collapsed #hudBody { grid-template-rows: 0fr; }
    #hudBody > .hud-body-inner {
      overflow: hidden;
      min-height: 0;
      opacity: 1;
      transition: opacity 200ms ease-in-out, margin-top 200ms ease-in-out;
      margin-top: 4px;
    }
    #hud.collapsed #hudBody > .hud-body-inner {
      opacity: 0;
      margin-top: 0;
    }
    #hud button {
      margin-top: 8px; padding: 4px 10px; font-size: 12px; cursor: pointer;
      border: 1px solid #bbb; border-radius: 4px; background: #fff;
    }
    #hud button:disabled { opacity: 0.45; cursor: default; }
    #hud .slider-row {
      display: flex; align-items: center; gap: 8px; margin-top: 8px;
    }
    #hud .slider-row label { flex: 0 0 auto; }
    #hud .slider-row input[type=range] { flex: 1; min-width: 0; }
    #hud .slider-row output { flex: 0 0 2.5em; text-align: right; font-variant-numeric: tabular-nums; }
    #tooltip {
      display: none; position: fixed; z-index: 10; pointer-events: none;
      background: rgba(255,255,255,0.96); border: 1px solid #aaa;
      border-radius: 6px; padding: 8px 10px;
      width: max-content;
      white-space: nowrap;
      font-size: 12px; line-height: 1.4; color: #222;
      box-shadow: 0 4px 14px rgba(0,0,0,0.12);
    }
    #tooltip .name { font-weight: 700; }
    #tooltip .file { color: #555; margin-bottom: 4px; }
    #tooltip .muted { color: #555; }
  </style>
</head>
<body>
  <div id="hud">
    <div class="hud-header">
      <span class="title">NBS call graph</span>
      <button type="button" id="hudToggle" aria-expanded="true" aria-controls="hudBody" title="Collapse panel">▾</button>
    </div>
    <div id="hudBody">
      <div class="hud-body-inner">
        Node &amp; edge colors = Louvain communities; <b>edges use the caller’s color</b>.<br />
        Size ≈ lines + fan-out. Scroll to zoom: peripheral nodes stay visible but fade.<br />
        <b>Double-click</b> a node to isolate it with callers &amp; callees.<br />
        Click empty space or <b>Esc</b> to leave isolation.
        <label style="display:block;margin-top:8px;cursor:pointer;">
          <input type="checkbox" id="showInitials" />
          Show initials when zoomed out (e.g. <code>dwp</code>)
        </label>
        <label style="display:block;margin-top:4px;cursor:pointer;">
          <input type="checkbox" id="crossOnly" />
          Emphasize cross-community edges
        </label>
        <div class="slider-row">
          <label for="fadeIntensity">Fade</label>
          <input type="range" id="fadeIntensity" min="0" max="100" value="100" />
          <output id="fadeIntensityOut" for="fadeIntensity">100%</output>
        </div>
        <div style="font-size:11px;color:#666;margin-top:2px;">0% hides faded nodes · 100% full ghost visibility</div>
        <div><button type="button" id="clearIsolate" disabled>Show full graph</button></div>
      </div>
    </div>
  </div>
  <div id="tooltip"></div>
  <div id="graph"></div>
  <script>
    const DATA = __GRAPH_DATA__;
    const T = DATA.thresholds;
    const tooltipEl = document.getElementById("tooltip");
    const hudEl = document.getElementById("hud");
    const hudToggle = document.getElementById("hudToggle");
    const clearBtn = document.getElementById("clearIsolate");
    const showInitialsCb = document.getElementById("showInitials");
    const crossOnlyCb = document.getElementById("crossOnly");
    const fadeSlider = document.getElementById("fadeIntensity");
    const fadeOut = document.getElementById("fadeIntensityOut");

    hudToggle.addEventListener("click", () => {
      const collapsed = hudEl.classList.toggle("collapsed");
      hudToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      hudToggle.title = collapsed ? "Expand panel" : "Collapse panel";
      hudToggle.textContent = collapsed ? "▸" : "▾";
    });

    function fadeIntensity() {
      return Number(fadeSlider.value) / 100;
    }

    function scaleFadedAlpha(alpha, intensity) {
      // Fully-focused nodes stay opaque; faded ones scale with the slider (0 = gone).
      if (alpha >= 0.999) return 1.0;
      return alpha * intensity;
    }

    function syncFadeLabel() {
      fadeOut.value = `${fadeSlider.value}%`;
    }
    fadeSlider.addEventListener("input", () => {
      syncFadeLabel();
      applyLod();
    });
    syncFadeLabel();

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function hexToRgba(hex, alpha) {
      const h = String(hex).replace("#", "");
      const full = h.length === 3
        ? h.split("").map(c => c + c).join("")
        : h;
      const n = parseInt(full, 16);
      const r = (n >> 16) & 255;
      const g = (n >> 8) & 255;
      const b = n & 255;
      return `rgba(${r},${g},${b},${alpha})`;
    }

    function formatTooltip(tip) {
      if (!tip) return "";
      return (
        `<div class="name">${escapeHtml(tip.name)}</div>` +
        `<div class="file">${escapeHtml(tip.file)}</div>` +
        `<div>${escapeHtml(tip.lines)} lines` +
        ` (${escapeHtml(tip.code_lines)} loc)</div>` +
        `<div>calls: ${escapeHtml(tip.out_degree)} out` +
        // ` &nbsp;/&nbsp; called from: ${escapeHtml(tip.in_degree)}` +
        `&nbsp;/&nbsp;${escapeHtml(tip.in_degree)} in` +
        ` (${escapeHtml(tip.in_calls)}` +
        ` time${tip.in_calls === 1 ? "" : "s"})</div>`
      );
    }

    function formatEdgeTooltip(edge) {
      if (!edge) return "";
      const calls = edge.value;
      const callLabel = calls === 1 ? "1 call" : `${calls} calls`;
      return (
        `<div class="name">${escapeHtml(edge.from)} &gt; ${escapeHtml(edge.to)}</div>` +
        `<div class="muted">${escapeHtml(callLabel)}</div>` +
        (edge.cross_community
          ? `<div class="muted">cross-community</div>`
          : "")
      );
    }

    function showTooltip(html) {
      tooltipEl.innerHTML = html;
      tooltipEl.style.display = "block";
    }

    function hideTooltip() {
      tooltipEl.style.display = "none";
    }

    // Largest first so they paint underneath; smaller nodes stay readable on overlap.
    const nodes = new vis.DataSet(
      DATA.nodes
        .slice()
        .sort((a, b) => (b.size || 0) - (a.size || 0))
        .map(n => ({
          ...n,
          label: "",
          _label: n.label,
          _initials: n.initials || n.label,
          _tooltip: n.tooltip,
          _bg: n.color.background,
          _border: n.color.border,
          opacity: 1
        }))
    );
    const edges = new vis.DataSet(DATA.edges.map(e => ({
      ...e,
      arrows: { to: { enabled: true, scaleFactor: 0.45 } },
      color: {
        color: hexToRgba(e.caller_color, 0.55),
        highlight: e.caller_color,
        hover: e.caller_color
      },
      smooth: { type: "continuous" }
    })));

    // Precompute undirected adjacency for isolation (callers + callees).
    const neighborsOf = {};
    DATA.nodes.forEach(n => { neighborsOf[n.id] = new Set(); });
    DATA.edges.forEach(e => {
      neighborsOf[e.from].add(e.to);
      neighborsOf[e.to].add(e.from);
    });

    // Custom shape: blob size + label size from importance; label canvas-centered.
    let network = null;
    function renderNode({ ctx, id, x, y, style, label }) {
      const r = style.size;
      const node = nodes.get(id) || {};
      const font = node.font || {};
      const importance = node.importance || 0;
      const scale = network ? network.getScale() : 1;
      const borderWidth = (style.borderWidth || 1) / Math.max(0.01, scale);
      // Derive from importance here — don't rely on font.size surviving DataSet merges.
      const showFull = Boolean(label) && label === node._label;
      const fontSize = showFull
        ? Math.min(22, 10 + Math.sqrt(importance))
        : Math.min(14, 8 + Math.sqrt(importance));
      return {
        drawNode() {
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fillStyle = style.color;
          ctx.fill();
          if (borderWidth > 0) {
            ctx.lineWidth = borderWidth;
            ctx.strokeStyle = style.borderColor;
            ctx.stroke();
          }
          if (!label) return;
          ctx.font = fontSize + "px " + (font.face || "Helvetica");
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          if (font.strokeWidth) {
            ctx.lineWidth = font.strokeWidth;
            ctx.strokeStyle = font.strokeColor || "#f7f5f0";
            ctx.strokeText(label, x, y);
          }
          ctx.fillStyle = font.color || "#1a1a1a";
          ctx.fillText(label, x, y);
        },
        nodeDimensions: { width: 2 * r, height: 2 * r }
      };
    }

    const container = document.getElementById("graph");
    network = new vis.Network(
      container,
      { nodes, edges },
      {
        // improvedLayout fails on graphs this large and only warns; ForceAtlas2 does the real layout.
        layout: { improvedLayout: false },
        interaction: {
          hover: true,
          tooltipDelay: 999999, // use custom HTML tooltip instead
          navigationButtons: true,
          keyboard: true,
          zoomView: true,
          dragView: true,
          hideEdgesOnDrag: true,
          hideEdgesOnZoom: true,
          multiselect: false
        },
        physics: {
          solver: "forceAtlas2Based",
          forceAtlas2Based: {
            // Milder repulsion than max avoidOverlap so communities sit a bit closer.
            gravitationalConstant: -65,
            centralGravity: 0.01,
            springLength: 95,
            springConstant: 0.06,
            damping: 0.45,
            avoidOverlap: 0.75
          },
          stabilization: { iterations: 300, fit: true }
        },
        nodes: {
          shape: "custom",
          ctxRenderer: renderNode,
          scaling: { min: 6, max: 150 },
          font: { color: "#1a1a1a", strokeWidth: 3, strokeColor: "#f7f5f0" }
        },
        edges: {
          selectionWidth: 2
        }
      }
    );

    function bandForScale(scale) {
      if (scale < 0.45) return "high";
      if (scale < 0.9) return "mid";
      return "all";
    }

    function minImportance(band) {
      if (band === "high") return T.high;
      if (band === "mid") return T.mid;
      return T.low;
    }

    let isolatedId = null;
    let hoverConnectedEdgesOn = true;
    let zoomLodTimer = 0;
    let lastLodBand = null;
    let cameraLock = false;
    let cameraLockTimer = 0;
    let savedView = null;

    function isolatedSet(id) {
      const keep = new Set([id]);
      (neighborsOf[id] || []).forEach(n => keep.add(n));
      return keep;
    }

    function lockCamera(durationMs) {
      // Block zoom→LOD while the camera animates (that feedback loop caused the glitch).
      cameraLock = true;
      window.clearTimeout(zoomLodTimer);
      window.clearTimeout(cameraLockTimer);
      cameraLockTimer = window.setTimeout(() => {
        cameraLock = false;
        lastLodBand = isolatedId ? "focus" : bandForScale(network.getScale());
      }, durationMs + 120);
    }

    function setIsolate(id) {
      if (!isolatedId) {
        savedView = {
          scale: network.getScale(),
          position: network.getViewPosition()
        };
      }
      isolatedId = id;
      clearBtn.disabled = !id;
      lastLodBand = null;
      applyLod(); // opacities first, then animate camera only
      const keep = isolatedSet(id);
      const duration = 450;
      lockCamera(duration);
      network.fit({
        nodes: Array.from(keep),
        animation: { duration: duration, easingFunction: "easeInOutQuad" }
      });
    }

    function clearIsolate() {
      isolatedId = null;
      clearBtn.disabled = true;
      lastLodBand = null;
      applyLod(); // restore full-graph fade at current pose
      if (savedView) {
        const duration = 450;
        lockCamera(duration);
        network.moveTo({
          scale: savedView.scale,
          position: savedView.position,
          animation: { duration: duration, easingFunction: "easeInOutQuad" }
        });
        savedView = null;
      }
    }

    clearBtn.addEventListener("click", clearIsolate);
    showInitialsCb.addEventListener("change", applyLod);
    crossOnlyCb.addEventListener("change", applyLod);
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") clearIsolate();
    });

    function fadeForImportance(importance, band) {
      // Always keep nodes in view; only change how solid they look.
      // high zoom-out → only hubs opaque; mid → hubs+medium; all → everything opaque.
      if (band === "all" || importance >= T.high) return 1.0;
      if (band === "mid") {
        if (importance >= T.mid) return 1.0;
        return 0.14; // deep leaves: ghosted but findable
      }
      // band === "high" (zoomed out)
      if (importance >= T.mid) return 0.4;
      return 0.1;
    }

    function applyLod() {
      const scale = network.getScale();
      const band = isolatedId ? "focus" : bandForScale(scale);
      const showLabels = scale >= 0.55 || isolatedId;
      const labelFloor = scale < 0.75 ? T.high : (scale < 1.2 ? T.mid : T.low);
      const keepSet = isolatedId ? isolatedSet(isolatedId) : null;
      const crossOnly = crossOnlyCb.checked;
      const intensity = fadeIntensity();
      lastLodBand = band;

      // While focused: outsiders stay visible at a fixed ghost opacity (not the slider),
      // but are treated as non-interactive in event handlers + muted hover styles.
      const FOCUS_GHOST = 0.05;

      const nodeAlpha = {};
      const nodeUpdates = [];
      nodes.forEach(n => {
        const inIsolate = !keepSet || keepSet.has(n.id);
        const isCenter = isolatedId && n.id === isolatedId;
        let alpha;
        if (keepSet) {
          alpha = inIsolate ? 1.0 : FOCUS_GHOST;
        } else {
          alpha = scaleFadedAlpha(fadeForImportance(n.importance, band), intensity);
        }
        nodeAlpha[n.id] = alpha;
        const interactive = !keepSet || inIsolate;
        const showFull = inIsolate && alpha > 0.05 && (
          keepSet || (showLabels && n.importance >= labelFloor)
        );
        // Optional short initials cue when the full name would be hidden.
        const showInitials = showInitialsCb.checked
          && !showFull && inIsolate && alpha > 0.05;
        const labelText = showFull ? n._label : (showInitials ? n._initials : "");
        const bg = hexToRgba(n._bg, alpha);
        const border = hexToRgba(n._border, Math.min(1, alpha + 0.15));
        nodeUpdates.push({
          id: n.id,
          label: labelText,
          hidden: false,
          opacity: alpha,
          // chosen:false + identical hover/highlight → no visual “pop” on accidental hits
          chosen: interactive,
          color: {
            background: bg,
            border: border,
            highlight: interactive
              ? { background: n._bg, border: "#111111" }
              : { background: bg, border: border },
            hover: interactive
              ? { background: n._bg, border: n._border }
              : { background: bg, border: border }
          },
          borderWidth: isCenter ? 4 : (n.borderWidth || 1),
          // Color/stroke only — font size is computed from importance in renderNode.
          font: {
            face: "Helvetica",
            color: hexToRgba("#1a1a1a", labelText ? Math.min(1, alpha + 0.25) : 0),
            strokeWidth: labelText ? (showFull ? 3 : 2) : 0,
            strokeColor: "#f7f5f0"
          }
        });
      });
      nodes.update(nodeUpdates);

      const edgeUpdates = [];
      edges.forEach(e => {
        let alpha;
        let tied = false;
        if (keepSet) {
          tied = (e.from === isolatedId || e.to === isolatedId)
            && keepSet.has(e.from) && keepSet.has(e.to);
          alpha = tied ? 0.85 : FOCUS_GHOST;
        } else {
          // Match the weaker endpoint: only edges touching faded nodes fade.
          const endpointAlpha = Math.min(
            nodeAlpha[e.from] ?? 0,
            nodeAlpha[e.to] ?? 0
          );
          alpha = endpointAlpha >= 0.999 ? 0.85 : endpointAlpha;
        }
        let stroke = e.caller_color;
        if (crossOnly && !keepSet) {
          if (e.cross_community) {
            alpha = Math.max(alpha, endpointVisibleBoost(nodeAlpha, e, intensity));
          } else if (alpha > 0) {
            stroke = "#9a9a9a";
            alpha = Math.min(alpha, 0.12 * intensity);
          }
        }
        const edgeColor = hexToRgba(stroke, alpha);
        const interactive = !keepSet || tied;
        edgeUpdates.push({
          id: e.id,
          hidden: false,
          chosen: interactive,
          color: {
            color: edgeColor,
            // Mute hover/highlight for non-ego edges while focused.
            highlight: interactive ? e.caller_color : edgeColor,
            hover: interactive ? e.caller_color : edgeColor
          },
          opacity: 1
        });
      });
      edges.update(edgeUpdates);

      const wantHoverConnected = !keepSet;
      if (hoverConnectedEdgesOn !== wantHoverConnected) {
        hoverConnectedEdgesOn = wantHoverConnected;
        network.setOptions({
          interaction: { hoverConnectedEdges: wantHoverConnected }
        });
      }
    }

    function endpointVisibleBoost(nodeAlpha, e, intensity) {
      const a = Math.min(nodeAlpha[e.from] ?? 0, nodeAlpha[e.to] ?? 0);
      if (a <= 0) return 0;
      return Math.max(a, 0.75 * Math.max(intensity, 0.01));
    }

    network.once("stabilizationIterationsDone", () => {
      network.setOptions({ physics: { enabled: false } });
      applyLod();
      network.fit({ animation: false });
    });

    network.on("zoom", () => {
      if (cameraLock || isolatedId) return;
      // Debounce until zoom settles; only redraw when the LOD band changes.
      window.clearTimeout(zoomLodTimer);
      zoomLodTimer = window.setTimeout(() => {
        if (cameraLock || isolatedId) return;
        const band = bandForScale(network.getScale());
        if (band === lastLodBand) return;
        applyLod();
      }, 120);
    });

    network.on("doubleClick", params => {
      if (params.nodes.length) {
        if (isolatedId) {
          const keep = isolatedSet(isolatedId);
          if (!keep.has(params.nodes[0])) return; // ghost nodes: not interactable
        }
        setIsolate(params.nodes[0]);
      } else {
        clearIsolate();
      }
    });

    network.on("click", params => {
      if (isolatedId && params.nodes.length) {
        const keep = isolatedSet(isolatedId);
        if (!keep.has(params.nodes[0])) return;
      }
      if (!params.nodes.length && !params.edges.length) {
        if (isolatedId) clearIsolate();
      }
    });

    network.on("hoverNode", params => {
      const node = nodes.get(params.node);
      if (!node || !node._tooltip) return;
      if (isolatedId) {
        const keep = isolatedSet(isolatedId);
        if (!keep.has(node.id)) {
          hideTooltip();
          return;
        }
      }
      showTooltip(formatTooltip(node._tooltip));
    });
    network.on("blurNode", hideTooltip);

    network.on("hoverEdge", params => {
      const edge = edges.get(params.edge);
      if (!edge) return;
      if (isolatedId) {
        const tied = edge.from === isolatedId || edge.to === isolatedId;
        if (!tied) {
          hideTooltip();
          return;
        }
      }
      showTooltip(formatEdgeTooltip(edge));
    });
    network.on("blurEdge", hideTooltip);

    container.addEventListener("mousemove", (ev) => {
      if (tooltipEl.style.display === "none") return;
      const pad = 12;
      const offset = 14;
      const tw = tooltipEl.offsetWidth;
      const th = tooltipEl.offsetHeight;
      let left = ev.clientX + offset;
      let top = ev.clientY + offset;
      if (left + tw > window.innerWidth - pad) {
        left = Math.max(pad, ev.clientX - tw - offset);
      }
      if (top + th > window.innerHeight - pad) {
        top = Math.max(pad, ev.clientY - th - offset);
      }
      tooltipEl.style.left = left + "px";
      tooltipEl.style.top = top + "px";
    });
  </script>
</body>
</html>
"""


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
        help="Output directory",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help="Optional root node; plot only that node and its descendants",
    )
    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Skip PNG rendering",
    )
    parser.add_argument(
        "--no-svg",
        action="store_true",
        help="Skip SVG rendering (SVG is the full-resolution Graphviz export)",
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
    png_path = out_dir / f"call_graph{suffix}.png"
    svg_path = out_dir / f"call_graph{suffix}.svg"
    html_path = out_dir / f"call_graph{suffix}.html"

    write_dot(graph, dot_path)
    print(
        f"Wrote {dot_path} ({graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)"
    )

    if not args.no_svg:
        try:
            print("Rendering SVG with Graphviz…")
            render_with_graphviz(dot_path, svg_path, "svg")
            print(f"Wrote {svg_path} (preferred for zooming; no cairo size cap)")
        except Exception as exc:
            print(f"Graphviz SVG render failed; skipping SVG. ({exc})")

    if not args.no_png:
        try:
            print("Rendering PNG with Graphviz…")
            render_with_graphviz(dot_path, png_path, "png")
            print(
                f"Wrote {png_path} "
                "(may be auto-scaled if the graph exceeds cairo bitmap limits)"
            )
        except Exception as exc:
            print(f"Graphviz PNG render failed; falling back to matplotlib. ({exc})")
            render_png_matplotlib_fallback(graph, png_path)
            print(f"Wrote {png_path}")

    if not args.no_html:
        write_interactive_html(graph, html_path)
        print(f"Wrote {html_path}")


if __name__ == "__main__":
    main()
