"use strict";
// Part-DB label station page. Scan (or photograph) a label, check what it filled in, save it to Part-DB.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const VENDOR_NAMES = { digikey: "DigiKey", mouser: "Mouser", lcsc: "LCSC", tme: "TME", element14: "Farnell / Newark" };
const KIND_NAMES = { ecia: "ECIA DATAMATRIX", lcsc: "LCSC QR", tme: "TME QR", partdb: "PART-DB LABEL", url: "LINK", gtin: "EAN / UPC", text: "TEXT" };
const PART_FIELDS = ["name", "mpn", "manufacturer", "description", "category", "footprint", "datasheet", "comment"];
const ALL_FIELDS = [...PART_FIELDS, "qty", "location", "lot_description", "lot_comment", "supplier", "spn", "supplier_url", "price", "currency"];

let ST = null;            // Part-DB connection status
let scan = null;          // the last scan: {raw, kind, vendor, fields, part, matches}
let chosen = null;        // the existing part being stocked, or null for a new part
let extra = {};           // values from the lookup that have no box: image, gtin, manufacturer_product_url
let lookupSeq = 0;

// ---- talking to the server ---------------------------------------------------------------
function say(text, err = false) {
  const m = $("#msg");
  if (!text) { m.hidden = true; return; }
  m.hidden = false; m.textContent = text; m.className = "msg" + (err ? " err" : "");
}
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  let j = null;
  try { j = await r.json(); } catch (e) { throw new Error(`The station didn't answer (${r.status}).`); }
  if (!r.ok || j.error) throw new Error(j.error || `Error ${r.status}`);
  return j;
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ---- tabs ----------------------------------------------------------------------------------
$$("#tabs button").forEach(b => b.onclick = () => {
  $$("#tabs button").forEach(x => x.classList.toggle("on", x === b));
  $$(".tab").forEach(t => t.hidden = t.id !== "tab-" + b.dataset.tab);
  if (b.dataset.tab === "recent") loadRecent();
  if (b.dataset.tab === "scan") focusScan();
  if (b.dataset.tab !== "scan") stopCam();
});

// ---- connection and lists --------------------------------------------------------------------
async function loadStatus() {
  try { ST = await api("/api/status"); } catch (e) { ST = { problem: e.message }; }
  const c = $("#conn");
  if (ST.problem) { c.className = "conn bad"; c.textContent = ST.has_token === false ? "NO API TOKEN" : "PART-DB NOT REACHED"; }
  else { c.className = "conn ok"; c.textContent = `PART-DB ${ST.version}  ·  ${ST.user}`; }
  $("#s-url").value = ST.url || "";
  const prov = (ST.providers || []).map(p => p.name).join(", ");
  $("#s-status").innerHTML = ST.problem ? `<b>Status</b><span>${esc(ST.problem)}</span>` :
    `<b>Connected as</b><span>${esc(ST.user)} (token "${esc(ST.token)}")</span><b>Part-DB</b><span>${esc(ST.version)}</span>` +
    `<b>Supplier lookups</b><span>${esc(prov || "none switched on")}</span>`;
  if (!ST.problem) loadLists();
  else if (ST.has_token === false) say("Add a Part-DB API token under SETTINGS to save parts. Scanning works without one.");
}
async function loadLists() {
  try {
    const L = await api("/api/lists");
    for (const [k, rows] of Object.entries(L))
      $("#dl-" + k).innerHTML = rows.map(r => `<option value="${esc(r.name)}">${r.path !== r.name ? esc(r.path) : ""}</option>`).join("");
    window.LISTS = L;
  } catch (e) { say(e.message, true); }
}
$("#s-save").onclick = async () => {
  try {
    await post("/api/config", { url: $("#s-url").value, token: $("#s-token").value });
    $("#s-token").value = "";
    await loadStatus();
    say(ST.problem ? ST.problem : "Connected to Part-DB.", !!ST.problem);
  } catch (e) { say(e.message, true); }
};

// ---- the scan box (a USB scanner is a keyboard) -------------------------------------------
const box = $("#scanbox");
function focusScan() { if (!$("#tab-scan").hidden) box.focus(); }
box.addEventListener("focus", () => $("#scanwrap").classList.add("ready"));
box.addEventListener("blur", () => $("#scanwrap").classList.remove("ready"));
box.addEventListener("keydown", e => {
  // the separators in a DataMatrix label, as a keyboard-wedge scanner types them
  const ctl = { "]": "\x1d", "BracketRight": "\x1d", "^": "\x1e", "6": "\x1e", "d": "\x04", "D": "\x04" };
  if (e.ctrlKey && !e.altKey && (ctl[e.key] || ctl[e.code])) {
    e.preventDefault();
    const ch = ctl[e.key] || ctl[e.code];
    const s = box.selectionStart, t = box.value;
    box.value = t.slice(0, s) + ch + t.slice(box.selectionEnd); box.selectionStart = box.selectionEnd = s + 1;
    return;
  }
  if (e.key === "Enter") { e.preventDefault(); const v = box.value; box.value = ""; if (v.trim()) runScan(v); }
});
// Scanning while nothing is focused (or a button is) still lands in the box.
document.addEventListener("keydown", e => {
  const a = document.activeElement;
  if ($("#tab-scan").hidden || e.ctrlKey || e.metaKey || e.altKey || e.key.length !== 1) return;
  if (a && (a.matches("input, textarea, select") || a.isContentEditable)) return;
  box.focus();
});
// Scanning into one of the part's boxes by mistake: a scanner types far faster than a person, so a
// quick burst of keys ending in Enter is taken back out of that box and read as a label.
const burst = { el: null, before: "", keys: [], last: 0 };
document.addEventListener("keydown", e => {
  const a = document.activeElement;
  if (a === box || !a || !a.matches("input:not([type=number]), textarea")) { burst.keys = []; return; }
  const now = performance.now();
  if (now - burst.last > 50 || burst.el !== a) { burst.el = a; burst.before = a.value; burst.keys = []; }
  burst.last = now;
  if (e.key === "Enter") {
    if (burst.keys.length >= 6) { e.preventDefault(); a.value = burst.before; runScan(burst.keys.join("")); }
    burst.keys = [];
  } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) burst.keys.push(e.key);
}, true);

// ---- camera and photos ----------------------------------------------------------------------
let stream = null, camTimer = null, camBusy = false;
$("#cam-start").onclick = async () => {
  if (stream) return stopCam();
  if (!navigator.mediaDevices?.getUserMedia) {
    $("#cam-note").hidden = false;
    $("#cam-note").textContent = "The browser only allows the camera on a page opened as http://localhost (on the Pi itself) or over https. Use a photo instead.";
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1920 }, height: { ideal: 1080 }, facingMode: "environment" } });
    $("#cam-video").srcObject = stream;
    $("#cam-view").hidden = false; $("#cam-snap").disabled = false; $("#cam-start").textContent = "STOP CAMERA";
    if ($("#cam-auto").checked) autoRead();
  } catch (e) { say("Couldn't start the camera: " + e.message, true); }
};
function stopCam() {
  clearTimeout(camTimer); camTimer = null;
  if (stream) stream.getTracks().forEach(t => t.stop());
  stream = null; $("#cam-view").hidden = true; $("#cam-snap").disabled = true; $("#cam-start").textContent = "START CAMERA";
}
function frame() {
  const v = $("#cam-video"), c = $("#cam-canvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);
  return new Promise(res => c.toBlob(res, "image/jpeg", 0.9));
}
async function readBlob(blob, quiet = false) {
  camBusy = true;
  try {
    const r = await api("/api/decode", { method: "POST", body: blob });
    if (!r.codes.length) { if (!quiet) say("No barcode found in that picture. Get closer, or light it better.", true); return false; }
    showCodes(r.codes);
    runScan(r.codes[0].text);
    return true;
  } catch (e) { say(e.message, true); return false; }
  finally { camBusy = false; }
}
$("#cam-snap").onclick = async () => { if (stream) readBlob(await frame()); };
$("#cam-auto").onchange = () => { if ($("#cam-auto").checked && stream) autoRead(); else clearTimeout(camTimer); };
async function autoRead() {
  clearTimeout(camTimer);
  if (!stream || !$("#cam-auto").checked) return;
  // one look about every second keeps the Pi's CPU low
  if (!camBusy && $("#cam-video").videoWidth && await readBlob(await frame(), true)) { $("#cam-auto").checked = false; return; }
  camTimer = setTimeout(autoRead, 1000);
}
function showCodes(codes) {
  const el = $("#codes");
  el.hidden = codes.length < 2;
  el.innerHTML = codes.map((c, i) => `<div class="pick${i ? "" : " cur"}" data-i="${i}"><span class="radio"></span>
    <span class="grow mono">${esc(c.text.slice(0, 80))}</span><span class="dim">${esc(c.format)}</span></div>`).join("");
  $$("#codes > div").forEach(d => d.onclick = () => {
    $$("#codes > div").forEach(x => x.classList.toggle("cur", x === d));
    runScan(codes[+d.dataset.i].text);
  });
}
const photo = $("#file-photo"), drop = $("#drop-photo");
photo.onchange = () => { if (photo.files[0]) gotPhoto(photo.files[0]); photo.value = ""; };
drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) gotPhoto(e.dataTransfer.files[0]); };
async function gotPhoto(f) {
  $("#photo-state").textContent = "Reading " + f.name + " …";
  const ok = await readBlob(f);
  $("#photo-state").textContent = ok ? "Read " + f.name : "Nothing read in " + f.name;
}

// ---- a scan ---------------------------------------------------------------------------------
async function runScan(raw) {
  $("#scanwrap").classList.add("busy"); say(""); $("#result").hidden = true;
  try {
    scan = await post("/api/scan", { raw });
  } catch (e) { say(e.message, true); return; }
  finally { $("#scanwrap").classList.remove("busy"); }
  showLabel();
  fillFromLabel();
  showMatches();
  if (scan.find_error) say(scan.find_error, true);
  if (scan.kind !== "partdb" && ST && !ST.problem) lookup();
  else $("#lookup-row").hidden = true;
  focusScan();
}
function showLabel() {
  $("#label-box").hidden = false;
  $("#label-kind").textContent = (KIND_NAMES[scan.kind] || scan.kind) + (scan.vendor ? "  ·  " + (VENDOR_NAMES[scan.vendor] || scan.vendor).toUpperCase() : "");
  $("#label-fields").innerHTML = scan.fields.map(([k, v]) => `<b>${esc(k)}</b><span class="mono">${esc(v)}</span>`).join("");
  $("#label-raw").textContent = scan.raw.replace(/\x1d/g, "<GS>").replace(/\x1e/g, "<RS>").replace(/\x04/g, "<EOT>");
}
function setF(k, v) { const el = $("#f-" + k); if (el) el.value = v ?? ""; }
function getF(k) { const el = $("#f-" + k); return el ? el.value.trim() : ""; }
function clearForm() {
  const loc = getF("location"), keep = $("#keep-loc").checked;
  ALL_FIELDS.forEach(k => setF(k, ""));
  if (keep) setF("location", loc);
  extra = {}; chosen = null;
  $("#pic").hidden = true; $("#params-box").hidden = true; $("#match-box").hidden = true; $("#lookup-row").hidden = true;
  setLots(null); lockPart(false); saveWhat();
}
function fillFromLabel() {
  clearForm();
  const p = scan.part;
  setF("name", p.mpn); setF("mpn", p.mpn); setF("manufacturer", p.manufacturer);
  setF("qty", p.qty ?? ""); setF("spn", p.spn); setF("supplier_url", p.url);
  if (scan.vendor) setF("supplier", VENDOR_NAMES[scan.vendor] || scan.vendor);
  setF("lot_description", [p.date_code && "Date code " + p.date_code, p.lot && "Lot " + p.lot, p.country && "Made in " + p.country].filter(Boolean).join(", "));
  setF("lot_comment", [p.po && "PO " + p.po, p.order && "Order " + p.order].filter(Boolean).join(", "));
  if (p.gtin) extra.gtin = p.gtin;
}
function showMatches() {
  const m = scan.matches || [];
  $("#match-box").hidden = !m.length;
  if (!m.length) return;
  const rows = m.map((p, i) => `<div class="pick" data-i="${i}"><span class="radio"></span><span class="grow">
      <a href="${esc(p.url)}" target="_blank">#${p.id} ${esc(p.name)}</a> <span class="dim">${esc(p.description)}</span></span>
      <span>${p.total ?? 0} in stock</span></div>`);
  rows.push(`<div class="pick" data-i="-1"><span class="radio"></span><span class="grow">It's a different part: make a new one</span></div>`);
  $("#matches").innerHTML = rows.join("");
  $$("#matches > div").forEach(d => d.onclick = e => { if (e.target.tagName !== "A") choose(+d.dataset.i); });
  choose(0);
}
function choose(i) {
  chosen = i >= 0 ? scan.matches[i] : null;
  $$("#matches > div").forEach(d => d.classList.toggle("cur", +d.dataset.i === i));
  if (chosen) {
    setF("name", chosen.name); setF("mpn", chosen.mpn || getF("mpn")); setF("description", chosen.description);
    const L = window.LISTS || {};
    const nm = (k, id) => ((L[k] || []).find(r => r.id === id) || {}).name || "";
    setF("category", nm("categories", chosen.category_id)); setF("manufacturer", nm("manufacturers", chosen.manufacturer_id) || getF("manufacturer"));
    setF("footprint", nm("footprints", chosen.footprint_id));
  }
  setLots(chosen); lockPart(!!chosen); saveWhat();
}
function lockPart(on) { PART_FIELDS.forEach(k => $("#f-" + k).disabled = on); }
function setLots(part) {
  const sel = $("#f-lot"), show = !!(part && part.lots.length);
  $("#lot-lab").hidden = !show; sel.hidden = !show;
  if (!show) { sel.innerHTML = ""; return; }
  const loc = getF("location").toLowerCase();
  sel.innerHTML = `<option value="">a new lot</option>` + part.lots.map(l =>
    `<option value="${l.id}">${esc(l.location || "no location")}: ${l.unknown ? "amount unknown" : l.amount}${l.description ? "  (" + esc(l.description) + ")" : ""}</option>`).join("");
  // the lot in the location typed, or with no location typed, the part's only lot
  const same = loc ? part.lots.find(l => l.location && l.location.toLowerCase() === loc) : part.lots.length === 1 ? part.lots[0] : null;
  sel.value = same ? same.id : "";
  lotChanged();
}
$("#f-lot").onchange = () => { lotChanged(); saveWhat(); };
function lotChanged() {
  const id = +$("#f-lot").value, lot = chosen && chosen.lots.find(l => l.id === id);
  $("#f-location").disabled = !!lot;
  if (lot) setF("location", lot.location);
}
$("#f-location").addEventListener("change", () => { if (chosen) setLots(chosen); });

// ---- supplier lookup ------------------------------------------------------------------------
async function lookup(provider = "", provider_id = "") {
  const seq = ++lookupSeq;
  $("#lookup-row").hidden = false;
  const who = VENDOR_NAMES[scan.vendor] || "the suppliers";
  $("#lookup-state").textContent = `Looking it up at ${who} …`;
  try {
    const r = await post("/api/lookup", { part: scan.part, vendor: scan.vendor, provider, provider_id });
    if (seq !== lookupSeq) return;
    if (r.candidates) showCandidates(r.candidates, r.suggest?.provider);
    applySuggest(r.suggest);
    $("#lookup-state").textContent = `Filled in from ${r.suggest.provider.key} (${r.suggest.provider.id}). Check it, then save.`;
  } catch (e) {
    if (seq !== lookupSeq) return;
    $("#lookup-state").textContent = "Lookup: " + e.message;
  }
}
function showCandidates(c, cur) {
  const sel = $("#candidates");
  sel.hidden = c.length < 2;
  sel.innerHTML = c.map(x => `<option value="${esc(x.provider + "\t" + x.id)}">${esc(x.provider)}: ${esc(x.mpn || x.id)}  ${esc(x.manufacturer || "")}  ${esc((x.description || "").slice(0, 50))}</option>`).join("");
  if (cur) sel.value = cur.key + "\t" + cur.id;
}
$("#candidates").onchange = () => { const [p, id] = $("#candidates").value.split("\t"); lookup(p, id); };
$("#lookup-again").onclick = () => scan && lookup();
function applySuggest(s) {
  if (!s) return;
  // the label wins for what it says itself; the lookup fills the rest
  const fill = (k, v) => { if (v && !getF(k)) setF(k, v); };
  if (!chosen) {
    fill("name", s.name); fill("mpn", s.mpn); fill("manufacturer", s.manufacturer); fill("description", s.description);
    fill("category", matchName("categories", s.category)); fill("footprint", matchName("footprints", s.footprint));
    fill("datasheet", s.datasheet);
    if (s.notes) fill("comment", s.notes.slice(0, 200));
    extra = { ...extra, image: s.image, gtin: extra.gtin || s.gtin, manufacturer_product_url: s.manufacturer_product_url };
  }
  fill("supplier", s.supplier); fill("spn", s.spn); fill("supplier_url", s.supplier_url || s.provider.url);
  if (s.price != null) { fill("price", s.price); fill("currency", s.currency); }
  if (s.image) { $("#pic").hidden = false; $("#pic-img").src = s.image; $("#pic-cap").textContent = s.status ? "Status: " + s.status : ""; }
  if (s.parameters?.length) {
    $("#params-box").hidden = false;
    $("#params").innerHTML = s.parameters.map(([k, v]) => `<b>${esc(k)}</b><span>${esc(v)}</span>`).join("");
  }
  saveWhat();
}
function matchName(kind, name) {
  // use an existing entry with the same name (any case) so we don't make near-duplicates
  if (!name) return "";
  const row = ((window.LISTS || {})[kind] || []).find(r => r.name.toLowerCase() === name.toLowerCase());
  return row ? row.name : name;
}

// ---- saving ---------------------------------------------------------------------------------
function saveWhat() {
  const q = getF("qty") || 0, lot = +$("#f-lot").value;
  $("#save-what").textContent = chosen
    ? `Adds ${q} to #${chosen.id} ${chosen.name}` + (lot ? " (existing lot)" : getF("location") ? " in " + getF("location") : "")
    : getF("name") ? `Makes a new part ${getF("name")} with ${q} in stock` : "";
}
ALL_FIELDS.forEach(k => $("#f-" + k).addEventListener("input", saveWhat));
$("#qty-plus").onclick = () => { setF("qty", (+getF("qty") || 0) + 1); saveWhat(); };
$("#qty-minus").onclick = () => { setF("qty", Math.max(0, (+getF("qty") || 0) - 1)); saveWhat(); };
$("#clear").onclick = () => { scan = null; clearForm(); $("#label-box").hidden = true; $("#codes").hidden = true; $("#result").hidden = true; say(""); focusScan(); };
$("#save").onclick = async () => {
  const f = Object.fromEntries(ALL_FIELDS.map(k => [k, getF(k)]));
  Object.assign(f, extra, { part_id: chosen ? chosen.id : null, lot_id: +$("#f-lot").value || null, raw: scan ? scan.raw : "" });
  $("#save").disabled = true;
  try {
    const r = await post("/api/save", f);
    $("#result").hidden = false;
    $("#result").innerHTML = `Saved: <a href="${esc(r.url)}" target="_blank">part #${r.part_id} in Part-DB</a>` +
      `<ul>${r.did.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` + r.warnings.map(w => `<div class="warn">${esc(w)}</div>`).join("");
    say("");
    if (r.did.some(x => x.startsWith("made the"))) loadLists();
    const keep = $("#result").innerHTML;
    scan = null; clearForm(); $("#label-box").hidden = true; $("#codes").hidden = true;
    $("#result").hidden = false; $("#result").innerHTML = keep;
  } catch (e) { say(e.message, true); }
  finally { $("#save").disabled = false; focusScan(); }
};

// ---- recent ---------------------------------------------------------------------------------
async function loadRecent() {
  try {
    const rows = await api("/api/recent");
    $("#recent").innerHTML = rows.map(r => `<tr><td class="no">${esc(r.time)}</td>
      <td><a href="${esc(r.url)}" target="_blank">#${r.part_id} ${esc(r.name)}</a></td><td>${esc(r.qty)}</td>
      <td>${esc(r.location)}</td><td>${esc(r.supplier)} ${esc(r.spn)}</td><td class="no">${esc((r.did || []).join("; "))}</td></tr>`).join("")
      || `<tr><td colspan="6" class="no">Nothing saved yet.</td></tr>`;
  } catch (e) { say(e.message, true); }
}

loadStatus();
focusScan();
