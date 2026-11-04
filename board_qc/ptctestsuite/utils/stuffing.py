"""Stuffing review: every BOM part of one board, beside the same part on a board known to work.

A photo of each side is lined up with the board design (from its fiducials) and saved at a fixed
scale, so a part is in the same place on every board. The review page then shows each BOM line with
its parts, this board beside the reference board, and the tester calls each part OK or says what is
wrong with it. Calls are kept per board in stuffing_dir/<serial>/review.json.

The photo can't decide this by itself: a wrong value only shows as a different printed marking, and
most small capacitors have none. So the score here only marks the parts that look most different;
the tester's calls are the result.

    stuffing_dir/reference.json             {"serial": the board compared against}
    stuffing_dir/<serial>/<side>-photo.jpg  the photo, turned so the D-sub is at the top
    stuffing_dir/<serial>/<side>.jpg        lined up with the design
    stuffing_dir/<serial>/<side>-scores.json  offset and difference of each part from the reference
    stuffing_dir/<serial>/review.json       {ref: {call, note, date}}
"""

import csv
import io
import json
import re
import tarfile
import tempfile
import threading
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from loguru import logger as lg

from ptctestsuite import design_import
from ptctestsuite.config import parameters
from ptctestsuite.utils import inspection

LAYER = {"front": "top", "back": "bot"}
PPI = 500            # scale of a lined-up photo: pixels per inch of board
CROP_PAD = 30        # board around a part in its closeup, in lined-up pixels
CALLS = {"ok": "OK", "missing": "Missing", "wrong": "Wrong value or part", "reversed": "Reversed",
         "dnp_fitted": "Fitted, BOM says no-stuff", "damaged": "Damaged or bad solder", "other": "Other"}
NOT_PARTS = ("FID", "MH", "ZT", "GTP", "TP")   # fiducials, holes and test points: nothing to stuff
_lock = threading.Lock()   # review.json and reference.json are read, changed and written whole


# ---- the design: every part, with its BOM line ----------------------------------------

@lru_cache(maxsize=1)
def design() -> dict:
    """{"parts": [...], "lines": [...], "fiducials": {...}, "outline": {...}}"""
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(parameters.design_odb) as tf:
            tf.extractall(tmp, filter="data")
        odb = design_import.read_odb(design_import._find_step(Path(tmp)))
    lines, by_ref = [], {}
    with open(parameters.design_bom, encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            value = r.get("Value", "").strip()
            line = {"item": r.get("Item Number", "").strip(), "value": value, "dnp": value.upper() == "DNP",
                    "description": re.sub(r"\s+", " ", r.get("Description", "")).strip(),
                    "mpn": r.get("Manufacturer PartNumber", "").strip(), "refs": []}
            for ref in r["Part Reference"].split(","):
                by_ref[ref.strip()] = line
            lines.append(line)
    parts = []
    for p in odb["parts"]:
        line = by_ref.get(p["ref"])
        if line is None or p["ref"].startswith(NOT_PARTS):
            continue
        side = "front" if p["side"] == "top" else "back"
        q = {"ref": p["ref"], "side": side, "box": _box(p, side, odb["outline"]), "package": p["package"]}
        parts.append(q)
        line["refs"].append(p["ref"])
    return {"parts": parts, "lines": [ln for ln in lines if ln["refs"]], "fiducials": odb["fiducials"], "outline": odb["outline"]}


def _origin(side: str, outline: dict) -> tuple[float, float]:
    _, sx, sy = parameters.inspection_orientation[side]
    return min(sx * outline["xmin"], sx * outline["xmax"]), min(sy * outline["ymin"], sy * outline["ymax"])


def _to_px(x: float, y: float, side: str, outline: dict) -> tuple[float, float]:
    """Board inches to pixels of a lined-up photo of that side."""
    _, sx, sy = parameters.inspection_orientation[side]
    ox, oy = _origin(side, outline)
    return (sx * x - ox) * PPI, (sy * y - oy) * PPI


def _box(p: dict, side: str, outline: dict) -> list[int]:
    x0, y0, x1, y1 = p["bbox"]
    t = np.radians(p["rot"])
    c, s = np.cos(t), np.sin(t)
    m = -1 if p["mirror"] else 1
    pts = np.array([_to_px(p["x"] + c * m * u - s * v, p["y"] + s * m * u + c * v, side, outline)
                    for u, v in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
    return [int(pts[:, 0].min()), int(pts[:, 1].min()), int(pts[:, 0].max()), int(pts[:, 1].max())]


def _size(outline: dict) -> tuple[int, int]:
    return int((outline["xmax"] - outline["xmin"]) * PPI), int((outline["ymax"] - outline["ymin"]) * PPI)


# ---- boards ------------------------------------------------------------------------------

def _root() -> Path:
    return Path(parameters.stuffing_dir)


def clean_serial(serial: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(serial).strip()).strip("._")


def _board(serial: str) -> Path:
    s = clean_serial(serial)
    if not s:
        raise ValueError("Enter a board serial first.")
    return _root() / s


def reference() -> str:
    try:
        return json.loads((_root() / "reference.json").read_text())["serial"]
    except (OSError, ValueError, KeyError):
        return ""


def set_reference(serial: str):
    with _lock:
        _root().mkdir(parents=True, exist_ok=True)
        (_root() / "reference.json").write_text(json.dumps({"serial": clean_serial(serial)}))
    lg.info(f"Stuffing review now compares against {clean_serial(serial)}")


def load_review(serial: str) -> dict:
    try:
        return json.loads((_board(serial) / "review.json").read_text())
    except (OSError, ValueError):
        return {}


def boards() -> list[dict]:
    if not _root().is_dir():
        return []
    total = len(design()["parts"])
    out = []
    for d in sorted(p for p in _root().iterdir() if p.is_dir()):
        calls = load_review(d.name)
        out.append({"serial": d.name, "front": (d / "front.jpg").is_file(), "back": (d / "back.jpg").is_file(), "total": total,
                    "called": len(calls), "problems": sum(c["call"] != "ok" for c in calls.values())})
    return out


def set_calls(serial: str, refs: list, call: str, note: str = "") -> dict:
    if call not in CALLS and call != "clear":
        raise ValueError(f"Unknown call {call}")
    known = {p["ref"] for p in design()["parts"]}
    with _lock:
        d = load_review(serial)
        for ref in refs:
            if ref not in known:
                continue
            if call == "clear":
                d.pop(ref, None)
            else:
                d[ref] = {"call": call, "note": note.strip(), "date": time.strftime("%Y-%m-%d %H:%M")}
        _board(serial).mkdir(parents=True, exist_ok=True)
        (_board(serial) / "review.json").write_text(json.dumps(d, indent=1))
    return d


# ---- lining a photo up ---------------------------------------------------------------------

def save_photo(serial: str, side: str, data: bytes, turn: bool) -> dict:
    """Keeps the photo, turned if it was taken with the D-sub at the bottom, and offers the fiducials."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("That image couldn’t be read.")
    if turn:
        img = cv2.rotate(img, cv2.ROTATE_180)
    d = _board(serial)
    d.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(d / f"{side}-photo.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return {"width": img.shape[1], "height": img.shape[0], "fiducials": inspection.fiducial_order(side)}


def line_up(serial: str, side: str, points: dict) -> int:
    """Lines the saved photo up from at least 3 clicked fiducials {ref: [x, y]}; a tag string may hide one."""
    des = design()
    img = cv2.imread(str(_board(serial) / f"{side}-photo.jpg"))
    if img is None:
        raise ValueError("Choose a photo of this side first.")
    fids = {r: f for r, f in des["fiducials"].items() if f["side"] == LAYER[side]}
    use = {r: xy for r, xy in (points or {}).items() if r in fids and xy}
    if len(use) < 3:
        raise ValueError("Click at least 3 fiducials.")
    dots = inspection._gold_dots(img)
    src, dst = [], []
    for r, xy in use.items():
        xy = np.float32(xy)
        if len(dots):
            dist = np.linalg.norm(dots - xy, axis=1)
            xy = dots[dist.argmin()] if dist.min() < img.shape[1] / 150 else xy   # snap to the pad near the click
        src.append(xy)
        dst.append(_to_px(fids[r]["x"], fids[r]["y"], side, des["outline"]))
    src, dst = np.float32(src), np.float32(dst)
    M = cv2.getPerspectiveTransform(src, dst) if len(src) == 4 else np.vstack([cv2.getAffineTransform(src[:3], dst[:3]), [0, 0, 1]])
    out = cv2.warpPerspective(img, M, _size(des["outline"]), flags=cv2.INTER_AREA)
    cv2.imwrite(str(_board(serial) / f"{side}.jpg"), out, [cv2.IMWRITE_JPEG_QUALITY, 93])
    _image.cache_clear()
    (_board(serial) / f"{side}-scores.json").unlink(missing_ok=True)
    lg.info(f"Lined up the {side} of {clean_serial(serial)} from {len(src)} fiducials")
    return len(src)


@lru_cache(maxsize=4)
def _image(serial: str, side: str):
    return cv2.imread(str(_board(serial) / f"{side}.jpg"))


# ---- comparing with the reference ------------------------------------------------------------

def _register(ga, gb, box, pad, m, off=(0, 0)):
    """Where the part's area of ga is in gb: lined-up photos can still be some pixels out towards the edges."""
    x0, y0, x1, y1 = box
    H, W = ga.shape
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    t = ga[Y0:Y1, X0:X1]
    ax, ay = max(0, X0 + off[0] - m), max(0, Y0 + off[1] - m)
    area = gb[ay:min(H, Y1 + off[1] + m), ax:min(W, X1 + off[0] + m)]
    if t.size == 0 or area.shape[0] < t.shape[0] or area.shape[1] < t.shape[1] or t.std() < 2:
        return off, 0.0
    _, best, _, loc = cv2.minMaxLoc(cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED))
    return (ax + loc[0] - X0, ay + loc[1] - Y0), float(best)


def _difference(a, b, box, off) -> float:
    """Colour difference over the part, after taking off each photo's local lighting."""
    x0, y0, x1, y1 = box
    ox, oy = off
    ca, cb = a[y0:y1, x0:x1], b[max(0, y0 + oy):y1 + oy, max(0, x0 + ox):x1 + ox]
    if ca.size == 0 or ca.shape != cb.shape:
        return 0.0
    def around(img, X0, Y0, X1, Y1):
        ring = img[max(0, Y0 - 30):Y1 + 30, max(0, X0 - 30):X1 + 30]
        return np.median(cv2.cvtColor(ring, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32), axis=0)
    la = cv2.cvtColor(ca, cv2.COLOR_BGR2LAB).astype(np.float32) - around(a, x0, y0, x1, y1)
    lb = cv2.cvtColor(cb, cv2.COLOR_BGR2LAB).astype(np.float32) - around(b, x0 + ox, y0 + oy, x1 + ox, y1 + oy)
    d = np.abs(la - lb)
    return float((0.5 * d[..., 0] + d[..., 1] + d[..., 2]).mean())


def scores(serial: str, side: str) -> dict:
    """{ref: {"off": [x, y], "diff": float}} against the reference; kept until a photo or the reference changes."""
    ref = reference()
    path = _board(serial) / f"{side}-scores.json"
    if not ref or clean_serial(serial) == ref:
        return {}
    a, b = _image(ref, side), _image(clean_serial(serial), side)
    if a is None or b is None:
        return {}
    try:
        cached = json.loads(path.read_text())
        if cached.get("reference") == ref:
            return cached["parts"]
    except (OSError, ValueError, KeyError):
        pass
    ga, gb = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    out = {}
    for p in design()["parts"]:
        if p["side"] != side:
            continue
        off, wide = _register(ga, gb, p["box"], 60, 45)
        off = off if wide >= 0.4 else (0, 0)
        off, _ = _register(ga, gb, p["box"], 8, 8, off)
        out[p["ref"]] = {"off": [int(off[0]), int(off[1])], "diff": round(_difference(a, b, p["box"], off), 1)}
    path.write_text(json.dumps({"reference": ref, "parts": out}))
    return out


def crop(serial: str, side: str, ref: str, offset: bool = True, pad: int = CROP_PAD) -> bytes | None:
    """A closeup of one part on one board, moved by the offset found against the reference."""
    img = _image(clean_serial(serial), side)
    p = next((q for q in design()["parts"] if q["ref"] == ref and q["side"] == side), None)
    if img is None or p is None:
        return None
    ox, oy = scores(serial, side).get(ref, {}).get("off", (0, 0)) if offset else (0, 0)
    x0, y0, x1, y1 = p["box"]
    H, W = img.shape[:2]
    c = img[max(0, y0 + oy - pad):min(H, y1 + oy + pad), max(0, x0 + ox - pad):min(W, x1 + ox + pad)]
    if c.size == 0:
        return None
    long = max(c.shape[:2])
    if long < 240:
        c = cv2.resize(c, None, fx=240 / long, fy=240 / long, interpolation=cv2.INTER_CUBIC)
    return cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


# ---- what the page and the export show --------------------------------------------------------

def board_view(serial: str) -> dict:
    des = design()
    calls = load_review(serial)
    sides = {"front": (_board(serial) / "front.jpg").is_file(), "back": (_board(serial) / "back.jpg").is_file()}
    diffs = {}
    for side, there in sides.items():
        if there:
            diffs.update(scores(serial, side))
    ranked = sorted((v["diff"] for v in diffs.values()), reverse=True)
    cut = ranked[len(ranked) // 10] if ranked else None   # the tenth that look most different
    where = {p["ref"]: p["side"] for p in des["parts"]}
    lines = []
    for ln in des["lines"]:
        lines.append({**{k: ln[k] for k in ("item", "value", "dnp", "description", "mpn")},
                      "parts": [{"ref": r, "side": where[r], "call": calls.get(r, {}).get("call", ""), "note": calls.get(r, {}).get("note", ""),
                                 "different": bool(cut is not None and r in diffs and diffs[r]["diff"] >= cut)} for r in ln["refs"]]})
    return {"serial": clean_serial(serial), "sides": sides, "reference": reference(), "lines": lines, "calls": CALLS}


def problems() -> list[dict]:
    """Every part called something other than OK, on every board."""
    des = design()
    line = {r: ln for ln in des["lines"] for r in ln["refs"]}
    out = []
    for b in boards():
        for ref, c in load_review(b["serial"]).items():
            if c["call"] != "ok":
                ln = line.get(ref, {})
                out.append({"serial": b["serial"], "ref": ref, "value": ln.get("value", ""), "description": ln.get("description", ""),
                            "call": CALLS.get(c["call"], c["call"]), "note": c.get("note", ""), "date": c.get("date", "")})
    return out


def problems_csv() -> bytes:
    f = io.StringIO()
    w = csv.DictWriter(f, ["serial", "ref", "value", "description", "call", "note", "date"])
    w.writeheader()
    w.writerows(problems())
    return f.getvalue().encode()
