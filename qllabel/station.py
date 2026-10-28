"""What the web page and the command line share: templates on disk, rendering, printing."""

import base64
import csv
import hashlib
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
MAX_BATCH = 500
BATCH_DEFAULT = {"on": False, "source": "range", "field": "serial", "prefix": "PTC-", "suffix": "", "start": 1,
                 "count": 10, "step": 1, "digits": 5, "advance": True, "csv": "", "map": {}, "first_row": 1,
                 "last_row": 0, "list": ""}


def png_b64(img) -> str:
    buf = io.BytesIO()
    img.convert("1").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class Station:
    def __init__(self, data: Path = DATA, device: str | None = None, dry_run: bool = False, flip: bool = False):
        self.data = data
        self.tdir = data / "templates"
        self.idir = data / "images"
        self.cdir = data / "csv"
        for d in (self.tdir, self.idir, self.cdir):
            d.mkdir(parents=True, exist_ok=True)
        R.IMAGES = self.idir
        for f in sorted((Path(__file__).parent.parent / "assets").glob("*.png")):   # built-in graphics
            try:
                self.upload_image(f.stem.replace("_", " "), base64.b64encode(f.read_bytes()).decode())
            except Exception as e:   # a bad asset shouldn't stop the app
                print(f"skipping {f.name}: {e}")
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

    # ---- graphics and CSV files
    def upload_image(self, name: str, b64png: str) -> dict:
        raw = base64.b64decode(b64png.split(",")[-1])
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        if im.width * im.height > 4000 * 4000:
            raise ValueError("That picture is too big.")
        f = self.idir / (hashlib.sha1(raw).hexdigest()[:16] + ".png")
        if not f.exists():
            im.save(f, "PNG")
        (self.idir / (f.stem + ".name")).write_text((name or "graphic")[:80])
        return {"src": f.name, "w": im.width, "h": im.height}

    def images(self) -> dict:
        out = []
        for f in sorted(self.idir.glob("*.png"), key=lambda p: -p.stat().st_mtime):
            n = self.idir / (f.stem + ".name")
            out.append({"src": f.name, "name": n.read_text() if n.exists() else f.stem,
                        "png": base64.b64encode(f.read_bytes()).decode() if f.stat().st_size < 400_000 else ""})
        return {"images": out}

    def _csvfile(self, name: str) -> Path:
        name = Path(name or "").name
        if not name.lower().endswith(".csv"):
            name += ".csv"
        if not NAME_OK.match(name):
            raise ValueError("CSV names: letters, digits, space, dot, dash, underscore.")
        return self.cdir / name

    def upload_csv(self, name: str, text: str) -> dict:
        f = self._csvfile(name)
        f.write_text(text)
        return self.csv_info(f.name)

    def csv_rows(self, name: str) -> tuple[list[str], list[dict]]:
        f = self._csvfile(name)
        if not f.exists():
            raise ValueError(f"No CSV called {name!r}; upload it on the batch tab.")
        text = f.read_text(errors="replace").lstrip("\ufeff")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rd = csv.DictReader(io.StringIO(text), dialect=dialect)
        rows = [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in rd]
        return [c.strip() for c in (rd.fieldnames or []) if c], rows

    def csv_info(self, name: str) -> dict:
        cols, rows = self.csv_rows(name)
        return {"csv": self._csvfile(name).name, "columns": cols, "count": len(rows), "head": rows[:5]}

    def csvs(self) -> dict:
        return {"csvs": [f.name for f in sorted(self.cdir.glob("*.csv"))]}

    # ---- batches
    def batch_rows(self, tpl: dict) -> list[dict]:
        b = {**BATCH_DEFAULT, **(tpl.get("batch") or {})}
        fields = R.fields_in(tpl)
        if b["source"] == "range":
            n, step, start = int(b["count"]), int(b["step"]) or 1, int(b["start"])
            if not 1 <= n <= MAX_BATCH:
                raise ValueError(f"Batch count must be 1 to {MAX_BATCH}.")
            digits = max(0, min(12, int(b["digits"])))
            return [{b["field"]: f"{b['prefix']}{start + i * step:0{digits}d}{b['suffix']}"} for i in range(n)]
        if b["source"] == "csv":
            cols, rows = self.csv_rows(b["csv"])
            first = max(1, int(b.get("first_row") or 1))
            last = int(b.get("last_row") or 0) or len(rows)
            mapping = {f: b["map"].get(f) or next((c for c in cols if c.lower() == f.lower()), None) for f in fields}
            missing = [f for f, c in mapping.items() if not c]
            if missing and fields:
                raise ValueError("Pick a CSV column for " + ", ".join("{" + m + "}" for m in missing) + ".")
            return [{f: r.get(c, "") for f, c in mapping.items()} for r in rows[first - 1:last]]
        lines = [l.strip() for l in str(b.get("list", "")).splitlines() if l.strip()]
        out = []
        for l in lines:
            parts = l.split("\t") if "\t" in l else l.split(",") if len(fields) > 1 else [l]
            out.append({f: (parts[i].strip() if i < len(parts) else "") for i, f in enumerate(fields)})
        return out

    def batch_info(self, tpl: dict) -> dict:
        rows = self.batch_rows(tpl)
        return {"count": len(rows), "first": rows[:3], "last": rows[-1] if rows else None}

    def print_batch(self, tpl: dict, copies: int = 1, over: dict | None = None) -> dict:
        rows = self.batch_rows(tpl)
        if not rows:
            raise ValueError("The batch is empty.")
        if len(rows) * max(1, int(copies)) > MAX_BATCH:
            raise ValueError(f"More than {MAX_BATCH} labels in one go; split the batch.")
        r = self.print_rows(tpl, rows, copies, over)
        b = {**BATCH_DEFAULT, **(tpl.get("batch") or {})}
        if b["source"] == "range" and b["advance"]:
            # carry on numbering next time: stored in the saved template, if there is one
            b["start"] = int(b["start"]) + int(b["count"]) * (int(b["step"]) or 1)
            r["next_start"] = b["start"]
            try:
                f = self._tfile(tpl.get("name", ""))
                if f.exists():
                    saved = json.loads(f.read_text())
                    saved["batch"] = {**BATCH_DEFAULT, **(saved.get("batch") or {}), "start": b["start"]}
                    f.write_text(json.dumps(saved, indent=1))
                    r["advanced"] = f.stem
            except ValueError:
                pass
        return r

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
            pages += [R.page(img, bool(tpl.get("flip", self.flip)), bool(tpl.get("across")))] * copies
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
