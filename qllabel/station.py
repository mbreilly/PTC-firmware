"""What the web page and the command line share: templates on disk, rendering, printing."""

import base64
import io
import json
import re
import threading
import time
from pathlib import Path

from . import render as R
from .printer import JobOptions, Printer, PrinterError

DATA = Path.home() / "ql-labels-data"
NAME_OK = re.compile(r"^[\w .-]{1,60}$")


def png_b64(img) -> str:
    buf = io.BytesIO()
    img.convert("1").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class Station:
    def __init__(self, data: Path = DATA, device: str | None = None, dry_run: bool = False, flip: bool = False):
        self.data = data
        self.tdir = data / "templates"
        self.tdir.mkdir(parents=True, exist_ok=True)
        self.printer = Printer(device, data / "dry-run" if dry_run else None)
        self.flip = flip
        self.lock = threading.Lock()
        self._st = (0.0, None)

    # ---- templates
    def _tfile(self, name: str) -> Path:
        if not NAME_OK.match(name or "") or name.startswith("."):
            raise ValueError("Template names: letters, digits, space, dot, dash, underscore (max 60).")
        return self.tdir / f"{name}.json"

    def templates(self):
        out = []
        for f in sorted(self.tdir.glob("*.json")):
            try:
                t = json.loads(f.read_text())
                out.append({"name": f.stem, "length_mm": t.get("length_mm"), "tape": t.get("tape"),
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))})
            except (OSError, json.JSONDecodeError):
                continue
        return {"templates": out}

    def load(self, name: str) -> dict:
        f = self._tfile(name)
        if not f.exists():
            raise ValueError(f"No template called {name!r}.")
        return {**R.DEFAULT, **json.loads(f.read_text()), "name": name}

    def save(self, tpl: dict) -> dict:
        f = self._tfile(tpl.get("name", ""))
        f.write_text(json.dumps(tpl, indent=1))
        return {"saved": f.stem}

    def delete(self, name: str) -> dict:
        f = self._tfile(name)
        f.unlink(missing_ok=True)
        return {"deleted": name}

    # ---- render / print
    def preview(self, tpl: dict, values: dict | None = None) -> dict:
        img, boxes, warn = R.render(tpl, values)
        return {"png": png_b64(img), "boxes": boxes, "warnings": warn, "checks": R.verify(img, tpl, values),
                **R.info(tpl)}

    def options(self, tpl: dict, over: dict | None = None) -> JobOptions:
        o = {**tpl, **(over or {})}
        return JobOptions(tape=int(o.get("tape", 29)), margin=int(o.get("margin", 35)), cut=o.get("cut", "each"),
                          cut_every=int(o.get("cut_every", 1)))

    def print_rows(self, tpl: dict, rows: list[dict] | None = None, copies: int = 1, over: dict | None = None):
        rows = rows or [{}]
        copies = max(1, min(100, int(copies)))
        pages, bad = [], []
        for row in rows:
            img, _, _ = R.render(tpl, row)
            for c in R.verify(img, tpl, row):
                if not c["ok"]:
                    bad.append(f"{c['type']} '{c['data']}' did not read back")
            pages += [R.page(img, bool(tpl.get("flip", self.flip)))] * copies
        if bad:
            raise ValueError("Not printing: " + "; ".join(bad[:5]))
        if len(pages) > 500:
            raise ValueError("More than 500 labels in one go; split the batch.")
        return self._print(pages, self.options(tpl, over))

    def calibrate(self, lengths: list[float], margin: int = 35, cut: str = "each", tape: int = 29, flip: bool | None = None):
        lengths = [float(x) for x in lengths if 0.5 <= float(x) <= 300][:30]
        if not lengths:
            raise ValueError("Give at least one length between 0.5 and 300 mm.")
        flip = self.flip if flip is None else bool(flip)
        pages = [R.page(p, flip) for p in R.calibration(lengths, tape)]
        return self._print(pages, JobOptions(tape=tape, margin=int(margin), cut=cut))

    def _print(self, pages, opt):
        if not self.lock.acquire(timeout=1):
            raise PrinterError("Printer is busy with another job.")
        try:
            r = self.printer.print_job(pages, opt)
            self._st = (0.0, None)
            return r
        finally:
            self.lock.release()

    def status(self) -> dict:
        t, cached = self._st
        if cached and time.monotonic() - t < 3:
            return cached
        if not self.lock.acquire(blocking=False):
            return cached or {"ok": True, "busy": True}
        try:
            st = self.printer.status()
            out = {"ok": not st.errors, **st.as_dict(), "device": self.printer.device or "auto",
                   "dry_run": bool(self.printer.dry_run_dir)}
        except (PrinterError, OSError) as e:
            out = {"ok": False, "error": str(e)}
        finally:
            self.lock.release()
        self._st = (time.monotonic(), out)
        return out
