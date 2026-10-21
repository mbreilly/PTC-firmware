"""Checks that polarised parts (ICs, tantalum and electrolytic capacitors, diodes, LEDs) are the
right way round in a board photo, by comparing it with a reference photo of a known-good board.

For each side there is a reference photo and a list of parts marked on it, kept in
parameters.inspection_dir/<side>/ (reference.jpg and parts.json). The setup page in the GUI
(/inspection) sets both. A board photo is first lined up with the reference (feature matching and
a homography, so the board can be a little rotated, shifted or closer), then each part's area is
compared with the same part on the reference as placed and turned round. A part that matches the
turned version better is flagged as possibly reversed; one that matches neither is flagged to be
checked. The tester confirms every flagged part.

This is an aid, not a replacement for the procedure's visual inspection. Thresholds are in
parameters (inspection_*) and should be tuned on real boards photographed on the camera stand.
"""

import base64
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import cv2
import numpy as np
from loguru import logger as lg

from ptctestsuite.config import parameters

KINDS = {"tantalum": "Tantalum capacitor", "electrolytic": "Electrolytic capacitor", "diode": "Diode",
         "led": "LED", "ic": "IC (pin 1)", "other": "Other polarised part"}


@dataclass
class Part:
    ref: str            # reference designator, e.g. CT29
    kind: str           # a key of KINDS
    box: list           # [x, y, w, h] on the reference photo, in pixels


@dataclass
class PartResult:
    ref: str
    kind: str
    box: list
    status: str                 # ok, reversed, rotated, check
    score: float                # match with the reference as placed
    best_turn: int              # 0, 90, 180 or 270: the turn that matched best
    turned_score: float
    crops: dict = field(default_factory=dict)   # {"reference": data URL, "board": data URL} for flagged parts


@dataclass
class Inspection:
    side: str
    aligned: bool
    message: str
    results: list = field(default_factory=list)
    overlay: bytes | None = None        # JPEG of the aligned photo with the parts outlined

    @property
    def flagged(self) -> list:
        return [r for r in self.results if r.status != "ok"]

    def summary(self) -> dict:
        return {"checked": len(self.results), "flagged": [r.ref for r in self.flagged],
                "aligned": self.aligned, "message": self.message}


# ---- reference photo and parts list ------------------------------------------------

def _dir(side: str) -> Path:
    return Path(parameters.inspection_dir) / side

def reference_path(side: str) -> Path:
    return _dir(side) / "reference.jpg"

def load_parts(side: str) -> list[Part]:
    p = _dir(side) / "parts.json"
    if not p.is_file():
        return []
    try:
        return [Part(**d) for d in json.loads(p.read_text())]
    except (OSError, ValueError, TypeError) as e:
        lg.error(f"Can't read {p}: {e}")
        return []

def save_parts(side: str, parts: list[dict]) -> list[Part]:
    clean = []
    for d in parts:
        x, y, w, h = (int(round(float(v))) for v in d["box"])
        if w < 4 or h < 4:
            continue
        kind = d.get("kind") if d.get("kind") in KINDS else "other"
        clean.append(Part(str(d.get("ref", "")).strip() or f"part{len(clean) + 1}", kind, [x, y, w, h]))
    _dir(side).mkdir(parents=True, exist_ok=True)
    (_dir(side) / "parts.json").write_text(json.dumps([asdict(p) for p in clean], indent=1))
    lg.info(f"Saved {len(clean)} inspection parts for the {side}")
    return clean

def save_reference(side: str, jpeg_or_png: bytes) -> tuple[int, int]:
    img = cv2.imdecode(np.frombuffer(jpeg_or_png, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("That image couldn’t be read.")
    _dir(side).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(reference_path(side)), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    lg.info(f"Saved a new {side} inspection reference ({img.shape[1]}x{img.shape[0]})")
    return img.shape[1], img.shape[0]

def is_set_up(side: str) -> bool:
    return reference_path(side).is_file() and bool(load_parts(side))


# ---- suggestions -------------------------------------------------------------------

def suggest_tantalums(img: np.ndarray) -> list[dict]:
    """Yellow tantalum capacitor bodies found by colour, as a starting point for the parts list."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (12, 110, 140), (32, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    scale = img.shape[1] / 2576   # tuned on 2576 px wide photos
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in stats[i])
        long, short = max(w, h), min(w, h)
        if 250 * scale ** 2 < a < 3000 * scale ** 2 and 1.2 < long / short < 2.8 and short > 14 * scale \
                and a / (w * h) > 0.55:
            out.append({"ref": "", "kind": "tantalum", "box": [x, y, w, h]})
    return out


# ---- placing the parts from the board design ---------------------------------------

def load_design() -> dict | None:
    p = Path(__file__).parents[1] / "config" / parameters.board_design_file
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def board_to_photo(board_pts, photo_pts):
    """A mapping from board inches to photo pixels through the anchor points: a homography, with the
    error left at each anchor spread smoothly between anchors to follow the camera lens's bending."""
    b, p = np.float32(board_pts), np.float32(photo_pts)
    H, _ = cv2.findHomography(b, p, 0)
    res = p - cv2.perspectiveTransform(b[None], H)[0]

    def apply(pts):
        pts = np.float32(pts).reshape(-1, 2)
        base = cv2.perspectiveTransform(pts[None], H)[0]
        w = 1 / (np.linalg.norm(pts[:, None] - b[None], axis=2) ** 2 + 1e-9)
        return base + (w @ res) / w.sum(1, keepdims=True)
    return apply


def _gold_dots(img) -> np.ndarray:
    """Small round gold pads the size of a fiducial."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (12, 70, 120), (38, 255, 255))
    n, _, st, cen = cv2.connectedComponentsWithStats(m)
    s = img.shape[1] / 2576
    dots = [cen[i] for i in range(1, n) if 60 * s ** 2 < st[i][4] < 280 * s ** 2 and 8 * s < st[i][2] < 20 * s
            and 0.7 < st[i][2] / st[i][3] < 1.4 and st[i][4] / (np.pi * (st[i][2] / 2) ** 2) > 0.6]
    return np.array(dots).reshape(-1, 2)


def fiducial_order(side: str) -> list[dict]:
    """The side's fiducials with the corner of the photo each should be in, for asking the tester to click them."""
    design = load_design()
    layer, sx, sy = parameters.inspection_orientation[side]
    fids = {r: f for r, f in (design or {}).get("fiducials", {}).items() if f["side"] == layer}
    out = []
    for r, f in fids.items():
        px, py = sx * f["x"], sy * f["y"]
        others = [(sx * g["x"], sy * g["y"]) for g in fids.values()]
        left = px <= np.median([o[0] for o in others]); top = py <= np.median([o[1] for o in others])
        out.append({"ref": r, "corner": f"{'top' if top else 'bottom'}-{'left' if left else 'right'}"})
    return sorted(out, key=lambda o: ["top-left", "top-right", "bottom-right", "bottom-left"].index(o["corner"]))


def place_from_design(side: str, img: np.ndarray, clicks: dict | None = None) -> dict:
    """Places every visible polarised part of the design on a photo of one side.
    Finds the four corner fiducials itself (or uses clicks {ref: [x, y]}), adds tantalum capacitors
    near where the design puts them as extra anchors, and returns {"ok", "parts", "message", ...}.
    If the fiducials can't be found it returns ok False and need_fiducials."""
    design = load_design()
    if not design:
        return {"ok": False, "message": "There’s no board design file. Make one with python -m ptctestsuite.design_import."}
    layer, sx, sy = parameters.inspection_orientation[side]
    fids = {r: f for r, f in design["fiducials"].items() if f["side"] == layer}
    if len(fids) < 4:
        return {"ok": False, "message": f"The design has {len(fids)} fiducials on the {side}; four are needed."}
    dots = _gold_dots(img)
    names = list(fids)
    bpos = np.array([[sx * fids[r]["x"], sy * fids[r]["y"]] for r in names])   # as the board lies in the photo
    found, how = {}, "found automatically"
    if clicks:
        how = "from the points you clicked"
        for r, xy in clicks.items():
            xy = np.float32(xy)
            if len(dots):
                d = np.linalg.norm(dots - xy, axis=1)   # snap to the fiducial pad near the click
                found[r] = dots[d.argmin()] if d.min() < img.shape[1] / 80 else xy
            else:
                found[r] = xy
    elif len(dots) >= 4:
        for a, b in ((1, 1), (-1, 1), (1, -1), (-1, -1)):   # the outermost dot in each corner
            found[names[int(np.argmin(a * bpos[:, 0] + b * bpos[:, 1]))]] = dots[int(np.argmin(a * dots[:, 0] + b * dots[:, 1]))]
    B = [[fids[r]["x"], fids[r]["y"]] for r in found]
    P = [list(map(float, found[r])) for r in found]
    # check the four points have the design's shape before trusting them
    ok = len(found) == 4
    if ok:   # each point must be in the corner its fiducial is in, as the board lies in the photo
        centre = np.float32(P).mean(0)
        for f in fiducial_order(side):
            x, y = found[f["ref"]]
            want_top, want_left = f["corner"].startswith("top"), f["corner"].endswith("left")
            ok = ok and (y < centre[1]) == want_top and (x < centre[0]) == want_left
    if ok:
        bq, pq = np.float32(B), np.float32(P)
        span = lambda q: (np.ptp(q[:, 0]), np.ptp(q[:, 1]))
        bw, bh = span(np.abs(bq)); pw, ph = span(pq)
        ok = pw > img.shape[1] * 0.3 and abs((pw / ph) / (bw / bh) - 1) < 0.15
    if not ok:
        return {"ok": False, "need_fiducials": fiducial_order(side),
                "message": "The fiducials couldn’t be found in this photo. Click each one in turn." if not clicks
                else "Those points don’t match the board’s fiducials. Click them again, in the order shown."}
    H, _ = cv2.findHomography(np.float32(B), np.float32(P), 0)
    px_per_in = float(np.linalg.norm(np.float32(P)[0] - np.float32(P)[3]) / np.linalg.norm(np.float32(B)[0] - np.float32(B)[3]))
    tants = [p for p in design["parts"] if p["side"] == layer and p["kind"] == "tantalum"]
    n_tant = 0
    if tants:
        seen = np.array([[q["box"][0] + q["box"][2] / 2, q["box"][1] + q["box"][3] / 2] for q in suggest_tantalums(img)]).reshape(-1, 2)
        if len(seen):
            pred = cv2.perspectiveTransform(np.float32([[p["x"], p["y"]] for p in tants])[None], H)[0]
            for p, pr in zip(tants, pred):
                d = np.linalg.norm(seen - pr, axis=1)
                if d.min() < 0.1 * px_per_in:
                    B.append([p["x"], p["y"]]); P.append(list(map(float, seen[d.argmin()]))); n_tant += 1
    to_px = board_to_photo(B, P)
    parts, skipped = [], []
    H_img, W_img = img.shape[:2]
    for p in design["parts"]:
        if p["side"] != layer:
            continue
        if p.get("hidden"):
            skipped.append({"ref": p["ref"], "why": p["hidden"]})
            continue
        x0, y0, x1, y1 = p["bbox"]
        t = np.radians(p["rot"]); c, s = np.cos(t), np.sin(t); m = -1 if p["mirror"] else 1
        poly = to_px([(p["x"] + c * m * u - s * v, p["y"] + s * m * u + c * v) for u, v in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
        bx0, by0 = np.maximum(poly.min(0), 0); bx1, by1 = np.minimum(poly.max(0), (W_img - 1, H_img - 1))
        w, h = int(bx1 - bx0), int(by1 - by0)
        if min(w, h) < parameters.inspection_min_part_px:
            why = f"{min(w, h)} px across, too small to check"
            if p["kind"] == "led":
                why += "; the LED tests catch a reversed LED, as it won’t light"
            skipped.append({"ref": p["ref"], "why": why})
            continue
        parts.append({"ref": p["ref"], "kind": p["kind"], "box": [int(bx0), int(by0), w, h]})
    # sanity checks: the parts must fit the photo, and the tantalum capacitors must say it's the right side
    big = [q for q in design["parts"] if q["side"] == layer and not q.get("hidden") and q["kind"] != "led"]
    if big and len([q for q in parts if q["kind"] != "led"]) < 0.5 * len(big):
        return {"ok": False, "need_fiducials": fiducial_order(side),
                "message": "The parts didn’t fit on the photo, so the fiducials were probably matched wrongly. "
                           "Click each one in turn."}
    if len(tants) >= 6 and n_tant < len(tants) / 2:
        return {"ok": False, "message": f"Only {n_tant} of the {len(tants)} tantalum capacitors on the {side} are where the "
                                        f"design puts them. Is this a photo of the {side}, the right way round?"}
    if not tants and len(suggest_tantalums(img)) >= 6:
        return {"ok": False, "message": f"This photo shows tantalum capacitors, which are only on the other side. "
                                        f"Is it a photo of the {side}?"}
    anchors = f"the 4 fiducials ({how})" + (f" and {n_tant} tantalum capacitors" if n_tant else "")
    return {"ok": True, "parts": parts, "skipped": skipped, "fiducials": {r: [float(v) for v in found[r]] for r in found},
            "message": f"Placed {len(parts)} parts from the {design['name']} design using {anchors}." + _skipped_text(skipped)}


def _skipped_text(skipped: list) -> str:
    if not skipped:
        return ""
    groups = {}
    for q in skipped:
        reason = q["why"] if "too small" not in q["why"] else "too small to check in this photo" + (
            "; the LED tests catch a reversed LED, as it won’t light" if "LED" in q["why"] else "")
        groups.setdefault(reason, []).append(q["ref"])
    return " Left out: " + "; ".join(f"{', '.join(sorted(refs))} ({why})" for why, refs in groups.items()) + "."


# ---- inspection --------------------------------------------------------------------

def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

def align(photo: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray | None, str]:
    """The photo warped onto the reference, or None and why not."""
    s = min(1.0, parameters.inspection_align_width / ref.shape[1])
    g_ref = cv2.resize(_gray(ref), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    sp = g_ref.shape[1] / photo.shape[1]
    g_ph = cv2.resize(_gray(photo), None, fx=sp, fy=sp, interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(parameters.inspection_features)
    k1, d1 = orb.detectAndCompute(g_ref, None)
    k2, d2 = orb.detectAndCompute(g_ph, None)
    if d1 is None or d2 is None or len(k1) < 50 or len(k2) < 50:
        return None, "The photo has too little detail to line up. Check it’s in focus and well lit."
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d2, d1), key=lambda m: m.distance)[:2000]
    if len(matches) < 40:
        return None, "The photo doesn’t look like the reference. Check it’s the right side of the board."
    src = np.float32([k2[m.queryIdx].pt for m in matches]) / sp
    dst = np.float32([k1[m.trainIdx].pt for m in matches]) / s
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0 / s)
    n_in = int(inl.sum()) if inl is not None else 0
    if H is None or n_in < parameters.inspection_min_matches or n_in / len(matches) < 0.15:
        return None, (f"The photo couldn’t be lined up with the reference ({n_in} matching features). "
                      "Check it’s the right side of the board and lined up with the ghost, then retake it.")
    # reject warps that squash or mirror the board: the stand should only allow small changes
    det = np.linalg.det(H[:2, :2])
    if not 0.6 < det < 1.6:
        return None, "The photo lined up with the reference only by stretching it a lot. Retake it lined up with the ghost."
    return cv2.warpPerspective(photo, H, (ref.shape[1], ref.shape[0])), f"Lined up using {n_in} matching features."


def _crop_url(img, box, pad):
    x, y, w, h = box
    H, W = img.shape[:2]
    c = img[max(0, y - pad):min(H, y + h + pad), max(0, x - pad):min(W, x + w + pad)]
    scale = 180 / max(c.shape[:2])
    c = cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def check_part(aligned, ref, part: Part) -> PartResult:
    x, y, w, h = part.box
    body = _gray(ref[y:y + h, x:x + w])
    m = parameters.inspection_search_px
    H, W = aligned.shape[:2]
    area = _gray(aligned[max(0, y - m):min(H, y + h + m), max(0, x - m):min(W, x + w + m)])

    def score(t):
        if t.shape[0] > area.shape[0] or t.shape[1] > area.shape[1]:
            return -1.0
        return float(cv2.matchTemplate(area, t, cv2.TM_CCOEFF_NORMED).max())

    same = score(body)
    turns = {180: cv2.rotate(body, cv2.ROTATE_180)}
    if part.kind == "ic" and 0.8 < w / h < 1.25:   # square ICs can also go in a quarter turn out
        turns[90] = cv2.rotate(body, cv2.ROTATE_90_CLOCKWISE)
        turns[270] = cv2.rotate(body, cv2.ROTATE_90_COUNTERCLOCKWISE)
    best_turn, turned = max(((t, score(img)) for t, img in turns.items()), key=lambda v: v[1])
    if turned > same + parameters.inspection_reverse_margin:
        status = "reversed" if best_turn == 180 else "rotated"
    elif same < parameters.inspection_min_match:
        status = "check"
    else:
        status = "ok"
    return PartResult(part.ref, part.kind, part.box, status, round(same, 3), best_turn, round(turned, 3))


def inspect(side: str, photo_bytes: bytes) -> Inspection | None:
    """Checks one board photo. None if this side has no reference or parts list yet."""
    if not is_set_up(side):
        return None
    ref = cv2.imread(str(reference_path(side)))
    photo = cv2.imdecode(np.frombuffer(photo_bytes, np.uint8), cv2.IMREAD_COLOR)
    if ref is None or photo is None:
        return Inspection(side, False, "The photo or the reference couldn’t be read.")
    aligned, msg = align(photo, ref)
    if aligned is None:
        return Inspection(side, False, msg)
    results = [check_part(aligned, ref, p) for p in load_parts(side)]
    pad = max(12, int(ref.shape[1] / 120))
    for r in results:
        if r.status != "ok":
            r.crops = {"reference": _crop_url(ref, r.box, pad), "board": _crop_url(aligned, r.box, pad)}
    insp = Inspection(side, True, msg, results, overlay(aligned, results))
    insp._aligned = aligned
    return insp


def overlay_from(insp: Inspection, answers: dict) -> bytes | None:
    """The check image redrawn with the tester's answers (flagged parts confirmed correct turn green)."""
    aligned = getattr(insp, "_aligned", None)
    return overlay(aligned, insp.results, answers) if aligned is not None else insp.overlay


COLOURS = {"ok": (80, 190, 80), "reversed": (60, 60, 230), "rotated": (60, 60, 230), "check": (40, 170, 240)}

def overlay(img, results, answers: dict | None = None, width: int = 1400) -> bytes:
    """A JPEG of the photo with each part outlined: green fine, red reversed, orange to check."""
    s = width / img.shape[1]
    vis = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    t = max(2, int(3 * width / 1400))
    for r in results:
        x, y, w, h = (int(v * s) for v in r.box)
        status = r.status
        if answers and r.ref in answers:
            status = "ok" if answers[r.ref] == "correct" else "reversed"
        cv2.rectangle(vis, (x - 4, y - 4), (x + w + 4, y + h + 4), COLOURS[status], t)
        if r.status != "ok":
            cv2.putText(vis, r.ref, (x, max(12, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOURS[status], 2)
    ok, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()
