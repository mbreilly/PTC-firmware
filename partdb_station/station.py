"""What the page asks for: read a label, look the part up, and put it (or more of it) into Part-DB."""

import json
import threading
import time
from pathlib import Path

from . import labels
from .partdb import PartDB, PartDBError, iri_id

# label vendor → Part-DB info provider key and the supplier name we file it under
VENDORS = {"digikey": ("digikey", "DigiKey"), "mouser": ("mouser", "Mouser"), "lcsc": ("lcsc", "LCSC"),
           "tme": ("tme", "TME"), "element14": ("element14", "Farnell / Newark")}
LISTS = ("categories", "footprints", "manufacturers", "suppliers", "storage_locations")


class Station:
    def __init__(self, data_dir: Path, config_path: Path):
        self.data = data_dir
        self.data.mkdir(parents=True, exist_ok=True)
        self.config_path = config_path
        self.cfg = self._load_cfg()
        self.lock = threading.Lock()

    # ---- settings (Part-DB address and API token) ----
    def _load_cfg(self):
        try:
            return json.loads(self.config_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def set_config(self, url=None, token=None):
        if url is not None:
            self.cfg["url"] = url.strip().rstrip("/")
        if token is not None and token.strip():
            self.cfg["token"] = token.strip()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.touch(mode=0o600, exist_ok=True)
        self.config_path.chmod(0o600)
        self.config_path.write_text(json.dumps(self.cfg, indent=2))

    @property
    def db(self):
        return PartDB(self.cfg.get("url", ""), self.cfg.get("token", ""))

    def status(self):
        st = {"url": self.cfg.get("url", ""), "has_token": bool(self.cfg.get("token"))}
        if not st["has_token"]:
            st["problem"] = "No API token yet."
            return st
        try:
            st.update(self.db.whoami())
            st["providers"] = self.db.providers()
        except PartDBError as e:
            st["problem"] = str(e)
        return st

    def lists(self):
        db = self.db
        return {k: db.names(k) for k in LISTS}

    # ---- a scan ----
    def scan(self, raw: str):
        r = labels.parse(raw)
        r["raw"] = raw
        r["matches"] = []
        if r["partdb"]:
            ref = r["partdb"]
            if ref["type"] == "part":
                r["matches"] = [self.db.part(ref["id"])]
            elif ref["type"] == "lot":
                pid = iri_id(self.db.lot(ref["id"]).get("part"))
                r["matches"] = [self.db.part(pid)] if pid else []
            return r
        p = r["part"]
        if self.cfg.get("token"):
            try:
                r["matches"] = self.db.find(p["mpn"], p["spn"], p["gtin"])
            except PartDBError as e:
                r["find_error"] = str(e)
        return r

    def lookup(self, part: dict, vendor: str, provider: str = "", provider_id: str = ""):
        """Ask Part-DB's distributor lookups about the part. Returns suggested field values."""
        db = self.db
        if not provider_id:
            active = {p["key"]: p for p in db.providers()}
            if not active:
                return {"error": "Part-DB has no supplier lookups switched on (Tools → Info providers)."}
            key = VENDORS.get(vendor, ("",))[0]
            if key in active:
                keys, keyword = [key], part.get("spn") or part.get("mpn")
            else:
                keys = [k for k, p in active.items() if not p["slow"]]
                keyword = part.get("mpn") or part.get("spn") or part.get("gtin")
            if not keyword:
                return {"error": "The label has no part number to look up."}
            results = db.search(keyword, keys)
            if not results and key in active and part.get("mpn") and keyword != part["mpn"]:
                results = db.search(part["mpn"], keys)
            if not results:
                return {"error": f"No supplier lookup found {keyword}.", "candidates": []}
            want = {(part.get("mpn") or "").lower(), (part.get("spn") or "").lower()} - {""}
            best = next((x for x in results if (x.get("mpn") or "").lower() in want
                         or (x.get("provider_id") or "").lower() in want), results[0])
            provider, provider_id = best["provider_key"], best["provider_id"]
            candidates = [{"provider": x["provider_key"], "id": x["provider_id"], "mpn": x.get("mpn"),
                           "manufacturer": x.get("manufacturer"), "description": x.get("description")}
                          for x in results[:8]]
        else:
            candidates = None
        d = db.details(provider, provider_id)
        sug = {
            "name": d.get("mpn") or d.get("name") or "", "mpn": d.get("mpn") or "", "description": d.get("description") or "",
            "manufacturer": d.get("manufacturer") or "", "category": _last(d.get("category")), "footprint": d.get("footprint") or "",
            "manufacturer_product_url": d.get("manufacturer_product_url") or "", "gtin": d.get("gtin") or "",
            "datasheet": next((f["url"] for f in d.get("datasheets") or [] if f.get("url")), ""),
            "image": d.get("preview_image_url") or next((f["url"] for f in d.get("images") or [] if f.get("url")), ""),
            "status": d.get("manufacturing_status") or "", "notes": d.get("notes") or "",
            "provider": {"key": provider, "id": provider_id, "url": d.get("provider_url") or ""},
            "parameters": [[x.get("name"), _param(x)] for x in (d.get("parameters") or [])[:30]],
        }
        vi = d.get("vendor_infos") or []
        mine = VENDORS.get(vendor, ("", ""))[1].lower()
        v = next((x for x in vi if mine and mine.split(" ")[0] in (x.get("distributor_name") or "").lower()), vi[0] if vi else None)
        if v:
            sug["supplier"] = v.get("distributor_name") or ""
            sug["spn"] = v.get("order_number") or ""
            sug["supplier_url"] = v.get("product_url") or ""
            prices = v.get("prices") or []
            if prices:
                sug["price"] = prices[0].get("price")
                sug["currency"] = prices[0].get("currency_iso_code") or ""
                sug["prices"] = [[p.get("minimum_discount_amount"), p.get("price"), p.get("currency_iso_code")] for p in prices]
        return {"suggest": sug, "candidates": candidates}

    # ---- saving ----
    def save(self, f: dict):
        db = self.db
        did, warn = [], []
        with self.lock:
            qty = float(f.get("qty") or 0)
            pid = f.get("part_id")
            if not pid:
                if not (f.get("name") or "").strip():
                    raise PartDBError("The part needs a name.")
                if not (f.get("category") or "").strip():
                    raise PartDBError("Pick or type a category; Part-DB needs one for every part.")
                body = {"name": f["name"].strip(), "description": f.get("description", ""),
                        "manufacturer_product_number": f.get("mpn", ""), "comment": f.get("comment", ""),
                        "manufacturer_product_url": f.get("manufacturer_product_url", ""), "tags": f.get("tags", "")}
                if f.get("gtin"):
                    body["gtin"] = f["gtin"]
                for field, kind in (("category", "categories"), ("manufacturer", "manufacturers"), ("footprint", "footprints")):
                    iri, made = db.resolve(kind, f.get(field))
                    if iri:
                        body[field] = iri
                    if made:
                        did.append(f"made the {field} \"{f[field]}\"")
                pid = db.post("/api/parts", body)["id"]
                did.append(f"made part #{pid} {body['name']}")
                for label, url in (("Datasheet", f.get("datasheet")), ("Picture", f.get("image"))):
                    if url:
                        try:
                            self._attach(db, pid, label, url)
                            did.append(f"linked the {label.lower()}")
                        except PartDBError as e:
                            warn.append(f"Couldn't link the {label.lower()}: {e}")
            part_iri = f"/api/parts/{pid}"

            # stock
            if qty or f.get("location"):
                lot_id = f.get("lot_id")
                if lot_id:
                    lot = db.lot(lot_id)
                    db.patch(f"/api/part_lots/{lot_id}", {"amount": float(lot.get("amount") or 0) + qty})
                    did.append(f"added {_n(qty)} to lot #{lot_id} (now {_n(float(lot.get('amount') or 0) + qty)})")
                else:
                    body = {"part": part_iri, "amount": qty, "description": f.get("lot_description", ""),
                            "comment": f.get("lot_comment", "")}
                    loc, made = db.resolve("storage_locations", f.get("location"))
                    if loc:
                        body["storage_location"] = loc
                    if made:
                        did.append(f"made the storage location \"{f['location']}\"")
                    lot = db.post("/api/part_lots", body)
                    did.append(f"put {_n(qty)} in {f.get('location') or 'a new lot'} (lot #{lot['id']})")

            # where it was bought
            spn = (f.get("spn") or "").strip()
            if spn and f.get("supplier"):
                have = [od for od in db.get("/api/orderdetails", supplierpartnr=spn) or [] if iri_id(od.get("part")) == pid]
                if not have:
                    sup, made = db.resolve("suppliers", f["supplier"])
                    if made:
                        did.append(f"made the supplier \"{f['supplier']}\"")
                    od = db.post("/api/orderdetails", {"part": part_iri, "supplier": sup, "supplierpartnr": spn,
                                                        "supplier_product_url": f.get("supplier_url", "")})
                    did.append(f"noted {f['supplier']} part no. {spn}")
                    if f.get("price"):
                        try:
                            body = {"orderdetail": f"/api/orderdetails/{od['id']}", "price": str(f["price"]),
                                    "min_discount_quantity": 1, "price_related_quantity": 1}
                            cur = self._currency(db, f.get("currency"))
                            if cur:
                                body["currency"] = cur
                            db.post("/api/pricedetails", body)
                            did.append(f"noted the price {f['price']} {f.get('currency') or ''}".strip())
                        except PartDBError as e:
                            warn.append(f"Couldn't save the price: {e}")
            result = {"part_id": pid, "url": f"{db.url}/en/part/{pid}", "did": did, "warnings": warn}
            self._log(f, result)
            return result

    def _attach(self, db, pid, name, url):
        types = db.names("attachment_types")
        if not types:
            raise PartDBError("Part-DB has no attachment types.")
        t = next((x for x in types if name.lower()[:5] in x["name"].lower()), types[0])
        db.post("/api/attachments", {"_type": "Part", "element": f"/api/parts/{pid}", "name": name, "url": url,
                                     "attachment_type": f"/api/attachment_types/{t['id']}"})

    @staticmethod
    def _currency(db, iso):
        """None means Part-DB's base currency; any other currency must already exist in Part-DB."""
        iso = (iso or "").upper()
        if not iso:
            return None
        for c in db.get("/api/currencies") or []:
            if (c.get("iso_code") or "").upper() == iso:
                return f"/api/currencies/{c['id']}"
        return None

    # ---- the station's own log ----
    def _log(self, form, result):
        row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "name": form.get("name") or form.get("mpn"),
               "mpn": form.get("mpn"), "qty": form.get("qty"), "location": form.get("location"),
               "supplier": form.get("supplier"), "spn": form.get("spn"), "raw": form.get("raw", ""), **result}
        with open(self.data / "saved.jsonl", "a") as fh:
            fh.write(json.dumps(row) + "\n")

    def recent(self, n=30):
        try:
            lines = (self.data / "saved.jsonl").read_text().splitlines()
        except OSError:
            return []
        return [json.loads(x) for x in reversed(lines[-n:]) if x.strip()]


def _last(cat):
    """Distributors give a path ("Integrated Circuits → Amplifiers"); keep its last step."""
    if not cat:
        return ""
    for sep in ("→", "->", ">", "/"):
        if sep in cat:
            return cat.split(sep)[-1].strip()
    return cat.strip()


def _param(x):
    if x.get("value_text"):
        return x["value_text"]
    v = x.get("value_typ") if x.get("value_typ") is not None else x.get("value_min")
    return f"{v if v is not None else ''} {x.get('unit') or ''}".strip()


def _n(x):
    return str(int(x)) if float(x).is_integer() else str(x)
