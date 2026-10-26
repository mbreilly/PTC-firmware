"""A tiny stand-in for Part-DB's REST API, enough to exercise the station's calls (not a full copy)."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

KINDS = ("parts", "part_lots", "orderdetails", "pricedetails", "attachments", "categories", "footprints",
         "manufacturers", "suppliers", "storage_locations", "attachment_types", "currencies")


class Fake:
    def __init__(self, token="tcp_test"):
        self.token = token
        self.db = {k: {} for k in KINDS}
        self.seq = 0
        self.calls = []
        self.add("categories", name="ICs")
        self.add("attachment_types", name="Datasheet")
        self.add("storage_locations", name="Drawer A1")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def add(self, kind, **row):
        self.seq += 1
        row["id"] = self.seq
        self.db[kind][self.seq] = row
        return row

    def view(self, kind, row):
        if kind == "parts":
            lots = [dict(l, storage_location=self.db["storage_locations"].get(int(l["storage_location"].rsplit("/", 1)[1]))
                         if l.get("storage_location") else None)
                    for l in self.db["part_lots"].values() if l["part"] == f"/api/parts/{row['id']}"]
            return dict(row, partLots=lots, total_instock=sum(l["amount"] for l in lots))
        return row

    def handler(fake):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def go(self, method):
                u = urlparse(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"null")
                fake.calls.append((method, u.path, body, self.headers.get("Content-Type")))
                if self.headers.get("Authorization") != "Bearer " + fake.token:
                    return self.reply(401, {"detail": "bad token"})
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if u.path == "/api/info":
                    return self.reply(200, {"version": "2.20.2", "title": "Part-DB"})
                if u.path == "/api/tokens/current":
                    return self.reply(200, {"name": "station", "level": 1, "user": "/api/users/1"})
                if u.path == "/api/users/1":
                    return self.reply(200, {"name": "mike"})
                if u.path == "/api/info_providers":
                    return self.reply(200, [{"key": "lcsc", "name": "LCSC"}])
                if u.path == "/api/info_providers/search":
                    return self.reply(200, [{"provider_key": "lcsc", "provider_id": "C7593", "mpn": "LM358DR2G",
                                             "name": "LM358DR2G", "description": "op amp"}])
                if u.path == "/api/info_providers/details":
                    return self.reply(200, {"provider_key": "lcsc", "provider_id": "C7593", "name": "LM358DR2G",
                        "mpn": "LM358DR2G", "description": "Dual op amp", "manufacturer": "onsemi",
                        "category": "Amplifiers → Op Amps", "footprint": "SOIC-8",
                        "datasheets": [{"url": "https://example.com/ds.pdf"}], "preview_image_url": "https://example.com/i.jpg",
                        "vendor_infos": [{"distributor_name": "LCSC", "order_number": "C7593", "product_url": "https://lcsc.com/C7593",
                                          "prices": [{"minimum_discount_amount": 1, "price": "0.0812", "currency_iso_code": "USD"}]}]})
                m = re.match(r"^/api/(\w+)(?:/(\d+))?$", u.path)
                if not m or m.group(1) not in KINDS:
                    return self.reply(404, {"detail": "no route"})
                kind, rid = m.group(1), m.group(2)
                rows = fake.db[kind]
                if method == "GET" and rid:
                    return self.reply(200, fake.view(kind, rows[int(rid)])) if int(rid) in rows else self.reply(404, {})
                if method == "GET":
                    out = list(rows.values())
                    for k, v in q.items():
                        if k in ("itemsPerPage",) or k.startswith("order["):
                            continue
                        v = v.replace("\\%", "%").replace("\\_", "_").lower()
                        out = [r for r in out if str(r.get(k, "")).lower() == v]
                    return self.reply(200, [fake.view(kind, r) for r in out])
                if method == "POST":
                    if kind == "parts" and not body.get("category"):
                        return self.reply(422, {"violations": [{"propertyPath": "category", "message": "pick one"}]})
                    return self.reply(201, fake.add(kind, **body))
                if method == "PATCH":
                    if self.headers.get("Content-Type") != "application/merge-patch+json":
                        return self.reply(415, {"detail": "wrong type"})
                    rows[int(rid)].update(body)
                    return self.reply(200, rows[int(rid)])

            def do_GET(self): self.go("GET")
            def do_POST(self): self.go("POST")
            def do_PATCH(self): self.go("PATCH")
        return H
