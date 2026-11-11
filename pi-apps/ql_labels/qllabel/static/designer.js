// QL label designer. The Pi draws every label (POST /api/preview); this page only arranges elements
// and shows the returned 300 dpi bitmap, so what you see is exactly what the printer gets.
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const DPMM = 300 / 25.4;
let MEDIA = {};               // roll id -> {name, kind, printable, total, ...} from /api/media
let loaded = null;            // roll id the printer reports
const mediaOf = t => String(t.media || t.tape || "29");
const CODE_GROUPS = {
  "2D (matrix) codes": { datamatrix: "DATAMATRIX", qr: "QR", microqr: "MICRO QR", rmqr: "rMQR (thin QR)", aztec: "AZTEC",
    pdf417: "PDF417", compactpdf417: "COMPACT PDF417" },
  "1D barcodes": { code128: "CODE 128", code39: "CODE 39", code93: "CODE 93", codabar: "CODABAR", itf: "ITF (2 of 5)",
    ean13: "EAN-13", ean8: "EAN-8", upca: "UPC-A", upce: "UPC-E", databar: "GS1 DATABAR", databarltd: "DATABAR LIMITED",
    databarexp: "DATABAR EXPANDED" },
};
const CODE_NAMES = Object.assign({}, ...Object.values(CODE_GROUPS));
const NAMES = { text: "TEXT", image: "GRAPHIC", box: "BOX", line: "LINE", ...CODE_NAMES };
const CODES = Object.keys(CODE_NAMES);
const LINEAR = Object.keys(CODE_GROUPS["1D barcodes"]);
// sample data for codes that only take digits or a fixed shape
const SAMPLE = { ean13: "400638133393", ean8: "9638507", upca: "03600029145", upce: "0123456", itf: "12345678",
  codabar: "A12345B", databar: "0950110153001", databarltd: "0950110153001", databarexp: "(01)09501101530003" };
const FONTS = ["sans", "sans-bold", "narrow", "narrow-bold", "mono", "mono-bold"];

// saved colours from the colour designer (same 8 tokens as app.css)
try {
  const c = JSON.parse(localStorage.getItem("qllabel-colors") || "{}");
  for (const [k, v] of Object.entries(c.tokens || {})) document.documentElement.style.setProperty("--" + k, v);
  if (c.title) document.addEventListener("DOMContentLoaded", () => { $("#title").textContent = c.title; });
} catch (e) { /* storage blocked: defaults */ }

let tpl = blank();
let sel = null;
let zoom = 2, zoomMode = "fit";
let last = null;              // last preview reply
let nextId = 1;

function blank() {
  return { name: "", media: loaded || "29", length_mm: 20, margin: 35, cut: "each", cut_every: 1, flip: false,
    fields: { serial: "PTC-00123" }, elements: [] };
}

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

let msgTimer;
function say(text, err = false) {
  const m = $("#msg");
  m.textContent = text; m.className = "msg" + (err ? " err" : ""); m.hidden = false;
  clearTimeout(msgTimer);
  msgTimer = setTimeout(() => { m.hidden = true; }, err ? 12000 : 5000);
}

// ---------------------------------------------------------------- knobs (hardware-panel geometry)
function knob(host, o) {
  const S = 96, r = S / 2 - 6, cx = S / 2, cy = S / 2, a0 = Math.PI * 1.25, a1 = Math.PI * 2.75;
  host.innerHTML = `<span class="kl">${o.label}</span><svg viewBox="0 0 ${S} ${S}"></svg><span class="kv2"></span>`;
  const svg = $("svg", host), box = $(".kv2", host);
  const pt = (a, rr) => [cx + rr * Math.sin(a), cy - rr * Math.cos(a)];
  let ticks = "";
  for (let i = 0; i <= 10; i++) {
    const a = a0 + i / 10 * (a1 - a0), [x1, y1] = pt(a, r * 0.92), [x2, y2] = pt(a, i % 5 ? r * 0.97 : r);
    ticks += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--dimInk)" stroke-width="${i % 5 ? 1 : 1.6}"/>`;
  }
  const kr = r * 0.7, cap = kr * 0.78;
  svg.innerHTML = `<defs>
    <linearGradient id="sk${o.id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="color-mix(in srgb, var(--knobBody) 84%, white)"/><stop offset="1" stop-color="var(--knobBody)"/></linearGradient>
    <linearGradient id="cp${o.id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="color-mix(in srgb, var(--knobBody) 90%, white)"/><stop offset="1" stop-color="color-mix(in srgb, var(--knobBody) 40%, black)"/></linearGradient></defs>
    ${ticks}<path class="arc" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round"/>
    <circle cx="${cx + 1.5}" cy="${cy + 3}" r="${kr}" fill="#00000080"/>
    <circle cx="${cx}" cy="${cy}" r="${kr}" fill="url(#sk${o.id})"/><circle cx="${cx}" cy="${cy}" r="${cap}" fill="url(#cp${o.id})"/>
    <line class="ptr" stroke="var(--ink)" stroke-width="2.2" stroke-linecap="round"/>`;
  const arc = $(".arc", svg), ptr = $(".ptr", svg);
  const k = { value: o.value };
  const pos = v => o.log ? Math.log(v / o.min) / Math.log(o.max / o.min) : (v - o.min) / (o.max - o.min);
  const val = p => o.log ? o.min * Math.pow(o.max / o.min, p) : o.min + p * (o.max - o.min);
  const snap = v => Math.min(o.max, Math.max(o.min, Math.round(v / o.step) * o.step));
  k.set = (v, fire = false) => {
    k.value = snap(v);
    const a = a0 + pos(k.value) * (a1 - a0), [sx, sy] = pt(a0, r * 0.84), [ex, ey] = pt(a, r * 0.84);
    arc.setAttribute("d", `M${sx} ${sy} A${r * 0.84} ${r * 0.84} 0 ${a - a0 > Math.PI ? 1 : 0} 1 ${ex} ${ey}`);
    const [p1x, p1y] = pt(a, kr * 0.25), [p2x, p2y] = pt(a, kr * 0.92);
    ptr.setAttribute("x1", p1x); ptr.setAttribute("y1", p1y); ptr.setAttribute("x2", p2x); ptr.setAttribute("y2", p2y);
    box.textContent = o.fmt(k.value);
    if (fire) o.onChange(k.value);
  };
  let drag = null;
  svg.addEventListener("pointerdown", e => { drag = { y: e.clientY, p: pos(k.value) }; svg.setPointerCapture(e.pointerId); });
  svg.addEventListener("pointermove", e => {
    if (!drag) return;
    const p = Math.min(1, Math.max(0, drag.p + (drag.y - e.clientY) / (e.shiftKey ? 800 : 200)));
    k.set(val(p), true);
  });
  svg.addEventListener("pointerup", () => { drag = null; });
  svg.addEventListener("wheel", e => { e.preventDefault(); k.set(k.value + (e.deltaY < 0 ? o.step : -o.step), true); }, { passive: false });
  box.addEventListener("dblclick", () => {
    const v = parseFloat(prompt(o.label, k.value));
    if (!isNaN(v)) k.set(v, true);
  });
  box.title = "Double-click to type a value";
  k.set(o.value);
  return k;
}

const kLength = knob($("#k-length"), { id: "len", label: "LENGTH", min: 2, max: 1000, step: 0.5, value: 20, log: true,
  fmt: v => `${v.toFixed(1)} mm`, onChange: v => { tpl.length_mm = v; changed(); if (tpl.strip?.on) stripUI(); } });
const kMargin = knob($("#k-margin"), { id: "mar", label: "END FEED", min: 35, max: 200, step: 1, value: 35,
  fmt: v => `${(v / DPMM).toFixed(1)} mm`, onChange: v => { tpl.margin = v; changed(false); } });

function seg(host, value, onChange) {
  const set = v => $$("button", host).forEach(b => b.classList.toggle("on", b.dataset.v === String(v)));
  host.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    set(b.dataset.v); onChange(b.dataset.v);
  });
  set(value);
  return set;
}
const setCut = seg($("#cut"), "each", v => { tpl.cut = v; changed(false); });
const setAcross = seg($("#across"), "0", v => { tpl.across = v === "1"; changed(); });
seg($("#zoom"), "fit", v => { zoomMode = v; layout(); });
const setCCut = seg($("#c-cut"), "each", () => {});

// ---------------------------------------------------------------- tabs
$("#tabs").addEventListener("click", e => {
  const b = e.target.closest("button[data-tab]"); if (!b) return;
  $$("#tabs button[data-tab]").forEach(x => x.classList.toggle("on", x === b));
  $$("section.tab").forEach(s => { s.hidden = s.id !== "tab-" + b.dataset.tab; });
  if (b.dataset.tab === "batch") { listTables(); batchPreview(true); }
  if (b.dataset.tab === "printer") printerStatus(true);
  if (b.dataset.tab === "design") layout();
});

// ---------------------------------------------------------------- preview
let inflight = false, again = false;
async function refresh() {
  if (inflight) { again = true; return; }
  inflight = true;
  try {
    last = await api("api/preview", { template: tpl });
    $("#bitmap").src = "data:image/png;base64," + last.png;
    layout();
    drawChecks();
    drawFields();
  } catch (e) { say(e.message, true); }
  inflight = false;
  if (again) { again = false; refresh(); }
}

function changed(rerender = true) {
  saveDraft();
  if (rerender) refresh(); else layout();
}

function layout() {
  if (!last) return;
  const md = MEDIA[mediaOf(tpl)] || {};
  const w = last.w, h = last.h, m = md.kind && md.kind !== "continuous" ? 0 : tpl.margin;   // die-cut: no feed margin
  const across = !!tpl.across;   // then the tape runs down the screen: edges left/right, feed above/below
  const printable = across ? w : h, total = md.total || printable + 36, edge = (total - printable) / 2;
  $("#label").classList.toggle("round", md.kind === "round");
  if (zoomMode === "fit") {
    const avail = $("#stage").clientWidth - 60;
    zoom = across ? Math.max(0.5, Math.min(6, avail / total, 440 / (h + 2 * m)))
                  : Math.max(0.5, Math.min(6, avail / (w + 2 * m), 440 / total));
  } else zoom = +zoomMode;
  const tape = $("#tape");
  tape.classList.toggle("across", across);
  tape.style.padding = across ? `0 ${edge * zoom}px` : `${edge * zoom}px 0`;
  tape.style.setProperty("--edge", `${edge * zoom}px`);
  for (const f of [$("#feed-l"), $("#feed-r")]) {
    f.style.width = across ? `${w * zoom}px` : `${m * zoom}px`;
    f.style.height = across ? `${m * zoom}px` : "auto";
  }
  const lab = $("#label");
  lab.style.width = `${w * zoom}px`; lab.style.height = `${h * zoom}px`;
  const img = $("#bitmap");
  img.style.width = `${w * zoom}px`; img.style.height = `${h * zoom}px`;
  $("#gridlay").classList.toggle("on", $("#grid").checked);
  $("#gridlay").style.setProperty("--mm", `${DPMM * zoom}px`);
  $("#dims").textContent = `${last.w_mm.toFixed(1)} × ${last.h_mm.toFixed(1)} mm printable  ·  ${w} × ${h} dots  ·  ` +
    `piece ≈ ${(((across ? h : w) + 2 * m) / DPMM).toFixed(1)} mm with margin`;
  drawBoxes();
}

function drawBoxes() {
  const host = $("#boxes");
  host.innerHTML = "";
  for (const b of last.boxes) {
    const e = tpl.elements.find(x => x.id === b.id); if (!e) continue;
    const d = document.createElement("div");
    d.className = "el" + (b.id === sel ? " sel" : "") + (multi.has(b.id) && b.id !== sel ? " multi" : "") + (b.bad ? " bad" : "");
    d.dataset.id = b.id;
    // the element may have moved since this preview was made: place by the element, size by the preview
    Object.assign(d.style, { left: `${e.x * zoom}px`, top: `${e.y * zoom}px`, width: `${b.w * zoom}px`, height: `${b.h * zoom}px` });
    d.innerHTML = `<span class="tag">${NAMES[e.type]}  ${e.x}, ${e.y}</span>`;
    host.appendChild(d);
  }
}

function drawChecks() {
  const out = [];
  for (const c of last.checks) out.push(`<div class="chk ${c.ok ? "" : "no"}">${NAMES[c.type]} “${esc(c.data)}” ${c.ok ? "reads back OK" : "does NOT read back"}</div>`);
  for (const w of last.warnings) out.push(`<div class="chk warn">${esc(w)}</div>`);
  $("#checks").innerHTML = out.join("");
}

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ---------------------------------------------------------------- selecting, dragging, smart guides, keys
let drag = null;
const multi = new Set();      // more selected items besides `sel` (Shift+click)
const selected = () => sel ? [sel, ...[...multi].filter(id => id !== sel)] : [];
const boxOf = id => {         // size from the last preview, position from the element (it may have moved since)
  const e = tpl.elements.find(x => x.id === id), b = last && last.boxes.find(x => x.id === id);
  return e && b ? { x: e.x, y: e.y, w: b.w, h: b.h } : null;
};
function groupBox(ids) {
  const bs = ids.map(boxOf).filter(Boolean); if (!bs.length) return null;
  const x = Math.min(...bs.map(b => b.x)), y = Math.min(...bs.map(b => b.y));
  return { x, y, w: Math.max(...bs.map(b => b.x + b.w)) - x, h: Math.max(...bs.map(b => b.y + b.h)) - y };
}

// Snap the moving box to the label's centre/edges and other items' centres/edges; returns the shift and the guides.
function snap(box, ids, free) {
  const out = { dx: 0, dy: 0, guides: [] };
  if (free || !$("#snap").checked || !last) return out;
  const tol = 6 / zoom;
  const xs = [{ v: last.w / 2, label: true }, { v: 0, label: true }, { v: last.w, label: true }];
  const ys = [{ v: last.h / 2, label: true }, { v: 0, label: true }, { v: last.h, label: true }];
  for (const e of tpl.elements) {
    if (ids.includes(e.id)) continue;
    const b = boxOf(e.id); if (!b) continue;
    xs.push({ v: b.x }, { v: b.x + b.w / 2 }, { v: b.x + b.w });
    ys.push({ v: b.y }, { v: b.y + b.h / 2 }, { v: b.y + b.h });
  }
  const best = (anchors, lines) => {
    let hit = null;
    for (const a of anchors) for (const l of lines) {
      const d = l.v - a;
      if (Math.abs(d) <= tol && (!hit || Math.abs(d) < Math.abs(hit.d) || (Math.abs(d) === Math.abs(hit.d) && l.label))) hit = { d, l };
    }
    return hit;
  };
  const hx = best([box.x, box.x + box.w / 2, box.x + box.w], xs);
  const hy = best([box.y, box.y + box.h / 2, box.y + box.h], ys);
  if (hx) { out.dx = Math.round(hx.d); out.guides.push({ dir: "v", at: hx.l.v, label: !!hx.l.label }); }
  if (hy) { out.dy = Math.round(hy.d); out.guides.push({ dir: "h", at: hy.l.v, label: !!hy.l.label }); }
  return out;
}
function drawGuides(guides) {
  $("#guides").innerHTML = guides.map(g => `<div class="g ${g.dir} ${g.label ? "label" : "item"}" style="${g.dir === "v" ? "left" : "top"}:${g.at * zoom}px"></div>`).join("");
}
// guides for where the selection sits now: shown briefly after a nudge or an align
let guideTimer;
function flashGuides() {
  const ids = selected(), b = groupBox(ids); if (!b) return;
  const tol = 0.5, gs = [];
  if (Math.abs(b.x + b.w / 2 - last.w / 2) <= tol) gs.push({ dir: "v", at: last.w / 2, label: true });
  if (Math.abs(b.y + b.h / 2 - last.h / 2) <= tol) gs.push({ dir: "h", at: last.h / 2, label: true });
  for (const e of tpl.elements) {
    if (ids.includes(e.id)) continue;
    const o = boxOf(e.id); if (!o) continue;
    if ([o.x, o.x + o.w / 2, o.x + o.w].some(v => [b.x, b.x + b.w / 2, b.x + b.w].some(a => Math.abs(a - v) <= tol))) {
      const v = [o.x, o.x + o.w / 2, o.x + o.w].find(v => [b.x, b.x + b.w / 2, b.x + b.w].some(a => Math.abs(a - v) <= tol)); gs.push({ dir: "v", at: v });
    }
    if ([o.y, o.y + o.h / 2, o.y + o.h].some(v => [b.y, b.y + b.h / 2, b.y + b.h].some(a => Math.abs(a - v) <= tol))) {
      const v = [o.y, o.y + o.h / 2, o.y + o.h].find(v => [b.y, b.y + b.h / 2, b.y + b.h].some(a => Math.abs(a - v) <= tol)); gs.push({ dir: "h", at: v });
    }
  }
  drawGuides(gs);
  clearTimeout(guideTimer); guideTimer = setTimeout(() => drawGuides([]), 900);
}

$("#boxes").addEventListener("pointerdown", e => {
  const d = e.target.closest(".el"); if (!d) return;
  e.preventDefault();
  const id = d.dataset.id;
  if (e.shiftKey && sel) {                       // add to / take out of the selection
    if (id === sel) { const rest = selected().slice(1); sel = rest[0] || null; multi.clear(); rest.slice(1).forEach(x => multi.add(x)); }
    else if (multi.has(id)) multi.delete(id); else multi.add(id);
    markSelection(); drawProps(); return;
  }
  if (!selected().includes(id)) select(id);
  const ids = selected();
  drag = { x: e.clientX, y: e.clientY, ids, start: Object.fromEntries(ids.map(i => { const el = tpl.elements.find(x => x.id === i); return [i, [el.x, el.y]]; })),
    box: groupBox(ids), node: d };
  d.setPointerCapture(e.pointerId);
});
document.addEventListener("pointermove", e => {
  if (!drag) return;
  let dx = Math.round((e.clientX - drag.x) / zoom), dy = Math.round((e.clientY - drag.y) / zoom);
  const s = drag.box ? snap({ ...drag.box, x: drag.box.x + dx, y: drag.box.y + dy }, drag.ids, e.altKey) : { dx: 0, dy: 0, guides: [] };
  dx += s.dx; dy += s.dy;
  drawGuides(s.guides);
  for (const id of drag.ids) {
    const el = tpl.elements.find(x => x.id === id), [sx, sy] = drag.start[id];
    el.x = sx + dx; el.y = sy + dy;
    const node = $(`.el[data-id="${id}"]`);
    if (node) { node.style.left = `${el.x * zoom}px`; node.style.top = `${el.y * zoom}px`; $(".tag", node).textContent = `${NAMES[el.type]}  ${el.x}, ${el.y}`; }
  }
  refresh();
});
document.addEventListener("pointerup", () => { if (drag) { drag = null; drawGuides([]); changed(); drawProps(); } });
$("#stage").addEventListener("pointerdown", e => { if (!e.target.closest(".el")) select(null); });

document.addEventListener("keydown", e => {
  if (!sel || e.target.matches("input, textarea, select")) return;
  const step = e.shiftKey ? 10 : 1;
  const mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
  if (mv) {
    e.preventDefault();
    for (const id of selected()) { const el = tpl.elements.find(x => x.id === id); if (el) { el.x += mv[0]; el.y += mv[1]; } }
    changed(); drawProps(); flashGuides(); return;
  }
  if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeSelected(); }
  if (e.key.toLowerCase() === "d" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); duplicate(sel); }
});

function select(id) {
  sel = id; multi.clear();
  markSelection(); drawProps();
}
function markSelection() {
  $$("#boxes .el").forEach(d => { d.classList.toggle("sel", d.dataset.id === sel); d.classList.toggle("multi", multi.has(d.dataset.id) && d.dataset.id !== sel); });
  const n = selected().length;
  $("#selcount").textContent = n > 1 ? `${n} selected: lining up with each other` : n ? "1 selected: lining up on the label" : "";
}

// align: several items to each other, or one (or a group) on the label
$("#align").addEventListener("click", e => {
  const a = e.target.closest("button")?.dataset.a; if (!a || !last) return;
  const ids = selected(); if (!ids.length) return say("Select something first (Shift+click for several).", true);
  const g = groupBox(ids);
  const ref = ids.length > 1 && !a.startsWith("label") ? g : { x: 0, y: 0, w: last.w, h: last.h };
  if (a === "label-h" || a === "label-v") {   // move the whole selection, keeping its layout
    const dx = a === "label-h" ? Math.round(last.w / 2 - (g.x + g.w / 2)) : 0, dy = a === "label-v" ? Math.round(last.h / 2 - (g.y + g.h / 2)) : 0;
    ids.forEach(id => { const el = tpl.elements.find(x => x.id === id); el.x += dx; el.y += dy; });
  } else {
    for (const id of ids) {
      const el = tpl.elements.find(x => x.id === id), b = boxOf(id); if (!b) continue;
      if (a === "left") el.x = ref.x;
      if (a === "hcenter") el.x = Math.round(ref.x + ref.w / 2 - b.w / 2);
      if (a === "right") el.x = ref.x + ref.w - b.w;
      if (a === "top") el.y = ref.y;
      if (a === "vcenter") el.y = Math.round(ref.y + ref.h / 2 - b.h / 2);
      if (a === "bottom") el.y = ref.y + ref.h - b.h;
    }
  }
  changed(); drawProps(); setTimeout(flashGuides, 50);
});
function removeSelected() {
  const ids = selected(); tpl.elements = tpl.elements.filter(e => !ids.includes(e.id)); sel = null; multi.clear(); changed(); drawProps();
}

// ---------------------------------------------------------------- elements
const DEFAULTS = {
  text: { data: "{serial}", font: "sans-bold", size: 40, align: "left" },
  image: { src: "", w: 0, h: 118, threshold: 128, dither: false },
  box: { w: 120, h: 80, stroke: 3 },
  line: { w: 150, stroke: 3 },
};
for (const k of CODES) DEFAULTS[k] = LINEAR.includes(k)
  ? { data: SAMPLE[k] || "{serial}", module: 2, height: 80, hrt: "none", hrt_size: 28, hrt_gap: 6, hrt_font: "narrow-bold" }
  : { data: "{serial}", module: k === "pdf417" || k === "compactpdf417" ? 2 : 4, hrt: "none", hrt_size: 28, hrt_gap: 6, hrt_font: "narrow-bold" };
$("#add-code").innerHTML = Object.entries(CODE_GROUPS).map(([g, m]) =>
  `<optgroup label="${g}">${Object.entries(m).map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</optgroup>`).join("");
function uid() { let id; do { id = "e" + nextId++; } while (tpl.elements.some(e => e.id === id)); return id; }

function add(type) {
  const [x, y] = freeSpot(60, 60);
  const el = { id: uid(), type, x, y, rotate: 0, ...structuredClone(DEFAULTS[type]) };
  tpl.elements.push(el);
  sel = el.id; changed(); drawProps();
}
$("#add").addEventListener("click", e => { const b = e.target.closest("button"); if (b) add(b.dataset.t); });
$("#add-code-btn").addEventListener("click", () => add($("#add-code").value));
$("#add-line").addEventListener("click", () => add("line"));
// first place (scanning across, then down) where a w x h box overlaps nothing already on the label
function freeSpot(w, h) {
  if (!last) return [10, 10];
  const hit = (x, y) => last.boxes.some(b => x < b.x + b.w + 6 && x + w + 6 > b.x && y < b.y + b.h + 6 && y + h + 6 > b.y);
  for (let y = 10; y + h <= last.h; y += 10)
    for (let x = 10; x + w <= last.w; x += 10)
      if (!hit(x, y)) return [x, y];
  return [10, 10];
}
function remove(id) { tpl.elements = tpl.elements.filter(e => e.id !== id); sel = null; multi.clear(); changed(); drawProps(); }
function duplicate(id) {
  const src = tpl.elements.find(e => e.id === id); if (!src) return;
  const el = { ...structuredClone(src), id: uid(), x: src.x + 10, y: src.y + 10 };
  tpl.elements.push(el); sel = el.id; changed(); drawProps();
}

function drawProps() {
  const host = $("#props");
  const el = tpl.elements.find(e => e.id === sel);
  if (!el) { host.innerHTML = `<p class="dim">Click something on the label, or add one.</p>`; return; }
  const box = last && last.boxes.find(b => b.id === el.id);
  const mm = d => `${(d / DPMM).toFixed(2)} mm`;
  const num = (k, lab, unit = "dots", min = 0) =>
    `<span class="lab">${lab}</span><span class="pair2"><input type="number" data-k="${k}" value="${el[k] ?? 0}" min="${min}"><span class="unit" data-u="${k}">${unit === "dots" ? mm(el[k] ?? 0) : unit}</span></span>`;
  let h = `<div class="grid2">`;
  h += `<span class="lab">TYPE</span><span><b>${NAMES[el.type]}</b>${box ? `<span class="unit">${mm(box.w)} × ${mm(box.h)}</span>` : ""}</span>`;
  if (el.type === "text" || CODES.includes(el.type))
    h += `<span class="lab">DATA</span><textarea data-k="data" rows="${el.type === "text" ? 2 : 1}" spellcheck="false">${esc(el.data || "")}</textarea>`;
  h += num("x", "X", "dots", -9999) + num("y", "Y", "dots", -9999);
  if (el.type === "text") {
    h += `<span class="lab">FONT</span><select data-k="font">${FONTS.map(f => `<option${f === el.font ? " selected" : ""}>${f}</option>`).join("")}</select>`;
    h += num("size", "SIZE");
    h += `<span class="lab">ALIGN</span><div class="seg" data-seg="align">${["left", "center", "right"].map(a => `<button data-v="${a}" class="${(el.align || "left") === a ? "on" : ""}">${a.toUpperCase()}</button>`).join("")}</div>`;
  }
  if (CODES.includes(el.type)) {
    h += `<span class="lab">CODE</span><select data-k="type">${Object.entries(CODE_GROUPS).map(([g, m]) =>
      `<optgroup label="${g}">${Object.entries(m).map(([k, n]) => `<option value="${k}"${k === el.type ? " selected" : ""}>${n}</option>`).join("")}</optgroup>`).join("")}</select>`;
    h += num("module", "MODULE", "dots", 1);
    if (LINEAR.includes(el.type)) h += num("height", "HEIGHT", "dots", 1);
    const hrt = el.hrt || "none";
    h += `<span class="lab">TEXT</span><div class="seg" data-seg="hrt">${["none", "below", "above", "right", "left"].map(a => `<button data-v="${a}" class="${hrt === a ? "on" : ""}">${a.toUpperCase()}</button>`).join("")}</div>`;
    if (hrt !== "none") {
      h += `<span class="lab">SAYS</span><input data-k="hrt_text" value="${esc(el.hrt_text || "")}" placeholder="(same as the code)" spellcheck="false">`;
      h += `<span class="lab">TEXT FONT</span><select data-k="hrt_font">${FONTS.map(f => `<option${f === (el.hrt_font || "narrow-bold") ? " selected" : ""}>${f}</option>`).join("")}</select>`;
      el.hrt_size ??= 28; el.hrt_gap ??= 6;
      h += num("hrt_size", "TEXT SIZE") + num("hrt_gap", "GAP");
    }
  }
  if (el.type === "image") {
    h += `<span class="lab">PICTURE</span><span id="pick-name" class="dim">${el.src ? "" : "none yet: pick one below"}</span>`;
    h += num("h", "HEIGHT", "dots", 0) + num("w", "WIDTH", "dots", 0);
    h += `<span></span><span class="dim">0 = follows the other side, keeping the shape</span>`;
    h += `<span class="lab">LEVEL</span><span class="pair2"><input type="number" data-k="threshold" value="${el.threshold ?? 128}" min="1" max="254"><span class="unit">0–255</span></span>`;
  }
  if (el.type === "box") h += num("w", "WIDTH", "dots", 1) + num("h", "HEIGHT", "dots", 1) + num("stroke", "STROKE", "dots", 1);
  if (el.type === "line") h += num("w", "LENGTH", "dots", 1) + num("stroke", "THICK", "dots", 1);
  h += `<span class="lab">ROTATE</span><div class="seg" data-seg="rotate">${[0, 90, 180, 270].map(a => `<button data-v="${a}" class="${(+el.rotate || 0) === a ? "on" : ""}">${a}°</button>`).join("")}</div>`;
  h += `<span class="lab">STYLE</span><span>`;
  if (el.type === "box") h += `<label class="check"><input type="checkbox" data-k="filled"${el.filled ? " checked" : ""}> filled</label> `;
  if (el.type === "image") h += `<label class="check"><input type="checkbox" data-k="dither"${el.dither ? " checked" : ""}> dither (photos)</label> `;
  h += `<label class="check"><input type="checkbox" data-k="invert"${el.invert ? " checked" : ""}> white on black</label></span>`;
  h += `</div><div class="props-actions">
    <button data-a="ch">CENTRE ↔</button><button data-a="cv">CENTRE ↕</button>
    <button data-a="front">TO FRONT</button><button data-a="back">TO BACK</button>
    <button data-a="dup">DUPLICATE</button><button data-a="del">DELETE</button></div>`;
  if (el.type === "image") h += `<div class="picker">
    <div class="row tight"><label class="btn grow" for="img-file">UPLOAD A PICTURE…</label>
      <input type="file" id="img-file" accept="image/*,.svg" hidden></div>
    <span class="lab">BUILT IN</span><div class="gal" id="gal-built"></div>
    <span class="lab">UPLOADED</span><div class="gal" id="gal-up"><span class="dim">…</span></div></div>`;
  host.innerHTML = h;
  if (el.type === "image") picker(el);

  $$("[data-k]", host).forEach(inp => inp.addEventListener("input", () => {
    const k = inp.dataset.k;
    el[k] = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? (parseInt(inp.value, 10) || 0) : inp.value;
    const u = $(`[data-u="${k}"]`, host); if (u && inp.type === "number") u.textContent = mm(el[k]);
    if (k === "type") {   // switching symbology: keep the data unless the new code can't take it
      if (SAMPLE[el.type]) el.data = SAMPLE[el.type];
      if (LINEAR.includes(el.type) && !el.height) { el.height = 80; el.module = 2; }
      changed(); return drawProps();
    }
    changed();
  }));
  $$("[data-seg]", host).forEach(s => s.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    $$("button", s).forEach(x => x.classList.toggle("on", x === b));
    el[s.dataset.seg] = s.dataset.seg === "rotate" ? +b.dataset.v : b.dataset.v;
    changed();
    if (s.dataset.seg === "hrt") drawProps();
  }));
  $(".props-actions", host).addEventListener("click", e => {
    const a = e.target.closest("button")?.dataset.a; if (!a) return;
    const b = last && last.boxes.find(x => x.id === el.id);
    if (a === "ch" && b) el.x = Math.round((last.w - b.w) / 2);
    if (a === "cv" && b) el.y = Math.round((last.h - b.h) / 2);
    if (a === "front") { tpl.elements = tpl.elements.filter(x => x !== el); tpl.elements.push(el); }
    if (a === "back") { tpl.elements = tpl.elements.filter(x => x !== el); tpl.elements.unshift(el); }
    if (a === "dup") return duplicate(el.id);
    if (a === "del") return remove(el.id);
    changed(); drawProps();
  });
}

function drawFields() {
  const host = $("#fields");
  const names = last.fields;
  const key = names.join(",");
  if (host.dataset.key === key) return;
  host.dataset.key = key;
  if (!names.length) { host.innerHTML = `<span class="dim" style="grid-column: 1 / 3">No {fields} used yet.</span>`; return; }
  host.innerHTML = names.map(n => `<span class="lab">${esc(n.toUpperCase())}</span><input data-f="${esc(n)}" value="${esc(tpl.fields[n] ?? "")}" spellcheck="false">`).join("");
  $$("input", host).forEach(i => i.addEventListener("input", () => { tpl.fields[i.dataset.f] = i.value; changed(); }));
}

$("#fit").addEventListener("click", () => {
  if (!last || !last.boxes.length) return;
  const a = tpl.across ? ["y", "h"] : ["x", "w"];   // the direction that runs along the tape
  const lo = Math.max(0, Math.min(...last.boxes.map(b => b[a[0]])));
  const hi = Math.max(...last.boxes.map(b => b[a[0]] + b[a[1]]));
  tpl.length_mm = Math.round((hi + lo) / DPMM * 10) / 10;
  kLength.set(tpl.length_mm);
  changed();
});
$("#flip").addEventListener("change", e => { tpl.flip = e.target.checked; changed(false); });
$("#grid").addEventListener("change", layout);
window.addEventListener("resize", layout);

// ---------------------------------------------------------------- templates
async function listTemplates(select) {
  const r = await api("api/templates");
  const s = $("#tpl-list");
  s.innerHTML = `<option value="">(unsaved)</option>` + r.templates.map(t => `<option>${esc(t.name)}</option>`).join("");
  s.value = select || tpl.name || "";
}
function use(t) {
  tpl = { ...blank(), ...t };
  nextId = 1; sel = null; multi.clear();
  $("#tpl-name").value = tpl.name;
  tpl.margin = Math.max(35, tpl.margin ?? 35);   // the printer won't feed less than 35 dots (~3 mm) per page
  kLength.set(tpl.length_mm); kMargin.set(tpl.margin); setCut(tpl.cut); setAcross(tpl.across ? "1" : "0");
  tpl.media = mediaOf(tpl); delete tpl.tape;
  mediaNote(); stripUI();
  $("#flip").checked = !!tpl.flip;
  $("#fields").dataset.key = "";
  batch = null; D();
  drawProps(); changed(); batchPreview(!$("#tab-batch").hidden);
}
$("#tpl-list").addEventListener("change", async e => {
  if (!e.target.value) return;
  try { use(await api("api/template?name=" + encodeURIComponent(e.target.value))); } catch (x) { say(x.message, true); }
});
$("#tpl-new").addEventListener("click", () => { use(blank()); $("#tpl-list").value = ""; });
$("#tpl-save").addEventListener("click", async () => {
  tpl.name = $("#tpl-name").value.trim();
  if (!tpl.name) { say("Give the template a name first.", true); $("#tpl-name").focus(); return; }
  try { await api("api/save", { template: tpl }); await listTemplates(tpl.name); say(`Saved “${tpl.name}”.`); saveDraft(); }
  catch (e) { say(e.message, true); }
});
$("#tpl-del").addEventListener("click", async () => {
  const n = $("#tpl-list").value;
  if (!n || !confirm(`Delete the template “${n}”?`)) return;
  try { await api("api/delete", { name: n }); await listTemplates(""); say(`Deleted “${n}”.`); } catch (e) { say(e.message, true); }
});
function saveDraft() { try { localStorage.setItem("qllabel-draft", JSON.stringify(tpl)); } catch (e) { /* fine */ } }

// ---------------------------------------------------------------- printing
async function doPrint(rows, copies, btn) {
  btn.disabled = true;
  const old = btn.textContent; btn.textContent = "PRINTING…";
  try {
    const r = await api("api/print", { template: tpl, rows, copies });
    const what = `${r.labels} label(s)` + (r.strips ? ` on ${r.strips} strip(s)` : "");
    say(r.dry_run ? `Dry run: ${what} written to ${r.dry_run}` : `Printed ${what}.`);
  } catch (e) { say(e.message, true); }
  btn.disabled = false; btn.textContent = old;
  printerStatus(true);
}
$("#print").addEventListener("click", e => D().on ? printBatch(e.target, +$("#copies").value || 1) : doPrint([{}], +$("#copies").value || 1, e.target));

// ---------------------------------------------------------------- data table + batch (see qllabel/data.py)
const MODE_NAMES = { sequence: "Sequence (001, 002…)", ip: "IP address (counts up)", fixed: "Same on every label", manual: "Typed / from CSV" };
const D = () => {
  if (!(tpl.data && tpl.data.columns) && tpl.batch && (tpl.batch.source || "range") === "range") {   // older one-field batch
    const o = tpl.batch, f = o.field || "num";
    tpl.data = { on: !!o.on, main: f, count: o.count ?? 10, advance: o.advance !== false, rows: [],
      columns: [{ name: f, mode: "sequence", prefix: o.prefix || "", start: o.start ?? 1, step: o.step || 1, digits: o.digits ?? 3, suffix: o.suffix || "" }] };
    delete tpl.batch;
  }
  const d = (tpl.data = tpl.data && tpl.data.columns ? tpl.data : { on: false, main: "num", count: 10, advance: true, columns: [], rows: [] });
  d.rows = d.rows || [];
  return d;
};
let batch = null;            // last /api/batch reply: {count, rows, warnings, data}
const setMode = seg($("#mode"), "single", v => { D().on = v === "batch"; changed(false); batchSummary(); });
const colDefaults = { sequence: { prefix: "", start: 1, step: 1, digits: 3, suffix: "" }, ip: { start: "10.0.0.1", step: 1 }, fixed: { value: "" }, manual: {} };

function renderGrid() {
  const d = D(), used = new Set((last && last.fields) || []);
  const rowsShown = Math.max(batch ? batch.count : 0, d.rows.length) + (mainCol()?.mode === "manual" ? 1 : 0);
  const head = `<tr><th class="rn">#</th>${d.columns.map((c, ci) => {
    const set = c.mode === "sequence" ? `<div class="set"><span>BEFORE</span><input data-k="prefix" value="${esc(c.prefix ?? "")}"><span>START</span><input type="number" data-k="start" value="${esc(c.start)}">
        <span>STEP</span><input type="number" data-k="step" value="${esc(c.step)}"><span>DIGITS</span><input type="number" data-k="digits" min="0" max="12" value="${esc(c.digits)}"><span>AFTER</span><input data-k="suffix" value="${esc(c.suffix ?? "")}"></div>`
      : c.mode === "ip" ? `<div class="set"><span>FIRST</span><input data-k="start" value="${esc(c.start)}" placeholder="10.0.1.11"><span>STEP</span><input type="number" data-k="step" value="${esc(c.step)}"></div>`
      : c.mode === "fixed" ? `<div class="set"><span>VALUE</span><input data-k="value" value="${esc(c.value ?? "")}"></div>` : "";
    return `<th data-ci="${ci}" class="${c.name === d.main ? "main" : ""}">
      <div class="hrow"><input class="nm" data-k="name" value="${esc(c.name)}" title="Use it on the label as {${esc(c.name)}}">
        <button class="x" data-del="${ci}" title="Remove this column">✕</button></div>
      <div class="hrow"><label class="mainpick" title="The main column counts and orders the rows; the others follow it"><input type="radio" name="d-main" data-main="${ci}"${c.name === d.main ? " checked" : ""}> MAIN</label>
        <select data-k="mode">${Object.entries(MODE_NAMES).map(([k, n]) => `<option value="${k}"${k === c.mode ? " selected" : ""}>${n}</option>`).join("")}</select></div>
      ${set}${used.has(c.name) ? "" : `<div class="unused">not on the label yet</div>`}</th>`;
  }).join("")}</tr>`;
  let body = "";
  for (let r = 0; r < Math.min(rowsShown, 500); r++) {
    const extra = batch && r >= batch.count;
    body += `<tr class="${extra ? "extra" : ""}"><td class="rn">${r + 1}</td>` + d.columns.map((c, ci) => {
      if (c.mode === "manual") {
        const v = (d.rows[r] || {})[c.name] ?? "";
        return `<td class="${!extra && !String(v).trim() ? "miss" : ""}"><input data-r="${r}" data-c="${ci}" value="${esc(v)}" spellcheck="false"></td>`;
      }
      return `<td class="calc" data-r="${r}" data-c="${ci}">${extra ? "" : esc(batch?.rows[r]?.[c.name] ?? "")}</td>`;
    }).join("") + `</tr>`;
  }
  $("#dt").innerHTML = head + body;
  $("#d-count").value = d.count; $("#d-advance").checked = d.advance !== false;
  $("#d-count").disabled = mainCol()?.mode === "manual";
  $("#d-count").title = mainCol()?.mode === "manual" ? "The main column is typed: one label per filled row" : "";
}
const mainCol = () => D().columns.find(c => c.name === D().main);

// header edits (name, mode, sequence settings), main radio, delete
$("#dt").addEventListener("change", e => {
  const d = D(), th = e.target.closest("th[data-ci]");
  if (e.target.dataset.main !== undefined) { d.main = d.columns[+e.target.dataset.main].name; dataChanged(true); return; }
  if (!th) return;
  const c = d.columns[+th.dataset.ci], k = e.target.dataset.k;
  if (k === "name") {
    const nv = e.target.value.trim().replace(/\W/g, "_");
    if (!nv || d.columns.some(x => x !== c && x.name === nv)) { say("Column names must be different, letters, digits and _ only.", true); e.target.value = c.name; return; }
    d.rows.forEach(r => { if (c.name in r) { r[nv] = r[c.name]; delete r[c.name]; } });
    if (d.main === c.name) d.main = nv;
    c.name = nv; dataChanged(true); return;
  }
  if (k === "mode") {
    const keep = { name: c.name, mode: e.target.value };
    Object.keys(c).forEach(x => delete c[x]); Object.assign(c, keep, colDefaults[keep.mode]);
    dataChanged(true); return;
  }
  if (k) { c[k] = e.target.type === "number" ? (parseInt(e.target.value, 10) || 0) : e.target.value; dataChanged(false); }
});
$("#dt").addEventListener("click", e => {
  const del = e.target.closest("[data-del]"); if (!del) return;
  const d = D(), c = d.columns[+del.dataset.del];
  if (!confirm(`Remove the column {${c.name}}?`)) return;
  d.columns.splice(+del.dataset.del, 1);
  if (d.main === c.name) d.main = d.columns[0]?.name || "";
  dataChanged(true);
});
// typed cells, and pasting a block from a spreadsheet
$("#dt").addEventListener("input", e => {
  const i = e.target; if (i.dataset.r === undefined) return;
  const d = D(), r = +i.dataset.r, c = d.columns[+i.dataset.c];
  while (d.rows.length <= r) d.rows.push({});
  d.rows[r][c.name] = i.value;
  i.parentElement.classList.toggle("miss", !i.value.trim());
  dataChanged(false, r >= (batch?.count ?? 0));
});
$("#dt").addEventListener("paste", e => {
  const i = e.target; if (i.dataset.r === undefined) return;
  const text = (e.clipboardData || window.clipboardData).getData("text");
  if (!/[\t\n]/.test(text.trim())) return;
  e.preventDefault();
  const d = D(), r0 = +i.dataset.r, manual = d.columns.map((c, ci) => ci).filter(ci => d.columns[ci].mode === "manual" && ci >= +i.dataset.c);
  text.replace(/\r/g, "").replace(/\n$/, "").split("\n").forEach((line, dr) => {
    while (d.rows.length <= r0 + dr) d.rows.push({});
    line.split("\t").forEach((v, dc) => { if (dc < manual.length) d.rows[r0 + dr][d.columns[manual[dc]].name] = v.trim(); });
  });
  dataChanged(true);
});

$("#d-addcol").addEventListener("click", () => {
  const d = D(); let n = d.columns.length + 1, name;
  do { name = "field" + n++; } while (d.columns.some(c => c.name === name));
  d.columns.push({ name, mode: "manual" });
  if (!d.main) d.main = name;
  dataChanged(true);
});
$("#d-addrow").addEventListener("click", () => { D().rows.push({}); dataChanged(true); });
$("#d-count").addEventListener("input", e => { D().count = Math.max(0, Math.min(500, parseInt(e.target.value, 10) || 0)); dataChanged(false, true); });
$("#d-advance").addEventListener("change", e => { D().advance = e.target.checked; changed(false); });

// CSV in and out
function parseCSV(text) {
  const rows = []; let row = [], f = "", q = false;
  const delim = (text.split("\n")[0].match(/;/g) || []).length > (text.split("\n")[0].match(/,/g) || []).length ? ";" : text.split("\n")[0].includes("\t") ? "\t" : ",";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) { if (ch === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += ch; }
    else if (ch === '"') q = true;
    else if (ch === delim) { row.push(f); f = ""; }
    else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(f); rows.push(row); row = []; f = ""; }
    else f += ch;
  }
  if (f || row.length) { row.push(f); rows.push(row); }
  return rows.filter(r => r.some(x => x.trim()));
}
$("#d-csv").addEventListener("change", async e => {
  const file = e.target.files[0]; if (!file) return;
  const rows = parseCSV((await file.text()).replace(/^﻿/, ""));
  e.target.value = "";
  if (rows.length < 2) return say("That CSV has no rows under its header.", true);
  const d = D(), head = rows[0].map(h => h.trim().replace(/\W/g, "_"));
  head.forEach(h => {   // columns by name: existing ones become typed, new ones are added
    const c = d.columns.find(x => x.name === h);
    if (c) { Object.keys(c).forEach(x => x !== "name" && delete c[x]); c.mode = "manual"; } else if (h) d.columns.push({ name: h, mode: "manual" });
  });
  d.rows = rows.slice(1).map(r => Object.fromEntries(head.map((h, i) => [h, (r[i] ?? "").trim()]).filter(([h]) => h)));
  if (!d.columns.some(c => c.name === d.main)) d.main = head[0];
  dataChanged(true);
  say(`Imported ${d.rows.length} rows: ${head.join(", ")}. Check which column is MAIN.`);
});
$("#d-export").addEventListener("click", () => {
  if (!batch) return;
  const cols = D().columns.map(c => c.name), q = v => /[",\n]/.test(v) ? `"${String(v).replace(/"/g, '""')}"` : v;
  const csv = [cols.join(","), ...batch.rows.map(r => cols.map(c => q(r[c] ?? "")).join(","))].join("\n") + "\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `${tpl.name || "labels"}-data.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

// saved tables, to reuse in other templates
async function listTables() {
  try { const r = await api("api/tables"); $("#d-tables").innerHTML = `<option value="">(saved tables)</option>` + r.tables.map(t => `<option>${esc(t)}</option>`).join(""); }
  catch (e) { /* not fatal */ }
}
$("#d-load").addEventListener("click", async () => {
  const n = $("#d-tables").value; if (!n) return;
  try { const t = await api("api/table?name=" + encodeURIComponent(n)); Object.assign(D(), t); dataChanged(true); say(`Loaded the table “${n}”.`); }
  catch (e) { say(e.message, true); }
});
$("#d-saveas").addEventListener("click", async () => {
  const n = prompt("Save this table as:", tpl.name ? tpl.name + "-data" : ""); if (!n) return;
  try { await api("api/save_table", { name: n.trim(), data: D() }); await listTables(); say(`Saved the table “${n}”.`); }
  catch (e) { say(e.message, true); }
});

let dpTimer;
function dataChanged(structure, recount = false) {
  changed(false);
  if (structure) renderGrid();
  clearTimeout(dpTimer); dpTimer = setTimeout(() => batchPreview(structure || recount), structure ? 0 : 350);
}
async function batchPreview(regrid = true) {
  try {
    batch = await api("api/batch", { template: tpl });
    // the server adds a column for any {field} on the label that has none yet
    const d = D();
    if (!d.columns.length) { Object.assign(d, batch.data); regrid = true; }
    for (const c of batch.data.columns) if (!d.columns.some(x => x.name === c.name)) { d.columns.push(c); regrid = true; }
    if (!d.main) d.main = batch.data.main;
  } catch (e) { batch = null; $("#b-count").textContent = e.message; }
  if (regrid) renderGrid(); else if (batch) $$("#dt td.calc").forEach(td => { td.textContent = batch.rows[+td.dataset.r]?.[D().columns[+td.dataset.c].name] ?? ""; });
  if (!batch) return batchSummary();
  $("#b-count").textContent = `${batch.count} label${batch.count === 1 ? "" : "s"}` + (batch.count ? `  ·  decode checked on rows ${batch.checked.join(", ")}` : "");
  $("#b-warn").innerHTML = batch.warnings.map(w => `<div class="chk">${esc(w)}</div>`).join("");
  for (const [id, row] of [["#b-first", batch.first[0]], ["#b-last", batch.last]]) {
    const img = $(id);
    if (!row) { img.removeAttribute("src"); continue; }
    try { const r = await api("api/preview", { template: tpl, values: row }); img.src = "data:image/png;base64," + r.png; img.style.width = `${r.w}px`; }
    catch (e) { /* the design tab shows render errors */ }
  }
  batchSummary();
}
async function batchSummary() {
  const d = D();
  setMode(d.on ? "batch" : "single");
  if (!d.on) { $("#batch-sum").textContent = "Prints the label as shown, with the test values above."; return; }
  try {
    const info = batch || await api("api/batch", { template: tpl });
    const show = r => r ? r[d.main] ?? Object.values(r)[0] : "";
    $("#batch-sum").textContent = `${info.count} labels from the data table (main {${d.main}}): ` +
      `${show(info.first[0])}${info.count > 1 ? " … " + show(info.last) : ""}. Edit it on the DATA & BATCH tab.`;
  } catch (e) { $("#batch-sum").textContent = e.message; }
}

async function printBatch(btn, copies) {
  let info;
  try { info = await api("api/batch", { template: tpl }); } catch (e) { return say(e.message, true); }
  if (info.count * copies > 20 && !confirm(`Print ${info.count * copies} labels?`)) return;
  btn.disabled = true;
  const old = btn.textContent; btn.textContent = "PRINTING…";
  try {
    const r = await api("api/print_batch", { template: tpl, copies });
    const what = `${r.labels} labels` + (r.strips ? ` on ${r.strips} strip(s)` : "");
    let m = r.dry_run ? `Dry run: ${what} written to ${r.dry_run}.` : `Printed ${what}.`;
    if (r.data) {
      D().columns = r.data.columns; changed(false);
      m += ` Next batch starts at ${r.next_start}` + (r.advanced ? ` (saved in “${r.advanced}”).` : " (save the template to keep it).");
    }
    say(m);
  } catch (e) { say(e.message, true); }
  btn.disabled = false; btn.textContent = old;
  batchPreview(); printerStatus(true);
}
$("#batch-print").addEventListener("click", e => printBatch(e.target, +$("#b-copies").value || 1));

// ---------------------------------------------------------------- graphics
const ICONS = {
  arrow: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M10 40h50V18l32 32-32 32V60H10z"/></svg>',
  warning: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 6 96 92H4z" fill="none" stroke="#000" stroke-width="9" stroke-linejoin="round"/><rect x="45" y="34" width="10" height="32"/><rect x="45" y="72" width="10" height="10"/></svg>',
  esd: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 6 96 92H4z" fill="none" stroke="#000" stroke-width="7" stroke-linejoin="round"/><path d="M38 80c0-14 4-22 10-30l-6-8 10-6 6 10c4-2 8-2 10 2l-4 6-4-2c-4 8-6 16-6 28z"/><path d="M28 40 72 84" stroke="#000" stroke-width="6"/></svg>',
  check: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M10 54l26 26L90 22" fill="none" stroke="#000" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  pin1: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="none" stroke="#000" stroke-width="10"/><circle cx="50" cy="50" r="18"/></svg>',
  ground: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M50 6v44M14 50h72M28 68h44M42 86h16" stroke="#000" stroke-width="9" stroke-linecap="round"/></svg>',
  hv: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M58 4 22 56h24L36 96l42-58H54z"/></svg>',
  hand: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" fill="none" stroke="#000" stroke-width="8"/><path d="M20 20 80 80" stroke="#000" stroke-width="8"/><path d="M36 74V40a5 5 0 0 1 10 0v-8a5 5 0 0 1 10 0v4a5 5 0 0 1 10 0v26c0 8-6 14-14 14h-6c-6 0-10-2-10-2z"/></svg>',
};
// any picture (also SVG) -> PNG on a canvas, so the Pi only ever stores PNGs
function toPng(url, maxSide = 1000) {
  return new Promise((ok, bad) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, maxSide / Math.max(img.naturalWidth || maxSide, img.naturalHeight || maxSide));
      const w = Math.max(1, Math.round((img.naturalWidth || maxSide) * s)), h = Math.max(1, Math.round((img.naturalHeight || maxSide) * s));
      const c = document.createElement("canvas"); c.width = w; c.height = h;
      const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, w, h); g.drawImage(img, 0, 0, w, h);
      ok(c.toDataURL("image/png"));
    };
    img.onerror = () => bad(new Error("That file isn't a picture the browser can read."));
    img.src = url;
  });
}
async function useGraphic(el, name, pngUrl) {
  const r = await api("api/image", { name, png: pngUrl });
  el.src = r.src;
  changed(); drawProps();
}
async function picker(el) {
  $("#gal-built").innerHTML = Object.entries(ICONS).map(([k, svg]) =>
    `<button data-icon="${k}" title="${k}"><img src="data:image/svg+xml;base64,${btoa(svg)}" alt="${k}"></button>`).join("");
  $("#gal-built").addEventListener("click", async e => {
    const b = e.target.closest("button"); if (!b) return;
    try { await useGraphic(el, b.dataset.icon, await toPng("data:image/svg+xml;base64," + btoa(ICONS[b.dataset.icon]), 600)); }
    catch (x) { say(x.message, true); }
  });
  $("#img-file").addEventListener("change", async e => {
    const f = e.target.files[0]; if (!f) return;
    const url = URL.createObjectURL(f);
    try { await useGraphic(el, f.name, await toPng(url)); } catch (x) { say(x.message, true); }
    URL.revokeObjectURL(url);
  });
  try {
    const r = await api("api/images");
    const g = $("#gal-up"); if (!g) return;
    g.innerHTML = r.images.map(i => `<button data-src="${esc(i.src)}" class="${i.src === el.src ? "on" : ""}" title="${esc(i.name)}">${i.png ? `<img src="data:image/png;base64,${i.png}" alt="">` : esc(i.name)}</button>`).join("")
      || `<span class="dim">Nothing uploaded yet.</span>`;
    g.addEventListener("click", e => { const b = e.target.closest("button"); if (b) { el.src = b.dataset.src; changed(); drawProps(); } });
    const cur = r.images.find(i => i.src === el.src);
    if (cur && $("#pick-name")) $("#pick-name").textContent = cur.name;
  } catch (x) { say(x.message, true); }
}

$("#c-print").addEventListener("click", async e => {
  const btn = e.target; btn.disabled = true;
  try {
    const lengths = $("#c-lengths").value.split(/[,\s]+/).filter(Boolean).map(Number);
    const r = await api("api/calibrate", { lengths, margin: +$("#c-margin").value, cut: $("#c-cut .on").dataset.v, media: MEDIA[mediaOf(tpl)]?.kind === "continuous" ? mediaOf(tpl) : null, flip: !!tpl.flip });
    say(r.dry_run ? `Dry run written to ${r.dry_run}` : `Printed ${r.pages} test labels.`);
  } catch (x) { say(x.message, true); }
  btn.disabled = false;
});

// ---------------------------------------------------------------- printer status
async function printerStatus(show = false) {
  let s;
  try { s = await api("api/status"); } catch (e) { s = { ok: false, error: e.message }; }
  const c = $("#conn");
  c.className = "conn " + (s.ok ? "ok" : "bad");
  c.textContent = s.error ? "PRINTER OFFLINE" : s.busy ? "PRINTING" :
    s.errors && s.errors.length ? s.errors.join(", ").toUpperCase() : (s.media_name || "").toUpperCase() + (s.dry_run ? " · DRY RUN" : "");
  c.title = s.error || "";
  if (s.media) loaded = s.media;
  if (s.media && s.media !== mediaOf(tpl) && MEDIA[mediaOf(tpl)])
    c.textContent += ` · LABEL IS FOR ${MEDIA[mediaOf(tpl)].name.toUpperCase()}`;
  mediaNote();
  if (show) {
    const rows = s.error ? [["Status", s.error]] : [["Status", s.busy ? "printing" : s.errors.length ? s.errors.join(", ") : "ready"],
      ["Loaded", s.media_name], ["Fixed length", s.media_length ? `${s.media_length} mm` : "none (continuous)"],
      ["Device", s.device], ["Mode", s.dry_run ? "dry run (nothing is sent)" : "live"]];
    $("#pstat").innerHTML = rows.map(([k, v]) => `<b>${k}</b><span>${esc(v)}</span>`).join("");
  }
}
$("#p-refresh").addEventListener("click", () => printerStatus(true));
setInterval(() => { if (!document.hidden) printerStatus(); }, 6000);

// ---------------------------------------------------------------- help: "?" links to the help page, and hover tips
const HELP_FOR = { "TEMPLATE": "templates", "LABEL": "label-size-and-roll", "ADD": "items-you-can-add",
  "ELEMENT": "items-you-can-add", "FIELDS": "fields-and-the-data-batch-table", "PRINT": "printing",
  "DATA TABLE": "fields-and-the-data-batch-table", "THE BATCH": "fields-and-the-data-batch-table",
  "PRINTER": "printer-and-calibration-tabs", "FULL-WIDTH BLEED": "printer-and-calibration-tabs",
  "FIND THE PRINTER'S REAL LIMITS": "printer-and-calibration-tabs", "COMMAND LINE (FOR PTC LATER)": "command-line-on-the-pi" };
$$("h2").forEach(h => {
  const id = HELP_FOR[h.textContent.trim()];
  if (id) h.insertAdjacentHTML("beforeend", `<a class="q" href="help#${id}" target="_blank" title="Help on this">?</a>`);
});
$("#align .lab").insertAdjacentHTML("beforeend", `<a class="q" href="help#the-align-bar" target="_blank" title="Help on aligning">?</a>`);
const TIPS = {
  "#k-length": "Label length along the tape. Drag up/down, scroll, or double-click the value to type it.",
  "#k-margin": "Blank tape the printer adds before and after each piece (at least 3 mm). Use STRIP for no gaps.",
  '#add [data-t="text"]': "Add a line of text. Use {name} to fill it from a field.",
  '#add [data-t="image"]': "Add a logo or symbol: built-in ones or upload a picture.",
  '#add [data-t="datamatrix"]': "Add a DataMatrix: the most compact 2D code, best for small labels.",
  '#add [data-t="qr"]': "Add a QR code: easiest to scan with a phone.",
  '#add [data-t="code128"]': "Add a normal 1D barcode (Code 128).",
  '#add [data-t="box"]': "Add a rectangle (outline or filled).",
  "#add-code": "Every other barcode type", "#add-code-btn": "Add the code chosen on the left", "#add-line": "Add a straight line",
  '#cut [data-v="each"]': "Cut after every label", '#cut [data-v="end"]': "Cut once, after the last label", '#cut [data-v="none"]': "Don't cut",
  "#fit": "Shrink or grow the length to fit what's on the label", '#mode [data-v="single"]': "Print the label as shown, with the test values",
  '#mode [data-v="batch"]': "Print every row of the DATA & BATCH table", "#copies": "How many of each label", "#print": "Print now",
  '#zoom [data-v="fit"]': "Fit the label to the window", "#tpl-list": "Open a saved template", "#tpl-name": "Name to save this template under",
  "#tpl-save": "Save under the name on the left", "#media": "The roll this label is for",
};
for (const [q, t] of Object.entries(TIPS)) { const el = $(q); if (el && !el.title) el.title = t; }
$$("#k-length .kl, #k-length svg").forEach(e => e.setAttribute("title", TIPS["#k-length"]));
$$("#k-margin .kl, #k-margin svg").forEach(e => e.setAttribute("title", TIPS["#k-margin"]));

// ---------------------------------------------------------------- start
// ---------------------------------------------------------------- strips: labels end to end, cut by hand
const S = () => (tpl.strip = { on: false, per: 0, marks: "edge", ends: true, ...(tpl.strip || {}) });
$("#strip-ends").addEventListener("change", e => { S().ends = e.target.checked; changed(false); });
const setStrip = seg($("#strip"), "0", v => { S().on = v === "1"; stripUI(); changed(false); });
const setMarks = seg($("#strip-marks"), "edge", v => { S().marks = v; changed(false); });
$("#strip-per").addEventListener("input", e => { S().per = Math.max(0, parseInt(e.target.value, 10) || 0); stripUI(); changed(false); });
function stripUI() {
  const s = S(), fixed = MEDIA[mediaOf(tpl)]?.kind !== "continuous";
  setStrip(s.on && !fixed ? "1" : "0"); setMarks(s.marks);
  $("#strip").querySelector('[data-v="1"]').disabled = fixed;
  $("#strip-opts").hidden = !s.on || fixed;
  $("#strip-per").value = s.per;
  $("#strip-ends").checked = s.ends !== false;
  $("#strip-note").textContent = fixed ? "Die-cut labels are already separate." : s.on
    ? `Labels are printed end to end at exactly ${tpl.length_mm} mm each, ${s.per ? s.per + " per strip" : "the whole batch on one strip"}; ` +
      "the printer only adds its ~3 mm feed at the two ends of each strip. Cut on the marks."
    : "Each label is cut on its own; the printer adds about 3 mm of blank tape at both ends.";
}

// ---------------------------------------------------------------- media (rolls)
async function loadMedia() {
  const r = await api("api/media");
  MEDIA = Object.fromEntries(r.media.map(m => [m.id, m]));
  const groups = { continuous: "Continuous rolls (any length)", "die-cut": "Die-cut labels (fixed size)", round: "Round labels" };
  $("#b-media").innerHTML = r.media.filter(m => m.kind === "continuous").map(m => `<option value="${m.id}">${m.name}</option>`).join("");
  $("#b-media").value = loaded && MEDIA[loaded]?.kind === "continuous" ? loaded : "29";
  bleedForm();
  $("#media").innerHTML = Object.entries(groups).map(([k, g]) => `<optgroup label="${g}">${r.media.filter(m => m.kind === k)
    .map(m => `<option value="${m.id}">${m.name}</option>`).join("")}</optgroup>`).join("");
}
function mediaNote() {
  const id = mediaOf(tpl), md = MEDIA[id];
  if (!md) return;
  const canWide = md.kind === "continuous" && md.wide > md.printable;
  $("#wide-wrap").hidden = !canWide;
  $("#wide").checked = canWide && !!tpl.wide;
  $("#wide-label").textContent = `use the full width: ${(md.wide / DPMM).toFixed(1)} mm instead of ${(md.printable / DPMM).toFixed(1)} mm`;
  $("#media").value = id;
  const fixed = md.kind !== "continuous";
  $("#knobs").classList.toggle("fixed", fixed);
  $("#fit").disabled = fixed;
  $("#media-note").textContent = (fixed ? `Fixed size: ${(md.printable / DPMM).toFixed(1)} × ${(md.printable_len / DPMM).toFixed(1)} mm printable. ` :
    `${(md.printable / DPMM).toFixed(1)} mm printable across; any length. `) +
    (loaded ? (loaded === id ? "This roll is in the printer." : `The printer has ${MEDIA[loaded]?.name || "another roll"} in it.`) : "");
  $("#use-loaded").disabled = !loaded || loaded === id;
}
$("#wide").addEventListener("change", e => { tpl.wide = e.target.checked; changed(); });
function bleedForm() {
  const id = $("#b-media").value || mediaOf(tpl), md = MEDIA[id]; if (!md) return;
  $("#b-head").value = md.bleed[0]; $("#b-open").value = md.bleed[1];
  $("#b-width").textContent = `full width: ${md.wide} dots = ${(md.wide / DPMM).toFixed(1)} mm`;
}
$("#b-media").addEventListener("change", bleedForm);
$("#b-save").addEventListener("click", async () => {
  try {
    const r = await api("api/bleed", { media: $("#b-media").value, head: +$("#b-head").value, open: +$("#b-open").value });
    MEDIA = Object.fromEntries(r.media.map(m => [m.id, m])); bleedForm(); mediaNote(); changed(); say("Bleed saved.");
  } catch (e) { say(e.message, true); }
});
$("#media").addEventListener("change", e => { tpl.media = e.target.value; mediaNote(); stripUI(); changed(); printerStatus(); });
$("#use-loaded").addEventListener("click", () => { if (loaded) { tpl.media = loaded; mediaNote(); changed(); printerStatus(); } });

(async () => {
  try { await loadMedia(); } catch (e) { say(e.message, true); }
  await printerStatus();
  let draft = null;
  try { draft = JSON.parse(localStorage.getItem("qllabel-draft") || "null"); } catch (e) { /* none */ }
  if (draft && draft.elements) use(draft);
  else use({ ...blank(), elements: [
    { id: "e1", type: "datamatrix", x: 12, y: 12, module: 6, data: "{serial}", rotate: 0 },
    { id: "e2", type: "text", x: 108, y: 34, size: 32, font: "narrow-bold", data: "{serial}", rotate: 0 },
    { id: "e3", type: "code128", x: 12, y: 190, module: 2, height: 100, data: "{serial}", rotate: 0 },
  ], length_mm: 25 });
  try { await listTemplates(); } catch (e) { say(e.message, true); }
  printerStatus();
})();
