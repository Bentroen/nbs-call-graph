const DATA = window.GRAPH_DATA;
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
  const full =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  const n = parseInt(full, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

function fmtNum(n) {
  return Number(n).toLocaleString("en-US");
}

function formatTooltip(tip) {
  if (!tip) return "";
  return (
    `<div class="title">${escapeHtml(tip.name)}</div>` +
    `<div class="meta">${escapeHtml(tip.file)}</div>` +
    `<div class="stats">` +
    `<div>${fmtNum(tip.lines)} lines` +
    ` (${fmtNum(tip.code_lines)} loc)</div>` +
    `<div>calls: ${fmtNum(tip.out_degree)}` +
    ` (${fmtNum(tip.out_calls)}` +
    ` time${tip.out_calls === 1 ? "" : "s"})</div>` +
    `<div>callers: ${fmtNum(tip.in_degree)}` +
    ` (${fmtNum(tip.in_calls)}` +
    ` time${tip.in_calls === 1 ? "" : "s"})</div>` +
    `</div>`
  );
}

function formatEdgeTooltip(edge) {
  if (!edge) return "";
  const calls = edge.value;
  const callLabel = calls === 1 ? "1 call" : `${fmtNum(calls)} calls`;
  return (
    `<div class="title">${escapeHtml(edge.from)} &gt; ${escapeHtml(edge.to)}</div>` +
    `<div class="meta">${escapeHtml(callLabel)}</div>` +
    (edge.cross_community ? `<div class="meta">cross-community</div>` : "")
  );
}

function showTooltip(html) {
  tooltipEl.innerHTML = html;
  tooltipEl.style.display = "flex";
}

function hideTooltip() {
  tooltipEl.style.display = "none";
}

// Largest first so they paint underneath; smaller nodes stay readable on overlap.
const nodes = new vis.DataSet(
  DATA.nodes
    .slice()
    .sort((a, b) => (b.size || 0) - (a.size || 0))
    .map((n) => ({
      ...n,
      label: "",
      _label: n.label,
      _initials: n.initials || n.label,
      _tooltip: n.tooltip,
      _bg: n.color.background,
      _border: n.color.border,
      opacity: 1,
    })),
);
const edges = new vis.DataSet(
  DATA.edges.map((e) => ({
    ...e,
    arrows: { to: { enabled: true, scaleFactor: 0.45 } },
    color: {
      color: hexToRgba(e.caller_color, 0.55),
      highlight: e.caller_color,
      hover: e.caller_color,
    },
    smooth: { type: "continuous" },
  })),
);

// Precompute undirected adjacency for isolation (callers + callees).
const neighborsOf = {};
DATA.nodes.forEach((n) => {
  neighborsOf[n.id] = new Set();
});
DATA.edges.forEach((e) => {
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
    nodeDimensions: { width: 2 * r, height: 2 * r },
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
      multiselect: false,
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
        avoidOverlap: 0.75,
      },
      stabilization: { iterations: 300, fit: true },
    },
    nodes: {
      shape: "custom",
      ctxRenderer: renderNode,
      scaling: { min: 6, max: 150 },
      font: { color: "#1a1a1a", strokeWidth: 3, strokeColor: "#f7f5f0" },
    },
    edges: {
      selectionWidth: 2,
    },
  },
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
  (neighborsOf[id] || []).forEach((n) => keep.add(n));
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
      position: network.getViewPosition(),
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
    animation: { duration: duration, easingFunction: "easeInOutQuad" },
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
      animation: { duration: duration, easingFunction: "easeInOutQuad" },
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
  const labelFloor = scale < 0.75 ? T.high : scale < 1.2 ? T.mid : T.low;
  const keepSet = isolatedId ? isolatedSet(isolatedId) : null;
  const crossOnly = crossOnlyCb.checked;
  const intensity = fadeIntensity();
  lastLodBand = band;

  // While focused: outsiders stay visible at a fixed ghost opacity (not the slider),
  // but are treated as non-interactive in event handlers + muted hover styles.
  const FOCUS_GHOST = 0.05;

  const nodeAlpha = {};
  const nodeUpdates = [];
  nodes.forEach((n) => {
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
    const showFull =
      inIsolate &&
      alpha > 0.05 &&
      (keepSet || (showLabels && n.importance >= labelFloor));
    // Optional short initials cue when the full name would be hidden.
    const showInitials =
      showInitialsCb.checked && !showFull && inIsolate && alpha > 0.05;
    const labelText = showFull ? n._label : showInitials ? n._initials : "";
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
          : { background: bg, border: border },
      },
      borderWidth: isCenter ? 4 : n.borderWidth || 1,
      // Color/stroke only — font size is computed from importance in renderNode.
      font: {
        face: "Helvetica",
        color: hexToRgba("#1a1a1a", labelText ? Math.min(1, alpha + 0.25) : 0),
        strokeWidth: labelText ? (showFull ? 3 : 2) : 0,
        strokeColor: "#f7f5f0",
      },
    });
  });
  nodes.update(nodeUpdates);

  const edgeUpdates = [];
  edges.forEach((e) => {
    let alpha;
    let tied = false;
    if (keepSet) {
      tied =
        (e.from === isolatedId || e.to === isolatedId) &&
        keepSet.has(e.from) &&
        keepSet.has(e.to);
      alpha = tied ? 0.85 : FOCUS_GHOST;
    } else {
      // Match the weaker endpoint: only edges touching faded nodes fade.
      const endpointAlpha = Math.min(
        nodeAlpha[e.from] ?? 0,
        nodeAlpha[e.to] ?? 0,
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
        hover: interactive ? e.caller_color : edgeColor,
      },
      opacity: 1,
    });
  });
  edges.update(edgeUpdates);

  const wantHoverConnected = !keepSet;
  if (hoverConnectedEdgesOn !== wantHoverConnected) {
    hoverConnectedEdgesOn = wantHoverConnected;
    network.setOptions({
      interaction: { hoverConnectedEdges: wantHoverConnected },
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

network.on("doubleClick", (params) => {
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

network.on("click", (params) => {
  if (isolatedId && params.nodes.length) {
    const keep = isolatedSet(isolatedId);
    if (!keep.has(params.nodes[0])) return;
  }
  if (!params.nodes.length && !params.edges.length) {
    if (isolatedId) clearIsolate();
  }
});

network.on("hoverNode", (params) => {
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

network.on("hoverEdge", (params) => {
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
