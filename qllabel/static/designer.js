// QL label designer. The Pi draws every label (POST /api/preview); this page only arranges elements
// and shows the returned 300 dpi bitmap, so what you see is exactly what the printer gets.
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const DPMM = 300 / 25.4;
const TAPE_TOTAL = { 12: 142, 29: 342, 38: 449, 50: 590, 54: 636, 62: 732 };   // whole tape width in dots
const TAPE_PRINT = { 12: 106, 29: 306, 38: 413, 50: 554, 54: 590, 62: 696 };
const NAMES = { text: "TEXT", datamatrix: "DATAMATRIX", code128: "CODE 128", qr: "QR", microqr: "MICRO QR",
  code39: "CODE 39", box: "BOX", line: "LINE" };
const LINEAR = ["code128", "code39"];
const CODES = ["datamatrix", "code128", "qr", "microqr", "code39"];
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
  return { name: "", tape: 29, length_mm: 20, margin: 35, cut: "each", cut_every: 1, flip: false,
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

const kLength = knob($("#k-length"), { id: "len", label: "LENGTH", min: 2, max: 150, step: 0.5, value: 20, log: true,
  fmt: v => `${v.toFixed(1)} mm`, onChange: v => { tpl.length_mm = v; changed(); } });
const kMargin = knob($("#k-margin"), { id: "mar", label: "MARGIN", min: 0, max: 100, step: 1, value: 35,
  fmt: v => `${v} dots`, onChange: v => { tpl.margin = v; changed(false); } });

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
seg($("#zoom"), "fit", v => { zoomMode = v; layout(); });
const setCCut = seg($("#c-cut"), "each", () => {});

// ---------------------------------------------------------------- tabs
$("#tabs").addEventListener("click", e => {
  const b = e.target.closest("button[data-tab]"); if (!b) return;
  $$("#tabs button[data-tab]").forEach(x => x.classList.toggle("on", x === b));
  $$("section.tab").forEach(s => { s.hidden = s.id !== "tab-" + b.dataset.tab; });
  if (b.dataset.tab === "batch") batchInfo();
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
  const w = last.w, h = last.h, total = TAPE_TOTAL[tpl.tape] || h + 36, edge = (total - h) / 2, m = tpl.margin;
  if (zoomMode === "fit") {
    const avail = $("#stage").clientWidth - 60;
    zoom = Math.max(0.5, Math.min(6, avail / (w + 2 * m), 440 / total));
  } else zoom = +zoomMode;
  const tape = $("#tape");
  tape.style.padding = `${edge * zoom}px 0`;
  tape.style.setProperty("--edge", `${edge * zoom}px`);
  $("#feed-l").style.width = $("#feed-r").style.width = `${m * zoom}px`;
  const lab = $("#label");
  lab.style.width = `${w * zoom}px`; lab.style.height = `${h * zoom}px`;
  const img = $("#bitmap");
  img.style.width = `${w * zoom}px`; img.style.height = `${h * zoom}px`;
  $("#gridlay").classList.toggle("on", $("#grid").checked);
  $("#gridlay").style.setProperty("--mm", `${DPMM * zoom}px`);
  $("#dims").textContent = `${last.w_mm.toFixed(1)} × ${last.h_mm.toFixed(1)} mm printable  ·  ${w} × ${h} dots  ·  ` +
    `piece ≈ ${((w + 2 * m) / DPMM).toFixed(1)} mm with margin`;
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
  datamatrix: { data: "{serial}", module: 5 },
  qr: { data: "{serial}", module: 4 },
  microqr: { data: "{serial}", module: 5 },
  code128: { data: "{serial}", module: 2, height: 80 },
  code39: { data: "{serial}", module: 2, height: 80 },
  box: { w: 120, h: 80, stroke: 3 },
  line: { w: 150, stroke: 3 },
};
function uid() { let id; do { id = "e" + nextId++; } while (tpl.elements.some(e => e.id === id)); return id; }

$("#add").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  const [x, y] = freeSpot(60, 60);
  const el = { id: uid(), type: b.dataset.t, x, y, rotate: 0, ...structuredClone(DEFAULTS[b.dataset.t]) };
  tpl.elements.push(el);
  sel = el.id; changed(); drawProps();
});
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
    h += num("module", "MODULE", "dots", 1);
    if (LINEAR.includes(el.type)) h += num("height", "HEIGHT", "dots", 1);
  }
  if (el.type === "box") h += num("w", "WIDTH", "dots", 1) + num("h", "HEIGHT", "dots", 1) + num("stroke", "STROKE", "dots", 1);
  if (el.type === "line") h += num("w", "LENGTH", "dots", 1) + num("stroke", "THICK", "dots", 1);
  h += `<span class="lab">ROTATE</span><div class="seg" data-seg="rotate">${[0, 90, 180, 270].map(a => `<button data-v="${a}" class="${(+el.rotate || 0) === a ? "on" : ""}">${a}°</button>`).join("")}</div>`;
  h += `<span class="lab">STYLE</span><span>`;
  if (el.type === "box") h += `<label class="check"><input type="checkbox" data-k="filled"${el.filled ? " checked" : ""}> filled</label> `;
  h += `<label class="check"><input type="checkbox" data-k="invert"${el.invert ? " checked" : ""}> white on black</label></span>`;
  h += `</div><div class="props-actions">
    <button data-a="ch">CENTRE ↔</button><button data-a="cv">CENTRE ↕</button>
    <button data-a="front">TO FRONT</button><button data-a="back">TO BACK</button>
    <button data-a="dup">DUPLICATE</button><button data-a="del">DELETE</button></div>`;
  host.innerHTML = h;

  $$("[data-k]", host).forEach(inp => inp.addEventListener("input", () => {
    const k = inp.dataset.k;
    el[k] = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? (parseInt(inp.value, 10) || 0) : inp.value;
    const u = $(`[data-u="${k}"]`, host); if (u && inp.type === "number") u.textContent = mm(el[k]);
    changed();
  }));
  $$("[data-seg]", host).forEach(s => s.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    $$("button", s).forEach(x => x.classList.toggle("on", x === b));
    el[s.dataset.seg] = s.dataset.seg === "rotate" ? +b.dataset.v : b.dataset.v;
    changed();
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
  const lo = Math.max(0, Math.min(...last.boxes.map(b => b.x)));
  const hi = Math.max(...last.boxes.map(b => b.x + b.w));
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
  kLength.set(tpl.length_mm); kMargin.set(tpl.margin); setCut(tpl.cut);
  $("#flip").checked = !!tpl.flip;
  $("#fields").dataset.key = "";
  drawProps(); changed();
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
    say(r.dry_run ? `Dry run: ${r.pages} label(s) written to ${r.dry_run}` : `Printed ${r.pages} label(s).`);
  } catch (e) { say(e.message, true); }
  btn.disabled = false; btn.textContent = old;
  printerStatus(true);
}
$("#print").addEventListener("click", e => doPrint([{}], +$("#copies").value || 1, e.target));

function batchRows() {
  const names = (last && last.fields) || [];
  return $("#batch").value.split("\n").map(l => l.trim()).filter(Boolean).map(l => {
    const parts = l.includes("\t") ? l.split("\t") : names.length > 1 ? l.split(",") : [l];
    return Object.fromEntries(names.map((n, i) => [n, (parts[i] ?? "").trim()]));
  });
}
function batchInfo() {
  const names = (last && last.fields) || [];
  $("#batch-hint").textContent = names.length
    ? `This template uses ${names.map(n => "{" + n + "}").join(", ")}. ` + (names.length > 1 ? "Separate them with a comma or a tab, in that order." : "Put one value on each line.")
    : "This template has no {fields}: every line prints the same label.";
  $("#r-field").innerHTML = names.map(n => `<option>${esc(n)}</option>`).join("");
  $("#batch-count").textContent = `${batchRows().length} labels`;
  rangeSample();
  thumb();
}
async function thumb() {
  const rows = batchRows();
  try {
    const r = await api("/api/preview", { template: tpl, values: rows[0] || {} });
    const img = $("#batch-thumb");
    img.src = "data:image/png;base64," + r.png; img.style.width = `${r.w}px`;
  } catch (e) { /* the design tab shows errors */ }
}
$("#batch").addEventListener("input", () => { $("#batch-count").textContent = `${batchRows().length} labels`; });
$("#batch").addEventListener("change", thumb);
function rangeVals() {
  const a = +$("#r-from").value, b = +$("#r-to").value, d = +$("#r-digits").value || 1;
  const out = [];
  for (let i = a; a <= b ? i <= b : i >= b; i += a <= b ? 1 : -1) {
    out.push($("#r-prefix").value + String(i).padStart(d, "0") + $("#r-suffix").value);
    if (out.length >= 500) break;
  }
  return out;
}
function rangeSample() { const v = rangeVals(); $("#r-sample").textContent = v.length ? `${v[0]} … ${v[v.length - 1]}  (${v.length})` : ""; }
$$("#r-prefix, #r-from, #r-to, #r-digits, #r-suffix").forEach(i => i.addEventListener("input", rangeSample));
$("#r-fill").addEventListener("click", () => {
  const names = (last && last.fields) || [];
  const f = $("#r-field").value, i = names.indexOf(f);
  $("#batch").value = rangeVals().map(v => names.length > 1 ? names.map((n, j) => j === i ? v : (tpl.fields[n] ?? "")).join("\t") : v).join("\n");
  batchInfo();
});
$("#batch-print").addEventListener("click", e => {
  const rows = batchRows();
  if (!rows.length) { say("The list is empty.", true); return; }
  if (rows.length > 20 && !confirm(`Print ${rows.length} labels?`)) return;
  doPrint(rows, 1, e.target);
});

$("#c-print").addEventListener("click", async e => {
  const btn = e.target; btn.disabled = true;
  try {
    const lengths = $("#c-lengths").value.split(/[,\s]+/).filter(Boolean).map(Number);
    const r = await api("/api/calibrate", { lengths, margin: +$("#c-margin").value, cut: $("#c-cut .on").dataset.v, tape: tpl.tape, flip: !!tpl.flip });
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
    s.errors && s.errors.length ? s.errors.join(", ").toUpperCase() : `${s.media_width} mm ${s.media_type}`.toUpperCase() + (s.dry_run ? " · DRY RUN" : "");
  c.title = s.error || "";
  if (s.media_width && TAPE_PRINT[s.media_width] && !s.dry_run && s.media_width !== tpl.tape)
    c.textContent += ` · LABEL IS ${tpl.tape} mm`;
  if (show) {
    const rows = s.error ? [["Status", s.error]] : [["Status", s.busy ? "printing" : s.errors.length ? s.errors.join(", ") : "ready"],
      ["Tape", `${s.media_width} mm ${s.media_type}`], ["Fixed length", s.media_length ? `${s.media_length} mm` : "none (continuous)"],
      ["Device", s.device], ["Mode", s.dry_run ? "dry run (nothing is sent)" : "live"]];
    $("#pstat").innerHTML = rows.map(([k, v]) => `<b>${k}</b><span>${esc(v)}</span>`).join("");
  }
}
$("#p-refresh").addEventListener("click", () => printerStatus(true));
setInterval(() => { if (!document.hidden) printerStatus(); }, 6000);

// ---------------------------------------------------------------- start
(async () => {
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
