"""The label designer web page: python -m qllabel serve  (http://localhost:8097)."""

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .printer import PrinterError
from . import render as R
from .station import Station

STATIC = Path(__file__).parent / "static"
HELP = Path(__file__).parent.parent / "HELP.md"
HELP_PAGE = STATIC / "help.html"
MAX_BODY = 12 * 1024 * 1024
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript", ".svg": "image/svg+xml"}


def help_page() -> bytes:
    """HELP.md as a page in the designer's style (one source for the page and the file)."""
    import markdown
    md = markdown.Markdown(extensions=["tables", "toc"], extension_configs={"toc": {"title": "Contents"}})
    body = md.convert(HELP.read_text())
    return HELP_PAGE.read_text().replace("<!--BODY-->", body).encode()


def make_handler(st: Station):
    class H(BaseHTTPRequestHandler):
        server_version = "ql-labels"

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

        def _jbody(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("Request too big.")
            return json.loads(self.rfile.read(n) or b"{}")

        def _run(self, fn):
            try:
                self._json(fn())
            except (PrinterError, ValueError) as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:   # keep the page alive; the console gets the details
                traceback.print_exc()
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_GET(self):
            u = urlparse(self.path)
            path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
            if path in ("/", "/index.html"):
                path = "/static/index.html"
            if path == "/help":
                return self._send(200, help_page(), "text/html; charset=utf-8")
            if path == "/colors":
                path = "/static/colors.html"
            if path.startswith("/static/"):
                f = (STATIC / path[len("/static/"):]).resolve()
                if STATIC.resolve() in f.parents and f.is_file():
                    return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
                return self._send(404, b"not found", "text/plain")
            routes = {"/api/status": st.status, "/api/templates": st.templates,
                      "/api/template": lambda: st.load(q.get("name", "")),
                      "/api/media": R.media_list, "/api/images": st.images, "/api/csvs": st.csvs,
                      "/api/csv": lambda: st.csv_info(q.get("name", "")),
                      "/api/tables": st.tables, "/api/table": lambda: st.load_table(q.get("name", ""))}
            if path in routes:
                return self._run(routes[path])
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            routes = {
                "/api/preview": lambda b: st.preview(b["template"], b.get("values")),
                "/api/save": lambda b: st.save(b["template"]),
                "/api/delete": lambda b: st.delete(b.get("name", "")),
                "/api/print": lambda b: st.print_rows(b["template"], b.get("rows"), b.get("copies", 1)),
                "/api/print_batch": lambda b: st.print_batch(b["template"], b.get("copies", 1)),
                "/api/save_table": lambda b: st.save_table(b.get("name", ""), b.get("data") or {}),
                "/api/batch": lambda b: st.batch_info(b["template"]),
                "/api/image": lambda b: st.upload_image(b.get("name", ""), b["png"]),
                "/api/upload_csv": lambda b: st.upload_csv(b.get("name", ""), b.get("text", "")),
                "/api/bleed": lambda b: st.set_bleed(str(b.get("media", "")), b.get("head", 0), b.get("open", 0)),
                "/api/calibrate": lambda b: st.calibrate(b.get("lengths", []), b.get("margin", 35),
                                                         b.get("cut", "each"), b.get("media") or b.get("tape"), b.get("flip")),
            }
            if path not in routes:
                return self._send(404, b"not found", "text/plain")
            self._run(lambda: routes[path](self._jbody()))

    return H


def serve(st: Station, host: str = "127.0.0.1", port: int = 8097):
    httpd = ThreadingHTTPServer((host, port), make_handler(st))
    print(f"QL label designer on http://{'localhost' if host == '127.0.0.1' else host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
