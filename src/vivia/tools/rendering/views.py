"""Documents HTML des MCP Apps : des tools qui rendent une vue, pas du texte.

Open WebUI implemente l'extension `io.modelcontextprotocol/ui` : un tool porte
un `resourceUri` en `ui://`, le serveur sert le HTML sous le type MIME
`text/html;profile=mcp-app`, et l'hote l'affiche dans une iframe sandboxee.

Deux contraintes dictent la forme de ces documents :

- La CSP par defaut est `default-src 'none'` avec `script-src 'unsafe-inline'`.
  L'inline passe, le reseau non : pas de CDN, pas de `fetch`. Tout est donc
  ecrit a la main plutot que delegue a une bibliotheque — ce qui evite aussi
  d'avoir a declarer des domaines externes.
- L'iframe n'a pas `allow-same-origin` : l'origine est opaque, donc pas de
  `localStorage` ni de cookie. L'etat ne vit que le temps du rendu.

Le dialogue avec l'hote est du JSON-RPC 2.0 par `postMessage`. L'ordre est
impose par l'hote : il n'envoie `tool-input` puis `tool-result` qu'apres avoir
recu `ui/notifications/initialized`, donc le rendu s'accroche a cette
notification et jamais a `load`.
"""

PROTOCOL_VERSION = "2025-11-21"

# Palette categorielle lisible sur fond clair comme sombre.
_SERIES_COLORS = (
    "#3b82f6",
    "#f97316",
    "#10b981",
    "#a855f7",
    "#ef4444",
    "#14b8a6",
    "#eab308",
    "#ec4899",
)

_BASE_CSS = """
:root {
  --vivia-bg: #ffffff; --vivia-fg: #18181b; --vivia-muted: #71717a;
  --vivia-line: #e4e4e7; --vivia-soft: #f4f4f5; --vivia-accent: #3b82f6;
  color-scheme: light;
}
:root[data-theme="dark"] {
  --vivia-bg: #18181b; --vivia-fg: #fafafa; --vivia-muted: #a1a1aa;
  --vivia-line: #3f3f46; --vivia-soft: #27272a;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 14px;
  font: 13px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--vivia-bg); color: var(--vivia-fg);
  -webkit-font-smoothing: antialiased;
}
h1 { margin: 0 0 2px; font-size: 14px; font-weight: 600; letter-spacing: -0.01em; }
.sub { margin: 0 0 12px; font-size: 12px; color: var(--vivia-muted); }
.err {
  padding: 10px 12px; border-radius: 8px; font-size: 12px;
  background: color-mix(in srgb, #ef4444 12%, transparent);
  color: #ef4444; border: 1px solid color-mix(in srgb, #ef4444 30%, transparent);
}
.wrap { overflow-x: auto; }
svg { display: block; max-width: 100%; height: auto; }
.tip {
  position: fixed; pointer-events: none; opacity: 0; transition: opacity .1s;
  background: var(--vivia-fg); color: var(--vivia-bg);
  padding: 5px 8px; border-radius: 6px; font-size: 11px; font-variant-numeric: tabular-nums;
  white-space: nowrap; z-index: 9; box-shadow: 0 2px 8px rgb(0 0 0 / .18);
}
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 10px; font-size: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; color: var(--vivia-muted); }
.legend i { width: 9px; height: 9px; border-radius: 2px; flex: none; }
"""

# Le bridge : handshake, theme, hauteur de l'iframe, extraction du resultat.
_BRIDGE_JS = """
const PENDING = new Map();
const HANDLERS = {};
let seq = 0;

function send(message) { parent.postMessage({ jsonrpc: "2.0", ...message }, "*"); }
function notify(method, params) { send({ method, params }); }
function request(method, params) {
  const id = ++seq;
  return new Promise((resolve, reject) => {
    PENDING.set(id, { resolve, reject });
    send({ id, method, params });
  });
}

addEventListener("message", (event) => {
  const message = event.data;
  if (!message || message.jsonrpc !== "2.0") return;
  if (message.id !== undefined && PENDING.has(message.id)) {
    const { resolve, reject } = PENDING.get(message.id);
    PENDING.delete(message.id);
    message.error ? reject(new Error(message.error.message)) : resolve(message.result);
    return;
  }
  HANDLERS[message.method]?.(message.params ?? {});
});

// L'hote expose son theme et ses variables CSS : s'y conformer evite une vue
// qui jure avec le reste de la conversation.
function applyContext(context) {
  if (!context) return;
  if (context.theme) document.documentElement.dataset.theme = context.theme;
  for (const [name, value] of Object.entries(context.styles?.variables ?? {})) {
    if (name.startsWith("--")) document.documentElement.style.setProperty(name, value);
  }
}

let sent = 0;
function autosize() {
  // `documentElement.scrollHeight` vaut au moins la hauteur de l'iframe : une
  // fois celle-ci agrandie, il ne redescend plus et la vue reste trop haute.
  // La boite du body, elle, suit son contenu dans les deux sens.
  const height = Math.ceil(document.body.getBoundingClientRect().height) + 2;
  // L'hote borne la hauteur a 100..10000px ; ne la renotifier que si elle bouge.
  if (Math.abs(height - sent) >= 6) {
    sent = height;
    notify("ui/notifications/size-changed", { height });
  }
}
addEventListener("resize", autosize);

// FastMCP renvoie un dict tel quel dans structuredContent, et emballe les
// valeurs scalaires dans {"result": ...} ; les deux formes sont acceptees.
function payload(result) {
  const structured = result?.structuredContent;
  if (structured) {
    const keys = Object.keys(structured);
    return keys.length === 1 && keys[0] === "result" ? structured.result : structured;
  }
  const text = (result?.content ?? []).find((item) => item.type === "text");
  return text ? JSON.parse(text.text) : null;
}

function fail(error) {
  document.getElementById("view").innerHTML = "";
  const box = document.createElement("div");
  box.className = "err";
  box.textContent = "Rendu impossible : " + (error?.message ?? error);
  document.getElementById("view").append(box);
  autosize();
}

function tooltip() {
  const node = document.createElement("div");
  node.className = "tip";
  document.body.append(node);
  return {
    show(event, text) {
      node.textContent = text;
      node.style.opacity = "1";
      const box = node.getBoundingClientRect();
      const x = Math.min(Math.max(6, event.clientX - box.width / 2), innerWidth - box.width - 6);
      node.style.left = x + "px";
      node.style.top = Math.max(6, event.clientY - box.height - 10) + "px";
    },
    hide() { node.style.opacity = "0"; },
  };
}

function svg(tag, attrs = {}, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function heading(data) {
  document.getElementById("title").textContent = data?.title ?? "";
  document.getElementById("sub").textContent = data?.subtitle ?? "";
}

async function start(render) {
  try {
    const result = await request("ui/initialize", {
      appInfo: { name: "vivia", version: "1" },
      appCapabilities: {},
      protocolVersion: "__PROTOCOL__",
    });
    applyContext(result?.hostContext);
    HANDLERS["ui/notifications/host-context-changed"] = (params) => {
      applyContext(params);
      autosize();
    };
    HANDLERS["ui/notifications/tool-result"] = (toolResult) => {
      try {
        const data = payload(toolResult);
        heading(data);
        render(data);
      } catch (error) { fail(error); }
      requestAnimationFrame(autosize);
    };
    // Declenche l'envoi de tool-input puis tool-result par l'hote.
    notify("ui/notifications/initialized", {});
  } catch (error) { fail(error); }
}
"""


def _document(script: str, extra_css: str = "") -> str:
    bridge = _BRIDGE_JS.replace("__PROTOCOL__", PROTOCOL_VERSION)
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_BASE_CSS}{extra_css}</style>
</head>
<body>
<h1 id="title"></h1>
<p class="sub" id="sub"></p>
<div id="view"></div>
<script>
const COLORS = {list(_SERIES_COLORS)!r};
{bridge}
{script}
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Graphique : barres groupees, lignes ou aires, axes et survol.
# --------------------------------------------------------------------------

_CHART_JS = """
const PAD = { top: 10, right: 12, bottom: 34, left: 52 };

function ticks(min, max, count) {
  // Pas « rond » (1, 2, 5 x 10^n) pour que les graduations restent lisibles.
  const raw = (max - min) / count || 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 5, 10].find((m) => m * magnitude >= raw) ?? 10) * magnitude;
  // Les bornes sont arrondies *vers l'exterieur* : une graduation qui s'arrete
  // sous le maximum ferait sortir la derniere barre hors du cadre.
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const values = [];
  for (let v = start; v <= end + step / 2; v += step) {
    values.push(Math.abs(v) < step / 1e6 ? 0 : v);
  }
  return values;
}

const format = (value) =>
  Math.abs(value) >= 1000 ? value.toLocaleString("fr-FR") : String(Math.round(value * 1000) / 1000);

function render(data) {
  const view = document.getElementById("view");
  view.innerHTML = "";
  const labels = data?.labels ?? [];
  const series = (data?.series ?? []).filter((s) => Array.isArray(s.values));
  if (!labels.length || !series.length) throw new Error("ni labels ni series");

  const kind = data.kind ?? "bar";
  const width = Math.max(320, Math.min(view.clientWidth || 720, 1100));
  const height = Math.max(200, Math.min(data.height ?? 300, 700));
  const inner = { w: width - PAD.left - PAD.right, h: height - PAD.top - PAD.bottom };

  const flat = series.flatMap((s) => s.values.filter((v) => typeof v === "number"));
  if (!flat.length) throw new Error("aucune valeur numerique");
  // L'axe part de zero pour les barres : une base tronquee exagere les ecarts.
  const top = Math.max(...flat, 0);
  const bottom = kind === "bar" ? Math.min(...flat, 0) : Math.min(...flat);
  const grads = ticks(bottom, top === bottom ? top + 1 : top, 5);
  const lo = Math.min(...grads);
  const hi = Math.max(...grads);
  const y = (value) => PAD.top + inner.h - ((value - lo) / (hi - lo)) * inner.h;
  const band = inner.w / labels.length;

  const root = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img" });
  const tip = tooltip();

  for (const value of grads) {
    root.append(svg("line", {
      x1: PAD.left, x2: PAD.left + inner.w, y1: y(value), y2: y(value),
      stroke: "var(--vivia-line)", "stroke-width": value === 0 ? 1.4 : 1,
    }));
    root.append(svg("text", {
      x: PAD.left - 8, y: y(value) + 4, "text-anchor": "end",
      fill: "var(--vivia-muted)", "font-size": 10,
    }, format(value)));
  }

  // Au-dela d'une dizaine de categories, une etiquette sur deux suffit.
  const every = Math.ceil((labels.length * 52) / inner.w);
  labels.forEach((label, index) => {
    if (index % every) return;
    root.append(svg("text", {
      x: PAD.left + band * (index + 0.5), y: height - 12, "text-anchor": "middle",
      fill: "var(--vivia-muted)", "font-size": 10,
    }, String(label)));
  });

  if (kind === "bar") {
    const slot = (band * 0.72) / series.length;
    series.forEach((entry, s) => {
      entry.values.forEach((value, index) => {
        if (typeof value !== "number") return;
        const x = PAD.left + band * index + band * 0.14 + slot * s;
        const zero = y(Math.max(lo, 0));
        const bar = svg("rect", {
          x, y: Math.min(y(value), zero), width: Math.max(1, slot - 1.5),
          height: Math.max(1, Math.abs(zero - y(value))), rx: 2,
          fill: COLORS[s % COLORS.length],
        });
        bar.addEventListener("pointermove", (event) =>
          tip.show(event, `${entry.name ?? "serie"} · ${labels[index]} · ${format(value)}`));
        bar.addEventListener("pointerleave", tip.hide);
        root.append(bar);
      });
    });
  } else {
    series.forEach((entry, s) => {
      const color = COLORS[s % COLORS.length];
      const points = entry.values
        .map((value, index) => [PAD.left + band * (index + 0.5), value])
        .filter(([, value]) => typeof value === "number")
        .map(([x, value]) => [x, y(value)]);
      if (!points.length) return;
      const path = points.map(([x, py], i) => `${i ? "L" : "M"}${x} ${py}`).join(" ");
      if (kind === "area") {
        const base = y(Math.max(lo, 0));
        root.append(svg("path", {
          d: `${path} L${points.at(-1)[0]} ${base} L${points[0][0]} ${base} Z`,
          fill: color, opacity: 0.16,
        }));
      }
      root.append(svg("path", {
        d: path, fill: "none", stroke: color, "stroke-width": 2,
        "stroke-linecap": "round", "stroke-linejoin": "round",
      }));
      points.forEach(([x, py], index) => {
        const dot = svg("circle", { cx: x, cy: py, r: 3.2, fill: color });
        const value = format(entry.values[index]);
        dot.addEventListener("pointermove", (event) =>
          tip.show(event, `${entry.name ?? "serie"} · ${labels[index]} · ${value}`));
        dot.addEventListener("pointerleave", tip.hide);
        root.append(dot);
      });
    });
  }

  const wrap = document.createElement("div");
  wrap.className = "wrap";
  wrap.append(root);
  view.append(wrap);

  if (series.length > 1 || series[0]?.name) {
    const legend = document.createElement("div");
    legend.className = "legend";
    series.forEach((entry, s) => {
      const item = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.style.background = COLORS[s % COLORS.length];
      item.append(swatch, document.createTextNode(entry.name ?? `serie ${s + 1}`));
      legend.append(item);
    });
    view.append(legend);
  }
}

start(render);
"""


# --------------------------------------------------------------------------
# Graphe : disposition par forces, noeuds deplacables.
# --------------------------------------------------------------------------

_GRAPH_CSS = """
.hint { margin-top: 8px; font-size: 11px; color: var(--vivia-muted); }
#view svg { cursor: grab; touch-action: none; }
.node { cursor: grab; }
.node:active { cursor: grabbing; }
"""

_GRAPH_JS = """
function render(data) {
  const view = document.getElementById("view");
  view.innerHTML = "";
  const edges = data?.edges ?? [];
  const declared = data?.nodes ?? [];
  // Un noeud cite par une arete sans etre declare est cree : un graphe partiel
  // vaut mieux qu'une arete pendante.
  const byId = new Map(declared.map((n) => [String(n.id), { ...n, id: String(n.id) }]));
  for (const edge of edges) {
    for (const end of [edge.source, edge.target]) {
      const id = String(end);
      if (!byId.has(id)) byId.set(id, { id, label: id });
    }
  }
  const nodes = [...byId.values()];
  if (!nodes.length) throw new Error("aucun noeud");

  const width = Math.max(320, Math.min(view.clientWidth || 720, 1100));
  const height = Math.max(260, Math.min(data.height ?? 420, 760));
  const groups = [...new Set(nodes.map((n) => n.group ?? ""))];
  const links = edges
    .map((e) => ({ ...e, a: byId.get(String(e.source)), b: byId.get(String(e.target)) }))
    .filter((e) => e.a && e.b && e.a !== e.b);

  const degree = new Map(nodes.map((n) => [n.id, 0]));
  for (const link of links) {
    degree.set(link.a.id, degree.get(link.a.id) + 1);
    degree.set(link.b.id, degree.get(link.b.id) + 1);
  }
  const radius = (node) =>
    typeof node.value === "number"
      ? Math.max(5, Math.min(22, 5 + Math.sqrt(Math.abs(node.value)) * 2.2))
      : Math.max(6, Math.min(18, 6 + degree.get(node.id) * 1.6));

  // Depart en cercle : deterministe, et evite les configurations degenerees
  // ou tous les noeuds partent du meme point.
  nodes.forEach((node, index) => {
    const angle = (index / nodes.length) * Math.PI * 2;
    node.x = width / 2 + Math.cos(angle) * Math.min(width, height) * 0.3;
    node.y = height / 2 + Math.sin(angle) * Math.min(width, height) * 0.3;
    node.vx = node.vy = 0;
  });

  const root = svg("svg", { width, height, viewBox: `0 0 ${width} ${height}` });
  const edgeLayer = svg("g", { stroke: "var(--vivia-line)", "stroke-width": 1.5 });
  const nodeLayer = svg("g", {});
  if (data.directed) {
    const defs = svg("defs", {});
    // `userSpaceOnUse` : la taille de la pointe ne suit pas l'epaisseur du trait.
    const marker = svg("marker", {
      id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5,
      markerWidth: 9, markerHeight: 9, markerUnits: "userSpaceOnUse", orient: "auto",
    });
    marker.append(
      svg("path", { d: "M0 0 L10 5 L0 10 z", fill: "var(--vivia-muted)", stroke: "none" })
    );
    defs.append(marker);
    root.append(defs);
  }
  root.append(edgeLayer, nodeLayer);

  const tip = tooltip();
  for (const link of links) {
    link.line = svg("line", data.directed ? { "marker-end": "url(#arrow)" } : {});
    edgeLayer.append(link.line);
  }
  for (const node of nodes) {
    node.r = radius(node);
    node.circle = svg("circle", {
      r: node.r, fill: COLORS[Math.max(0, groups.indexOf(node.group ?? "")) % COLORS.length],
      stroke: "var(--vivia-bg)", "stroke-width": 1.5, class: "node",
    });
    node.text = svg("text", {
      "text-anchor": "middle", "font-size": 10, fill: "var(--vivia-fg)",
      "pointer-events": "none",
    }, node.label ?? node.id);
    nodeLayer.append(node.circle, node.text);
    node.circle.addEventListener("pointermove", (event) =>
      tip.show(event, `${node.label ?? node.id} · ${degree.get(node.id)} lien(s)`));
    node.circle.addEventListener("pointerleave", tip.hide);
  }

  function draw() {
    for (const link of links) {
      // L'arete s'arrete au bord des cercles : sinon la pointe de la fleche
      // se dessine sous le noeud cible et devient invisible.
      const dx = link.b.x - link.a.x;
      const dy = link.b.y - link.a.y;
      const d = Math.hypot(dx, dy) || 1;
      const gap = data.directed ? 9 : 1;
      link.line.setAttribute("x1", link.a.x + (dx / d) * link.a.r);
      link.line.setAttribute("y1", link.a.y + (dy / d) * link.a.r);
      link.line.setAttribute("x2", link.b.x - (dx / d) * (link.b.r + gap));
      link.line.setAttribute("y2", link.b.y - (dy / d) * (link.b.r + gap));
    }
    for (const node of nodes) {
      node.circle.setAttribute("cx", node.x); node.circle.setAttribute("cy", node.y);
      node.text.setAttribute("x", node.x); node.text.setAttribute("y", node.y + node.r + 11);
    }
  }

  // Verlet amorti : repulsion de Coulomb, ressorts sur les aretes, rappel au
  // centre. Assez pour quelques centaines de noeuds, sans dependance.
  const spring = Math.min(width, height) / Math.max(2, Math.sqrt(nodes.length)) * 0.6;
  let alpha = 1;
  function tick() {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1e-4) {
          dx = (Math.random() - 0.5) * 0.1;
          dy = (Math.random() - 0.5) * 0.1;
          d2 = 0.01;
        }
        const force = (spring * spring * 2) / d2;
        const d = Math.sqrt(d2);
        a.vx -= (dx / d) * force; a.vy -= (dy / d) * force;
        b.vx += (dx / d) * force; b.vy += (dy / d) * force;
      }
    }
    for (const link of links) {
      const dx = link.b.x - link.a.x;
      const dy = link.b.y - link.a.y;
      const d = Math.hypot(dx, dy) || 1;
      const pull = ((d - spring) / d) * 0.08 * (link.weight ?? 1);
      link.a.vx += dx * pull; link.a.vy += dy * pull;
      link.b.vx -= dx * pull; link.b.vy -= dy * pull;
    }
    for (const node of nodes) {
      if (node.fixed) { node.vx = node.vy = 0; continue; }
      node.vx += (width / 2 - node.x) * 0.012;
      node.vy += (height / 2 - node.y) * 0.012;
      node.x += (node.vx *= 0.82) * alpha;
      node.y += (node.vy *= 0.82) * alpha;
      node.x = Math.max(node.r + 2, Math.min(width - node.r - 2, node.x));
      node.y = Math.max(node.r + 2, Math.min(height - node.r - 14, node.y));
    }
    draw();
  }

  let frames = 0;
  (function loop() {
    tick();
    alpha = Math.max(0.12, alpha * 0.985);
    if (++frames < 420) requestAnimationFrame(loop);
  })();

  // Glisser un noeud le fixe et relance la simulation autour de lui.
  let dragged = null;
  const place = (event) => {
    const box = root.getBoundingClientRect();
    dragged.x = ((event.clientX - box.left) / box.width) * width;
    dragged.y = ((event.clientY - box.top) / box.height) * height;
    draw();
  };
  for (const node of nodes) {
    node.circle.addEventListener("pointerdown", (event) => {
      dragged = node;
      node.fixed = true;
      node.circle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
  }
  root.addEventListener("pointermove", (event) => { if (dragged) place(event); });
  root.addEventListener("pointerup", () => {
    if (!dragged) return;
    dragged = null;
    alpha = 0.5;
    frames = 260;
    requestAnimationFrame(function again() {
      tick();
      alpha = Math.max(0.12, alpha * 0.985);
      if (++frames < 420) requestAnimationFrame(again);
    });
  });

  const wrap = document.createElement("div");
  wrap.className = "wrap";
  wrap.append(root);
  view.append(wrap);

  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = `${nodes.length} noeuds, ${links.length} aretes — glisser pour reorganiser`;
  view.append(hint);

  if (groups.length > 1) {
    const legend = document.createElement("div");
    legend.className = "legend";
    groups.forEach((group, index) => {
      const item = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.style.background = COLORS[index % COLORS.length];
      item.append(swatch, document.createTextNode(group || "sans groupe"));
      legend.append(item);
    });
    view.append(legend);
  }
  draw();
}

start(render);
"""


# --------------------------------------------------------------------------
# Tableau : tri, filtre, alignement numerique.
# --------------------------------------------------------------------------

_TABLE_CSS = """
.bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
.bar input {
  flex: 1; min-width: 0; padding: 6px 9px; font: inherit; border-radius: 7px;
  border: 1px solid var(--vivia-line); background: var(--vivia-bg); color: inherit;
}
.bar input:focus { outline: 2px solid var(--vivia-accent); outline-offset: -1px; }
.count { font-size: 11px; color: var(--vivia-muted); font-variant-numeric: tabular-nums; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td {
  padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--vivia-line);
  white-space: nowrap; max-width: 420px; overflow: hidden; text-overflow: ellipsis;
}
th {
  position: sticky; top: 0; cursor: pointer; user-select: none; font-weight: 600;
  background: var(--vivia-bg); font-size: 12px;
}
th:hover { color: var(--vivia-accent); }
th span { color: var(--vivia-muted); font-weight: 400; }
td.num, th.num { text-align: right; }
tbody tr:nth-child(even) { background: var(--vivia-soft); }
.scroll {
  max-height: 460px; overflow: auto;
  border: 1px solid var(--vivia-line); border-radius: 8px;
}
"""

_TABLE_JS = """
function render(data) {
  const view = document.getElementById("view");
  view.innerHTML = "";
  const raw = data?.rows ?? [];
  if (!raw.length) throw new Error("aucune ligne");

  // Deux formes acceptees : liste d'objets, ou liste de listes + colonnes.
  let columns = data.columns ?? null;
  let rows;
  if (Array.isArray(raw[0])) {
    columns ??= raw[0].map((_, index) => `col ${index + 1}`);
    rows = raw.map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i]])));
  } else {
    columns ??= [...new Set(raw.flatMap((row) => Object.keys(row)))];
    rows = raw;
  }

  const numeric = new Set(
    columns.filter((column) =>
      rows.some((row) => typeof row[column] === "number") &&
      rows.every((row) => row[column] == null || typeof row[column] === "number"))
  );
  const cell = (value) =>
    value == null ? "" : typeof value === "object" ? JSON.stringify(value)
    : typeof value === "number" ? value.toLocaleString("fr-FR", { maximumFractionDigits: 6 })
    : String(value);

  const bar = document.createElement("div");
  bar.className = "bar";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "Filtrer…";
  search.setAttribute("aria-label", "Filtrer les lignes");
  const count = document.createElement("span");
  count.className = "count";
  bar.append(search, count);

  const scroll = document.createElement("div");
  scroll.className = "scroll";
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  const body = table.createTBody();
  scroll.append(table);
  view.append(bar, scroll);

  let sort = { column: null, descending: false };
  const headers = columns.map((column) => {
    const th = document.createElement("th");
    th.textContent = column;
    if (numeric.has(column)) th.className = "num";
    const arrow = document.createElement("span");
    th.append(" ", arrow);
    th.addEventListener("click", () => {
      sort = { column, descending: sort.column === column && !sort.descending };
      paint();
    });
    head.append(th);
    return { column, arrow };
  });

  function paint() {
    const needle = search.value.trim().toLowerCase();
    let visible = needle
      ? rows.filter((row) => columns.some((c) => cell(row[c]).toLowerCase().includes(needle)))
      : rows.slice();
    if (sort.column) {
      const column = sort.column;
      const sign = sort.descending ? -1 : 1;
      visible.sort((a, b) => {
        const x = a[column];
        const y = b[column];
        // Les trous vont en fin de tri, quel que soit le sens demande.
        if (x == null) return y == null ? 0 : 1;
        if (y == null) return -1;
        return sign * (numeric.has(column) ? x - y : String(x).localeCompare(String(y), "fr"));
      });
    }
    for (const { column, arrow } of headers) {
      arrow.textContent = sort.column === column ? (sort.descending ? "\\u2193" : "\\u2191") : "";
    }
    body.replaceChildren(...visible.map((row) => {
      const tr = document.createElement("tr");
      for (const column of columns) {
        const td = tr.insertCell();
        const value = cell(row[column]);
        td.textContent = value;
        td.title = value;
        if (numeric.has(column)) td.className = "num";
      }
      return tr;
    }));
    count.textContent = visible.length === rows.length
      ? `${rows.length} ligne(s)`
      : `${visible.length} / ${rows.length}`;
    autosize();
  }

  search.addEventListener("input", paint);
  paint();
}

start(render);
"""


CHART_HTML = _document(_CHART_JS)
GRAPH_HTML = _document(_GRAPH_JS, _GRAPH_CSS)
TABLE_HTML = _document(_TABLE_JS, _TABLE_CSS)
