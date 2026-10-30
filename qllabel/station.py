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

from . import data as D
from . import render as R
from .printer import JobOptions, Printer, PrinterError

DATA = Path.home() / "ql-labels-data"
NAME_OK = re.compile(r"^[\w .-]{1,60}$")
MAX_BATCH = 500
MIN_MARGIN = 35


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
        self.bdir = data / "tables"
        for d in (self.tdir, self.idir, self.cdir, self.bdir):
            d.mkdir(parents=True, exist_ok=True)
        R.IMAGES = self.idir
        self.load_bleed()
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
                out.append({"name": f.stem, "length_mm": t.get("length_mm"), "media": str(t.get("media") or t.get("tape") or "29"),
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))})
            except (OSError, json.JSONDecodeError):
                continue
        return {"templates": out}

    def load(self, name: str) -> dict:
        f = self._tfile(name)
        if not f.exists():
            raise ValueError(f"No template called {name!r}.")
        return D.migrate({**R.DEFAULT, **json.loads(f.read_text()), "name": name}, self.csv_rows)

    def save(self, tpl: dict) -> dict:
        f = self._tfile(tpl.get("name", ""))
        D.migrate(tpl, self.csv_rows)
        D.check(tpl["data"])
        f.write_text(json.dumps(tpl, indent=1))
        return {"saved": f.stem}

    def delete(self, name: str) -> dict:
        f = self._tfile(name)
        f.unlink(missing_ok=True)
        return {"deleted": name}

    # ---- per-roll bleed (extra printable dots past Brother's window)
    def load_bleed(self):
        f = self.data / "media.json"
        try:
            for k, v in json.loads(f.read_text()).get("bleed", {}).items():
                R.BLEED[k] = (int(v[0]), int(v[1]))
        except (OSError, ValueError):
            pass

    def set_bleed(self, mid: str, head: int, open_: int) -> dict:
        m = R.media(mid)
        if m.die_cut:
            raise ValueError("Bleed is only for continuous rolls.")
        R.BLEED[m.id] = (max(0, min(m.right, int(head))), max(0, min(60, int(open_))))
        f = self.data / "media.json"
        try:
            cur = json.loads(f.read_text())
        except (OSError, ValueError):
            cur = {}
        cur.setdefault("bleed", {})[m.id] = list(R.BLEED[m.id])
        f.write_text(json.dumps(cur, indent=1))
        return R.media_list()

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

    # ---- batches: the template's data table (data.py)
    def _data(self, tpl: dict) -> dict:
        D.migrate(tpl, self.csv_rows)
        D.ensure_fields(tpl["data"], R.fields_in(tpl), tpl.get("fields") or {})
        return tpl["data"]

    def batch_rows(self, tpl: dict, overrides: dict | None = None) -> tuple[list[dict], list[str]]:
        self._data(tpl)
        return D.resolve(tpl, overrides)

    def batch_info(self, tpl: dict) -> dict:
        """Every row (for the table) plus a decode check of the first and last few labels."""
        rows, warn = self.batch_rows(tpl)
        sample = sorted(set(list(range(min(3, len(rows)))) + list(range(max(0, len(rows) - 3), len(rows)))))
        bad = []
        for i in sample:
            img, _, _ = R.render(tpl, rows[i])
            for c in R.verify(img, tpl, rows[i]):
                if not c["ok"]:
                    bad.append(f"row {i + 1}: {c['type']} '{c['data']}' doesn't read back")
        return {"count": len(rows), "rows": rows, "first": rows[:3], "last": rows[-1] if rows else None,
                "warnings": warn + bad, "checked": [i + 1 for i in sample], "data": tpl["data"]}

    def print_batch(self, tpl: dict, copies: int = 1, over: dict | None = None, values: dict | None = None) -> dict:
        rows, warn = self.batch_rows(tpl, values)
        if not rows:
            raise ValueError("The batch is empty: " + "; ".join(warn))
        if len(rows) * max(1, int(copies)) > MAX_BATCH:
            raise ValueError(f"More than {MAX_BATCH} labels in one go; split the batch.")
        r = self.print_rows(tpl, rows, copies, over)
        d = tpl["data"]
        if d.get("advance", True) and any(c["mode"] in ("sequence", "ip") for c in d["columns"]):
            # carry on numbering next time: stored in the saved template, if there is one
            D.advance(d, len(rows))
            main = next((c for c in d["columns"] if c["name"] == d.get("main")), {})
            r["next_start"] = main.get("start")
            r["data"] = d
            try:
                f = self._tfile(tpl.get("name", ""))
                if f.exists():
                    saved = D.migrate(json.loads(f.read_text()), self.csv_rows)
                    saved["data"]["columns"] = d["columns"]
                    f.write_text(json.dumps(saved, indent=1))
                    r["advanced"] = f.stem
            except ValueError:
                pass
        return r

    # ---- named tables, to reuse a table in another template
    def _tbl(self, name: str) -> Path:
        if not NAME_OK.match(name or "") or name.startswith("."):
            raise ValueError("Table names: letters, digits, space, dot, dash, underscore (max 60).")
        return self.bdir / f"{name}.json"

    def tables(self) -> dict:
        return {"tables": [f.stem for f in sorted(self.bdir.glob("*.json"))]}

    def save_table(self, name: str, data: dict) -> dict:
        D.check(data)
        keep = {k: data[k] for k in ("main", "count", "advance", "columns", "rows") if k in data}
        self._tbl(name).write_text(json.dumps(keep, indent=1))
        return {"saved": name, **self.tables()}

    def load_table(self, name: str) -> dict:
        f = self._tbl(name)
        if not f.exists():
            raise ValueError(f"No table called {name!r}.")
        return json.loads(f.read_text())

    # ---- render / print
    def preview(self, tpl: dict, values: dict | None = None) -> dict:
        img, boxes, warn = R.render(tpl, values)
        return {"png": png_b64(img), "boxes": boxes, "warnings": warn, "checks": R.verify(img, tpl, values),
                **R.info(tpl)}

    def options(self, tpl: dict, over: dict | None = None) -> JobOptions:
        o = {**tpl, **(over or {})}
        # the QL-810W feeds at least 35 dots (~3 mm) at each end of every page whatever we send (measured 2026-10-28)
        return JobOptions(media=R.tpl_media(o).id, margin=max(MIN_MARGIN, int(o.get("margin", 35))), cut=o.get("cut", "each"),
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
        labels = len(pages)
        strip = {**R.STRIP_DEFAULT, **(tpl.get("strip") or {}), **((over or {}).get("strip") or {})}
        if strip["on"] and not R.tpl_media(tpl).die_cut:
            pages = R.strips(pages, int(strip.get("per") or 0), strip.get("marks", "edge"), bool(strip.get("ends", True)))
        if len(pages) > 500:
            raise ValueError("More than 500 labels in one go; split the batch.")
        r = self._print(pages, self.options(tpl, over))
        r["labels"] = labels
        if len(pages) != labels:
            r["strips"] = len(pages)
        return r

    def calibrate(self, lengths: list[float], margin: int = 35, cut: str = "each", tape=None, flip: bool | None = None):
        tape = tape or self.status().get("media") or "29"        # default: whatever roll is loaded
        if R.media(tape).die_cut:
            raise ValueError("Calibration strips need a continuous roll.")
        lengths = [float(x) for x in lengths if 0.5 <= float(x) <= 300][:30]
        if not lengths:
            raise ValueError("Give at least one length between 0.5 and 300 mm.")
        flip = self.flip if flip is None else bool(flip)
        pages = [R.page(p, flip) for p in R.calibration(lengths, tape, f"m{int(margin)}")]
        return self._print(pages, JobOptions(media=str(tape), margin=int(margin), cut=cut))

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
