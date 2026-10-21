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
