"""The local web page: python -m partdb_station  (opens http://localhost:8095).

The webcam only works on a page served from localhost (or https). From another computer the page
still works with a USB scanner, or by uploading a photo of the label."""

import json
import traceback
import webbrowser
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import decode as dec
from .partdb import PartDBError
from .station import Station

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 40 * 1024 * 1024
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml"}


def make_handler(st: Station):
    class H(BaseHTTPRequestHandler):
        server_version = "partdb-station"

        def log_message(self, fmt, *args):
            pass

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                raise ValueError("That file is too big.")
            return self.rfile.read(n)

        def _jbody(self):
            return json.loads(self._body() or b"{}")

        def _run(self, fn):
            try:
                self._json(fn())
            except (PartDBError, ValueError) as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:   # keep the page alive; the console gets the details
                traceback.print_exc()
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                path = "/static/index.html"
            if path.startswith("/static/"):
                f = (STATIC / path[len("/static/"):]).resolve()
                if STATIC.resolve() in f.parents and f.is_file():
                    return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
                return self._send(404, b"not found", "text/plain")
            routes = {"/api/status": st.status, "/api/lists": st.lists, "/api/recent": st.recent}
            if path in routes:
                return self._run(routes[path])
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/decode":
                return self._run(lambda: {"codes": dec.decode(self._body())})
            if path == "/api/scan":
                return self._run(lambda: st.scan(self._jbody().get("raw", "")))
            if path == "/api/lookup":
                def lookup():
                    b = self._jbody()
                    return st.lookup(b.get("part") or {}, b.get("vendor", ""), b.get("provider", ""), b.get("provider_id", ""))
                return self._run(lookup)
            if path == "/api/save":
                return self._run(lambda: st.save(self._jbody()))
            if path == "/api/config":
                def config():
                    b = self._jbody()
                    st.set_config(b.get("url"), b.get("token"))
                    return st.status()
                return self._run(config)
            self._send(404, b"not found", "text/plain")

    return H


def main(argv=None):
    ap = ArgumentParser(prog="partdb_station", description="Scan part labels into Part-DB")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to reach it from other computers")
    ap.add_argument("--data", type=Path, default=Path.home() / "partdb-station-data", help="where the save log is kept")
    ap.add_argument("--config", type=Path, default=Path.home() / ".config" / "partdb-station" / "config.json",
                    help="Part-DB address and API token")
    ap.add_argument("--partdb", help="Part-DB address, e.g. http://128.91.45.130 (kept in the config)")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    st = Station(a.data, a.config)
    if a.partdb or not st.cfg.get("url"):
        st.set_config(url=a.partdb or "http://128.91.45.130")
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(st))
    url = f"http://localhost:{a.port}"
    print(f"Part-DB label station at {url}  (Part-DB: {st.cfg['url']})")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
