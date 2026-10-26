"""A small client for Part-DB's REST API (https://docs.part-db.de/api/).

Needs an API token made in Part-DB under  user menu → User settings → API tokens.
"Edit" access is enough for adding parts and stock; the supplier lookups also need the user to be
allowed to create parts from info providers.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
LOOKUP_TIMEOUT = 60   # the distributor lookups go out to DigiKey/Mouser/LCSC and can be slow


class PartDBError(Exception):
    pass


def iri_id(v):
    """The id from an IRI ("/api/parts/12"), an embedded object, or None."""
    if isinstance(v, dict):
        v = v.get("@id") or v.get("id")
    if isinstance(v, int):
        return v
    m = re.search(r"/(\d+)$", str(v or ""))
    return int(m.group(1)) if m else None


class PartDB:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token.strip()

    # ---- HTTP ----
    def _req(self, method, path, body=None, query=None, timeout=TIMEOUT, ctype="application/json"):
        if not self.token:
            raise PartDBError("No Part-DB API token yet. Add one under SETTINGS.")
        url = self.url + path
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/json", "Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.geturl().rstrip("/").endswith("/login"):
                    raise PartDBError("Part-DB sent us to its login page; the API token was not accepted.")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise PartDBError(self._why(e)) from None
        except urllib.error.URLError as e:
            raise PartDBError(f"Can't reach Part-DB at {self.url}: {e.reason}") from None
        except json.JSONDecodeError:
            raise PartDBError("Part-DB answered with something that isn't JSON (is the URL right?).") from None

    @staticmethod
    def _why(e):
        try:
            j = json.loads(e.read() or b"{}")
        except (json.JSONDecodeError, OSError):
            j = {}
        msg = j.get("detail") or j.get("hydra:description") or j.get("description") or j.get("title") or ""
        if j.get("violations"):
            msg = "; ".join(f"{v.get('propertyPath')}: {v.get('message')}" for v in j["violations"])
        if e.code == 401:
            return "Part-DB didn't accept the API token (401). Check it under SETTINGS."
        if e.code == 403:
            return "The API token isn't allowed to do that (403). " + msg
        return f"Part-DB said {e.code}: {msg or e.reason}"

    def get(self, path, **query):
        return self._req("GET", path, query=query)

    def post(self, path, body, timeout=TIMEOUT):
        return self._req("POST", path, body, timeout=timeout)

    def patch(self, path, body):
        return self._req("PATCH", path, body, ctype="application/merge-patch+json")

    # ---- who and what ----
    def whoami(self):
        tok = self.get("/api/tokens/current")
        info = self.get("/api/info")
        user = tok.get("user") if isinstance(tok, dict) else None
        if isinstance(user, str) and user.startswith("/api/"):
            try:
                user = self.get(user).get("name")
            except PartDBError:
                pass
        elif isinstance(user, dict):
            user = user.get("name")
        return {"user": user or "", "token": tok.get("name", ""), "level": tok.get("level"),
                "version": info.get("version", ""), "title": info.get("title", "")}

    def names(self, kind):
        """[(id, name)] for categories, footprints, manufacturers, suppliers, storage_locations, attachment_types."""
        rows = self.get(f"/api/{kind}", itemsPerPage=1000, **{"order[name]": "asc"})
        return [{"id": r["id"], "name": r["name"], "path": r.get("full_path") or r["name"]} for r in rows or []]

    def resolve(self, kind, name, create=True):
        """The IRI for a category/footprint/... called `name`, made if it doesn't exist yet."""
        name = (name or "").strip()
        if not name:
            return None, False
        rows = self.get(f"/api/{kind}", name=name.replace("%", r"\%").replace("_", r"\_"))
        for r in rows or []:
            if r["name"] == name:
                return f"/api/{kind}/{r['id']}", False
        if rows:
            return f"/api/{kind}/{rows[0]['id']}", False
        if not create:
            return None, False
        r = self.post(f"/api/{kind}", {"name": name})
        return f"/api/{kind}/{r['id']}", True

    # ---- finding parts ----
    def find(self, mpn="", spn="", gtin=""):
        """Parts already in Part-DB with this manufacturer or supplier part number."""
        ids = []
        if mpn:
            for p in self.get("/api/parts", manufacturer_product_number=mpn) or []:
                ids.append(p["id"])
        if spn:
            for od in self.get("/api/orderdetails", supplierpartnr=spn) or []:
                pid = iri_id(od.get("part"))
                if pid:
                    ids.append(pid)
        if gtin and not ids:
            for p in self.get("/api/parts", name=gtin) or []:
                ids.append(p["id"])
        out = []
        for pid in dict.fromkeys(ids):
            try:
                out.append(self.part(pid))
            except PartDBError:
                pass
        return out

    def part(self, pid):
        p = self.get(f"/api/parts/{pid}")
        lots = []
        for lot in p.get("partLots") or p.get("part_lots") or []:
            loc = lot.get("storage_location")
            lots.append({"id": iri_id(lot), "amount": lot.get("amount"), "unknown": lot.get("instock_unknown"),
                         "location_id": iri_id(loc),
                         "location": loc.get("name") if isinstance(loc, dict) else "",
                         "description": lot.get("description", "")})
        return {"id": p["id"], "name": p.get("name", ""), "description": p.get("description", ""),
                "mpn": p.get("manufacturer_product_number", ""), "category_id": iri_id(p.get("category")),
                "manufacturer_id": iri_id(p.get("manufacturer")), "footprint_id": iri_id(p.get("footprint")),
                "total": p.get("total_instock"), "lots": lots, "url": f"{self.url}/en/part/{p['id']}"}

    def lot(self, lid):
        return self.get(f"/api/part_lots/{lid}")

    # ---- distributor lookups (Part-DB's info providers) ----
    def providers(self):
        rows = self.get("/api/info_providers") or []
        return [{"key": r["key"], "name": r["name"], "slow": r.get("slow") or r.get("expensive")} for r in rows]

    def search(self, keyword, providers):
        body = {"keyword": keyword}
        if providers:
            body["providers"] = providers
        r = self._req("POST", "/api/info_providers/search", body, timeout=LOOKUP_TIMEOUT)
        return r if isinstance(r, list) else (r or {}).get("hydra:member", [r] if r else [])

    def details(self, provider_key, provider_id):
        return self._req("POST", "/api/info_providers/details",
                         {"provider_key": provider_key, "provider_id": provider_id}, timeout=LOOKUP_TIMEOUT)
