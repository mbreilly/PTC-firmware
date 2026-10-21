"""Browser GUI for the test station.

GuiUI serves one page (static/index.html) on http://localhost:<port>/ and keeps the
whole screen state here in Python. The page shows that state and sends back the
tester's answers over a websocket on the same port, so refreshing or reopening the
page during a test picks up where it was. Only the websockets package is needed,
which the test suite already uses.
"""

import asyncio
import re
import json
import webbrowser
from pathlib import Path

from loguru import logger as lg
from websockets.asyncio.server import serve, broadcast
from websockets.datastructures import Headers
from websockets.http11 import Response

from ptctestsuite.config import parameters
from ptctestsuite.ui.base import TesterUI, Step, TestAborted, format_value
from ptctestsuite.utils import photos

PAGE = Path(__file__).with_name("static") / "index.html"
FONTS = PAGE.with_name("fonts")


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


class GuiUI(TesterUI):
    def __init__(self, port: int, title: str, station: str, hwdb_on: bool, hwdb_label: str,
                 host: str = "127.0.0.1", open_browser: bool = True):
        self.host, self.port, self.open_browser = host, port, open_browser
        self.clients = set()
        self._ask_id = 0
        self._pending = None          # (id, future, validator)
        self._abort = False
        self._photos: dict[str, photos.Photo] = {}   # this run's photos, served at /photo/<side>
        self.state = {
            "title": title, "station": station,
            "hwdb": {"on": hwdb_on, "label": hwdb_label},
            "screen": "start", "mode": None, "ident": "", "tester": "",
            "plan": [], "results": {}, "last": None,
            "ask": None, "running": None, "status": None, "final": None,
            "camera": {"width": parameters.camera_width, "height": parameters.camera_height,
                       "max_mb": parameters.photo_max_mb},
            "ghosts": {side: photos.ghost_version(side) for side in photos.SIDES},
            "photos": {},
            "run_label": None,
        }

    # ---- server ---------------------------------------------------------------
    @property
    def url(self) -> str:
        return f"http://{'localhost' if self.host in ('127.0.0.1', '0.0.0.0') else self.host}:{self.port}/"

    async def serve(self):
        self.server = await serve(self._handler, self.host, self.port, process_request=self._http,
                                  max_size=(parameters.photo_max_mb * 4 // 3 + 2) * 2 ** 20)
        lg.info(f"GUI running at {self.url}")
        print(f"PTC QC GUI running at {self.url}  (Ctrl+C to quit)")
        if self.open_browser:
            webbrowser.open(self.url)

    def _http(self, connection, request):
        path = request.path.split("?")[0]
        if path == "/ws":
            return None
        if path in ("/", "/index.html"):
            body = PAGE.read_bytes()
            return Response(200, "OK", Headers([("Content-Type", "text/html; charset=utf-8"),
                                                ("Content-Length", str(len(body))),
                                                ("Cache-Control", "no-store")]), body)
        if path.startswith("/fonts/"):
            font = FONTS / Path(path).name
            if font.suffix == ".woff2" and font.is_file():
                body = font.read_bytes()
                return Response(200, "OK", Headers([("Content-Type", "font/woff2"),
                                                    ("Content-Length", str(len(body))),
                                                    ("Cache-Control", "max-age=86400")]), body)
        if path in ("/ghost/front", "/ghost/back"):
            g = photos.ghost_path(path.rsplit("/", 1)[1])
            if g:
                return self._file_response(g.read_bytes(), photos.EXT_MIME[g.suffix])
        if path.startswith("/stored/"):
            name = path[len("/stored/"):]
            stored = Path(parameters.photo_dir) / name
            if re.fullmatch(r"[A-Za-z0-9._-]+", name) and stored.suffix in photos.EXT_MIME and stored.is_file():
                return self._file_response(stored.read_bytes(), photos.EXT_MIME[stored.suffix])
        if path in ("/photo/front", "/photo/back"):
            p = self._photos.get(path.rsplit("/", 1)[1])
            if p:
                return self._file_response(p.data, p.mime)
        return connection.respond(404, "Not found\n")

    @staticmethod
    def _file_response(body: bytes, mime: str):
        return Response(200, "OK", Headers([("Content-Type", mime), ("Content-Length", str(len(body))),
                                            ("Cache-Control", "no-store")]), body)

    async def _handler(self, ws):
        self.clients.add(ws)
        try:
            await ws.send(self._snapshot())
            async for raw in ws:
                self._on_message(raw)
        finally:
            self.clients.discard(ws)

    def _snapshot(self) -> str:
        return json.dumps({"type": "state", "state": self.state}, default=str)

    def _push(self):
        broadcast(self.clients, self._snapshot())

    def _on_message(self, raw):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if data.get("type") == "ghost":
            self._ghost_message(data)
            return
        if data.get("type") == "abort" and self.state["screen"] == "run":
            lg.warning("Tester stopped the test from the GUI")
            self._abort = True
            if self._pending and not self._pending[1].done():
                self._pending[1].set_exception(TestAborted())
            return
        if data.get("type") != "answer" or not self._pending:
            return
        ask_id, fut, validate = self._pending
        if data.get("id") != ask_id or fut.done():
            return
        value = data.get("value")
        error = validate(value) if validate else None
        if error:
            self.state["ask"]["error"] = error
            self._push()
            return
        fut.set_result(value)

    async def _ask(self, kind: str, step: Step | None = None, validate=None, **fields):
        if self._abort and self.state["screen"] == "run":
            raise TestAborted()
        self._ask_id += 1
        ask = {"id": self._ask_id, "kind": kind, "step": step.to_dict() if step else None, "error": None, **fields}
        self.state.update(ask=ask, running=None, status=None)
        fut = asyncio.get_running_loop().create_future()
        self._pending = (self._ask_id, fut, validate)
        self._push()
        try:
            return await fut
        finally:
            self._pending = None
            self.state["ask"] = None

    # ---- screens --------------------------------------------------------------
    async def start(self) -> dict:
        self._abort = False
        self.state.update(screen="start", mode=None, ident="", plan=[], results={}, last=None, final=None,
                          run_label=None)
        from ptctestsuite.utils import board_records
        try:
            boards = {"waiting": board_records.waiting_for_retest()[:12], "recent": board_records.recent(10)}
        except OSError as e:
            lg.error(f"Can't read the board records: {e}")
            boards = {"waiting": [], "recent": []}

        def check(v):
            if not isinstance(v, dict) or v.get("mode") not in ("board", "ship", "lookup"):
                return "Choose what you’re entering first."
            if v["mode"] == "lookup":
                return None if str(v.get("query", "")).strip() else "Scan or type a serial to look up."
            if not str(v.get("tester", "")).strip():
                return "Enter the tester name first."
            if v["mode"] == "board" and not str(v.get("serial", "")).strip():
                return "Scan the PTC serial first."
            if v["mode"] == "ship" and not str(v.get("po", "")).strip():
                return "Enter the purchase order number first."
            return None

        v = await self._ask("start", validate=check, tester=self.state["tester"], boards=boards)
        if v["mode"] == "lookup":
            return {"mode": "lookup", "tester": self.state["tester"] or str(v.get("tester", "")).strip(),
                    "query": str(v["query"]).strip()}
        self.state["tester"] = v["tester"].strip()
        return {"mode": v["mode"], "tester": self.state["tester"], "serial": str(v.get("serial", "")),
                "po": str(v.get("po", "")), "batch": str(v.get("batch", "")).strip()}

    def _ghost_message(self, data: dict):
        """The tester replaced or removed a ghost image from the photo step."""
        side = data.get("side")
        if side not in photos.SIDES:
            return
        try:
            if data.get("action") == "clear":
                photos.clear_ghost(side)
            elif data.get("action") == "set":
                photos.save_ghost(photos.from_data_url(side, data.get("image"), "file"))
            else:
                return
            self.state["ghost_error"] = None
        except (photos.PhotoError, OSError) as e:
            lg.error(f"Ghost image change failed: {e}")
            self.state["ghost_error"] = str(e)
        self.state["ghosts"][side] = photos.ghost_version(side)
        self._push()

    def begin(self, mode, ident, tester, plan):
        self._photos = {}
        self.state["photos"] = {}
        self.state.update(screen="run", mode=mode, ident=ident, tester=tester,
                          plan=[s.to_dict() for s in plan], results={}, last=None, final=None)
        self._push()

    def summary(self, record):
        pass

    async def finish(self, record, upload_message, upload_ok):
        self.state.update(screen="results", running=None, status=None,
                          final={"overall": record.overall_result.name, "message": upload_message,
                                 "ok": upload_ok, "notes": record.tester_notes})
        await self._ask("next")

    async def stopped(self, message, title=None):
        self.state.update(screen="stopped", running=None, status=None,
                          final={"message": message, "title": title or "The test stopped"})
        await self._ask("next")

    # ---- boards tested before -------------------------------------------------
    def set_run(self, label):
        self.state["run_label"] = label
        self._push()

    async def ask_retest_choice(self, board):
        return await self._ask("retest", board=board,
                               validate=lambda v: None if v in ("repair", "retest", "repair_only", "cancel")
                               else "Choose one of the options.")

    async def ask_repair(self, form):
        def check(v):
            if not isinstance(v, dict):
                return "Fill in the repair first."
            if not str(v.get("repaired_by", "")).strip():
                return "Enter who repaired the board."
            if not str(v.get("fault_found", "")).strip() and not str(v.get("action_taken", "")).strip():
                return "Describe the fault found or what was done."
            return None
        v = await self._ask("repair", form=form, validate=check)
        keys = {f["key"] for f in form["failed"]}
        return {"repaired_by": str(v.get("repaired_by", "")), "for_steps": [k for k in v.get("for_steps", []) if k in keys],
                "fault_found": str(v.get("fault_found", "")), "action_taken": str(v.get("action_taken", "")),
                "parts_replaced": str(v.get("parts_replaced", "")), "notes": str(v.get("notes", ""))}

    async def show_board(self, board):
        self.state.update(screen="board", mode=None, ident=board["serial"], plan=[], results={})
        return await self._ask("board", board=board,
                               validate=lambda v: None if v in ("retest", "repair", "back") else "Choose an action.")

    async def pick_board(self, query, rows):
        self.state.update(screen="board", mode=None, ident="")
        serials = {r["serial"] for r in rows}
        v = await self._ask("pick", query=query, rows=rows[:50],
                            validate=lambda v: None if v in serials or v == "" else "Choose a board from the list.")
        return v or None

    # ---- questions ------------------------------------------------------------
    async def ask_number(self, step):
        v = await self._ask("number", step, lambda v: None if _is_number(v) else "Enter a number.")
        return float(v)

    async def ask_yesno(self, step):
        return bool(await self._ask("yesno", step))

    async def ask_judged(self, step):
        def check(v):
            if not isinstance(v, dict) or not str(v.get("value", "")).strip():
                return "Enter the reading first."
            return None
        v = await self._ask("judged", step, check)
        return bool(v["ok"]), str(v["value"]).strip()

    async def ask_text(self, step, default=""):
        optional = step.key == "batch_number"
        v = await self._ask("text", step, None if optional else
                            (lambda v: None if str(v or "").strip() else "Enter or scan a value first."),
                            default=default)
        return str(v or "")

    async def ask_counts(self, step):
        def check(v):
            if not isinstance(v, dict) or not (_is_number(v.get("ordered")) and _is_number(v.get("received"))):
                return "Enter both quantities as numbers."
            return None
        v = await self._ask("counts", step, check)
        return float(v["ordered"]), float(v["received"])

    async def ask_photo(self, step, side, optional=False):
        got = {}

        def check(v):
            if optional and isinstance(v, dict) and v.get("done"):
                got["photo"] = None
                return None
            if not isinstance(v, dict):
                return "Take the photo or choose a file first."
            try:
                got["photo"] = photos.from_data_url(side, v.get("image"), v.get("source", "camera"))
            except photos.PhotoError as e:
                return str(e)
            return None

        v = await self._ask("photo", step, check, side=side, optional=optional)
        photo = got["photo"]
        if photo is None:
            return None
        if v.get("ghost") and side in photos.SIDES:
            try:
                photos.save_ghost(photo)
            except OSError as e:
                lg.error(f"Couldn't save the {side} ghost image: {e}")
            self.state["ghosts"][side] = photos.ghost_version(side)
        if side in photos.SIDES:
            self._photos[side] = photo
            self.state["photos"][side] = self._ask_id
        return photo

    async def ask_notes(self):
        notes = str(await self._ask("notes", Step("notes", "Notes and finish", "End",
                                                  "Add any notes for this run, then finish.")) or "")
        self.saved("notes", notes or "No notes")
        return notes

    async def instruct(self, title, text):
        await self._ask("instruct", title=title, text=text)

    async def confirm(self, title, text, yes="Yes", no="No"):
        return bool(await self._ask("confirm", title=title, text=text, yes=yes, no=no))

    # ---- progress -------------------------------------------------------------
    def running(self, step):
        self.state.update(running=step.to_dict(), status=None)
        self._push()

    def _set(self, key, result: str, value: str):
        self.state["results"][key] = {"result": result, "value": value}
        self.state["last"] = key
        self._push()

    def result(self, key, result, value=None, unit=None, limits=None):
        self.state["running"] = None
        self._set(key, result.name, format_value(value, unit))

    def saved(self, key, value):
        self._set(key, "SAVED", str(value))

    def skipped(self, keys):
        for k in keys:
            self.state["results"][k] = {"result": "SKIPPED", "value": ""}
        self._push()

    def status(self, text):
        self.state.update(status=text, running=None)
        self._push()
