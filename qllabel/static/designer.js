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
  if (b.dataset.tab === "batch") { batchForm(); batchPreview(); }
  if (b.dataset.tab === "printer") printerStatus(true);
  if (b.dataset.tab === "design") layout();
});

// ---------------------------------------------------------------- preview
let inflight = false, again = false;
async function refresh() {
  if (inflight) { again = true; return; }
  inflight = true;
  try {
    last = await api("/api/preview", { template: tpl });
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
    d.className = "el" + (b.id === sel ? " sel" : "") + (b.bad ? " bad" : "");
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

// ---------------------------------------------------------------- dragging & keys
let drag = null;
$("#boxes").addEventListener("pointerdown", e => {
  const d = e.target.closest(".el"); if (!d) return;
  e.preventDefault();
  select(d.dataset.id);
  const el = tpl.elements.find(x => x.id === sel);
  drag = { x: e.clientX, y: e.clientY, ex: el.x, ey: el.y, el, node: $(`.el[data-id="${sel}"]`) };
  drag.node.setPointerCapture(e.pointerId);
});
document.addEventListener("pointermove", e => {
  if (!drag) return;
  drag.el.x = Math.round(drag.ex + (e.clientX - drag.x) / zoom);
  drag.el.y = Math.round(drag.ey + (e.clientY - drag.y) / zoom);
  drag.node.style.left = `${drag.el.x * zoom}px`; drag.node.style.top = `${drag.el.y * zoom}px`;
  $(".tag", drag.node).textContent = `${NAMES[drag.el.type]}  ${drag.el.x}, ${drag.el.y}`;
  refresh();
});
document.addEventListener("pointerup", () => { if (drag) { drag = null; changed(); drawProps(); } });
$("#stage").addEventListener("pointerdown", e => { if (!e.target.closest(".el")) select(null); });

document.addEventListener("keydown", e => {
  if (!sel || e.target.matches("input, textarea, select")) return;
  const el = tpl.elements.find(x => x.id === sel); if (!el) return;
  const step = e.shiftKey ? 10 : 1;
  const mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
  if (mv) { e.preventDefault(); el.x += mv[0]; el.y += mv[1]; changed(); drawProps(); return; }
  if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); remove(sel); }
  if (e.key.toLowerCase() === "d" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); duplicate(sel); }
});

function select(id) {
  sel = id;
  $$("#boxes .el").forEach(d => d.classList.toggle("sel", d.dataset.id === id));
  drawProps();
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
function remove(id) { tpl.elements = tpl.elements.filter(e => e.id !== id); sel = null; changed(); drawProps(); }
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
  const r = await api("/api/templates");
  const s = $("#tpl-list");
  s.innerHTML = `<option value="">(unsaved)</option>` + r.templates.map(t => `<option>${esc(t.name)}</option>`).join("");
  s.value = select || tpl.name || "";
}
function use(t) {
  tpl = { ...blank(), ...t };
  nextId = 1; sel = null;
  $("#tpl-name").value = tpl.name;
  tpl.margin = Math.max(35, tpl.margin ?? 35);   // the printer won't feed less than 35 dots (~3 mm) per page
  kLength.set(tpl.length_mm); kMargin.set(tpl.margin); setCut(tpl.cut); setAcross(tpl.across ? "1" : "0");
  tpl.media = mediaOf(tpl); delete tpl.tape;
  mediaNote(); stripUI();
  $("#flip").checked = !!tpl.flip;
  $("#fields").dataset.key = "";
  tpl.batch = { ...BATCH, ...(tpl.batch || {}) };
  drawProps(); changed(); batchSummary();
}
$("#tpl-list").addEventListener("change", async e => {
  if (!e.target.value) return;
  try { use(await api("/api/template?name=" + encodeURIComponent(e.target.value))); } catch (x) { say(x.message, true); }
});
$("#tpl-new").addEventListener("click", () => { use(blank()); $("#tpl-list").value = ""; });
$("#tpl-save").addEventListener("click", async () => {
  tpl.name = $("#tpl-name").value.trim();
  if (!tpl.name) { say("Give the template a name first.", true); $("#tpl-name").focus(); return; }
  try { await api("/api/save", { template: tpl }); await listTemplates(tpl.name); say(`Saved “${tpl.name}”.`); saveDraft(); }
  catch (e) { say(e.message, true); }
});
$("#tpl-del").addEventListener("click", async () => {
  const n = $("#tpl-list").value;
  if (!n || !confirm(`Delete the template “${n}”?`)) return;
  try { await api("/api/delete", { name: n }); await listTemplates(""); say(`Deleted “${n}”.`); } catch (e) { say(e.message, true); }
});
function saveDraft() { try { localStorage.setItem("qllabel-draft", JSON.stringify(tpl)); } catch (e) { /* fine */ } }

// ---------------------------------------------------------------- printing
async function doPrint(rows, copies, btn) {
  btn.disabled = true;
  const old = btn.textContent; btn.textContent = "PRINTING…";
  try {
    const r = await api("/api/print", { template: tpl, rows, copies });
    const what = `${r.labels} label(s)` + (r.strips ? ` on ${r.strips} strip(s)` : "");
    say(r.dry_run ? `Dry run: ${what} written to ${r.dry_run}` : `Printed ${what}.`);
  } catch (e) { say(e.message, true); }
  btn.disabled = false; btn.textContent = old;
  printerStatus(true);
}
$("#print").addEventListener("click", e => B().on ? printBatch(e.target, +$("#copies").value || 1) : doPrint([{}], +$("#copies").value || 1, e.target));

// ---------------------------------------------------------------- batch
const BATCH = { on: false, source: "range", field: "serial", prefix: "PTC-", suffix: "", start: 1, count: 10, step: 1,
  digits: 5, advance: true, csv: "", map: {}, first_row: 1, last_row: 0, list: "" };
const B = () => (tpl.batch = { ...BATCH, ...(tpl.batch || {}) });
const setMode = seg($("#mode"), "single", v => { B().on = v === "batch"; changed(false); batchSummary(); });
const setSource = seg($("#b-source"), "range", v => { B().source = v; batchForm(); batchPreview(); changed(false); });

function batchForm() {
  const b = B(), names = (last && last.fields) || [];
  setSource(b.source);
  $$(".bsrc").forEach(d => { d.hidden = d.id !== "b-" + b.source; });
  $$("#tab-batch [data-b]").forEach(i => {
    const v = b[i.dataset.b];
    if (i.type === "checkbox") i.checked = !!v; else if (i.tagName !== "SELECT") i.value = v ?? "";
  });
  $$(".b-field").forEach(s => {
    s.innerHTML = (names.length ? names : [b.field]).map(n => `<option${n === b.field ? " selected" : ""}>${esc(n)}</option>`).join("");
    if (!names.includes(b.field) && names.length) { b.field = names[0]; s.value = b.field; }
  });
  $("#b-listhint").textContent = names.length > 1
    ? `One label per line: ${names.map(n => "{" + n + "}").join(", ")}, separated by a comma or a tab.`
    : names.length ? `One {${names[0]}} per line.` : "This template has no {fields}; each line prints the same label.";
  if (b.source === "csv") csvForm();
}
$$("#tab-batch [data-b]").forEach(i => i.addEventListener("input", () => {
  const b = B(), k = i.dataset.b;
  b[k] = i.type === "checkbox" ? i.checked : i.type === "number" ? (parseInt(i.value, 10) || 0) : i.value;
  changed(false); batchPreviewSoon();
}));

async function csvForm() {
  const b = B();
  try {
    const r = await api("/api/csvs");
    $("#b-csvlist").innerHTML = `<option value="">(pick a CSV)</option>` + r.csvs.map(n => `<option${n === b.csv ? " selected" : ""}>${esc(n)}</option>`).join("");
  } catch (e) { say(e.message, true); }
  if (!b.csv) { $("#b-map").innerHTML = ""; $("#b-head").innerHTML = ""; return; }
  let info;
  try { info = await api("/api/csv?name=" + encodeURIComponent(b.csv)); } catch (e) { say(e.message, true); return; }
  const names = (last && last.fields) || [];
  $("#b-map").innerHTML = names.map(n => {
    const cur = b.map[n] || info.columns.find(c => c.toLowerCase() === n.toLowerCase()) || "";
    return `<span class="lab">{${esc(n)}}</span><select data-map="${esc(n)}"><option value="">(choose)</option>${info.columns.map(c => `<option${c === cur ? " selected" : ""}>${esc(c)}</option>`).join("")}</select>`;
  }).join("") || `<span class="dim" style="grid-column:1/3">The template has no {fields} to fill.</span>`;
  $$("#b-map select").forEach(s => s.addEventListener("change", () => { b.map[s.dataset.map] = s.value; changed(false); batchPreview(); }));
  $("#b-head").innerHTML = `<table><tr>${info.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr>` +
    info.head.map(r => `<tr>${info.columns.map(c => `<td>${esc(r[c] ?? "")}</td>`).join("")}</tr>`).join("") + `</table>` +
    `<p class="dim">${info.count} rows in ${esc(info.csv)}${info.count > 5 ? " (first 5 shown)" : ""}</p>`;
}
$("#b-csvlist").addEventListener("change", e => { B().csv = e.target.value; B().map = {}; changed(false); csvForm(); batchPreview(); });
$("#b-csvfile").addEventListener("change", async e => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const r = await api("/api/upload_csv", { name: f.name.replace(/[^\w .-]/g, "_"), text: await f.text() });
    B().csv = r.csv; B().map = {}; changed(false); await csvForm(); batchPreview();
    say(`Loaded ${r.csv}: ${r.count} rows, columns ${r.columns.join(", ")}.`);
  } catch (x) { say(x.message, true); }
  e.target.value = "";
});

let bpTimer;
function batchPreviewSoon() { clearTimeout(bpTimer); bpTimer = setTimeout(batchPreview, 300); }
async function batchPreview() {
  if ($("#tab-batch").hidden) return batchSummary();
  try {
    const info = await api("/api/batch", { template: tpl });
    $("#b-count").textContent = `${info.count} label${info.count === 1 ? "" : "s"}`;
    for (const [id, row] of [["#b-first", info.first[0]], ["#b-last", info.last]]) {
      const img = $(id);
      if (!row) { img.removeAttribute("src"); continue; }
      const r = await api("/api/preview", { template: tpl, values: row });
      img.src = "data:image/png;base64," + r.png; img.style.width = `${r.w}px`;
    }
  } catch (e) { $("#b-count").textContent = e.message; }
  batchSummary();
}
async function batchSummary() {
  const b = B();
  setMode(b.on ? "batch" : "single");
  if (!b.on) { $("#batch-sum").textContent = "Prints the label as shown, with the test values above."; return; }
  try {
    const info = await api("/api/batch", { template: tpl });
    const show = r => r ? Object.values(r).join(" / ") : "";
    $("#batch-sum").textContent = `${info.count} labels from ${{ range: "numbers", csv: b.csv || "a CSV", list: "the typed list" }[b.source]}: ` +
      `${show(info.first[0])}${info.count > 1 ? " … " + show(info.last) : ""}. Set it up on the BATCH PRINT tab.`;
  } catch (e) { $("#batch-sum").textContent = e.message; }
}

async function printBatch(btn, copies) {
  let info;
  try { info = await api("/api/batch", { template: tpl }); } catch (e) { return say(e.message, true); }
  if (info.count * copies > 20 && !confirm(`Print ${info.count * copies} labels?`)) return;
  btn.disabled = true;
  const old = btn.textContent; btn.textContent = "PRINTING…";
  try {
    const r = await api("/api/print_batch", { template: tpl, copies });
    const what = `${r.labels} labels` + (r.strips ? ` on ${r.strips} strip(s)` : "");
    let m = r.dry_run ? `Dry run: ${what} written to ${r.dry_run}.` : `Printed ${what}.`;
    if (r.next_start !== undefined) {
      B().start = r.next_start; changed(false); batchForm();
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
  const r = await api("/api/image", { name, png: pngUrl });
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
    const r = await api("/api/images");
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
    const r = await api("/api/calibrate", { lengths, margin: +$("#c-margin").value, cut: $("#c-cut .on").dataset.v, media: MEDIA[mediaOf(tpl)]?.kind === "continuous" ? mediaOf(tpl) : null, flip: !!tpl.flip });
    say(r.dry_run ? `Dry run written to ${r.dry_run}` : `Printed ${r.pages} test labels.`);
  } catch (x) { say(x.message, true); }
  btn.disabled = false;
});

// ---------------------------------------------------------------- printer status
async function printerStatus(show = false) {
  let s;
  try { s = await api("/api/status"); } catch (e) { s = { ok: false, error: e.message }; }
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

// ---------------------------------------------------------------- start
// ---------------------------------------------------------------- strips: labels end to end, cut by hand
const S = () => (tpl.strip = { on: false, per: 0, marks: "edge", ...(tpl.strip || {}) });
const setStrip = seg($("#strip"), "0", v => { S().on = v === "1"; stripUI(); changed(false); });
const setMarks = seg($("#strip-marks"), "edge", v => { S().marks = v; changed(false); });
$("#strip-per").addEventListener("input", e => { S().per = Math.max(0, parseInt(e.target.value, 10) || 0); stripUI(); changed(false); });
function stripUI() {
  const s = S(), fixed = MEDIA[mediaOf(tpl)]?.kind !== "continuous";
  setStrip(s.on && !fixed ? "1" : "0"); setMarks(s.marks);
  $("#strip").querySelector('[data-v="1"]').disabled = fixed;
  $("#strip-opts").hidden = !s.on || fixed;
  $("#strip-per").value = s.per;
  $("#strip-note").textContent = fixed ? "Die-cut labels are already separate." : s.on
    ? `Labels are printed end to end at exactly ${tpl.length_mm} mm each, ${s.per ? s.per + " per strip" : "the whole batch on one strip"}; ` +
      "the printer only adds its ~3 mm feed at the two ends of each strip. Cut on the marks."
    : "Each label is cut on its own; the printer adds about 3 mm of blank tape at both ends.";
}

// ---------------------------------------------------------------- media (rolls)
async function loadMedia() {
  const r = await api("/api/media");
  MEDIA = Object.fromEntries(r.media.map(m => [m.id, m]));
  const groups = { continuous: "Continuous rolls (any length)", "die-cut": "Die-cut labels (fixed size)", round: "Round labels" };
  $("#media").innerHTML = Object.entries(groups).map(([k, g]) => `<optgroup label="${g}">${r.media.filter(m => m.kind === k)
    .map(m => `<option value="${m.id}">${m.name}</option>`).join("")}</optgroup>`).join("");
}
function mediaNote() {
  const id = mediaOf(tpl), md = MEDIA[id];
  if (!md) return;
  $("#media").value = id;
  const fixed = md.kind !== "continuous";
  $("#knobs").classList.toggle("fixed", fixed);
  $("#fit").disabled = fixed;
  $("#media-note").textContent = (fixed ? `Fixed size: ${(md.printable / DPMM).toFixed(1)} × ${(md.printable_len / DPMM).toFixed(1)} mm printable. ` :
    `${(md.printable / DPMM).toFixed(1)} mm printable across; any length. `) +
    (loaded ? (loaded === id ? "This roll is in the printer." : `The printer has ${MEDIA[loaded]?.name || "another roll"} in it.`) : "");
  $("#use-loaded").disabled = !loaded || loaded === id;
}
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
