"""Label templates -> 1-bit images at 300 dpi.

A template is laid out the way you read the label. Normally x runs along the tape (0 .. length) and y
across it (0 .. the printable width, 306 dots on 29 mm tape). With "across": true the text reads across
the tape instead: x is across (0 .. 306) and y along (0 .. length), for short labels like 29 x 10 mm.
"media" names the roll (see printer.MEDIA): "29" = 29 mm continuous (any length), "29x90" = die-cut
(length fixed by the label). All positions and sizes are in dots.
Text and barcode data may contain {field} placeholders, filled from the values passed in."""

import re
from pathlib import Path

import numpy as np
import zxingcpp
from PIL import Image, ImageDraw, ImageFont

from .printer import MEDIA, Media, PrinterError, dots_to_mm, media, mm_to_dots

FONTS = {
    "sans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "sans-bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "narrow": "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Regular.ttf",
    "narrow-bold": "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
    "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "mono-bold": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
}
# element type -> zxing-cpp format. Linear codes are drawn one bar row tall and stretched to "height".
CODES = {
    "datamatrix": "DataMatrix", "qr": "QRCode", "microqr": "MicroQRCode", "rmqr": "RMQRCode",
    "aztec": "Aztec", "pdf417": "PDF417", "compactpdf417": "CompactPDF417",
    "code128": "Code128", "code39": "Code39", "code93": "Code93", "codabar": "Codabar", "itf": "ITF",
    "ean13": "EAN13", "ean8": "EAN8", "upca": "UPCA", "upce": "UPCE",
    "databar": "DataBar", "databarltd": "DataBarLtd", "databarexp": "DataBarExp",
}
LINEAR = {"code128", "code39", "code93", "codabar", "itf", "ean13", "ean8", "upca", "upce",
          "databar", "databarltd", "databarexp"}
TYPES = ["text", *CODES, "image", "box", "line"]
SIBLINGS = {"compactpdf417", "upca", "databar"}
IMAGES = Path.home() / "ql-labels-data" / "images"     # set by Station

DEFAULT = {"name": "untitled", "media": "29", "length_mm": 20.0, "margin": 35, "cut": "each", "cut_every": 1,
           "fields": {"serial": "PTC-00123"}, "elements": []}

_font_cache: dict = {}


def font(name: str, size: int):
    key = (name, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(FONTS.get(name, FONTS["sans"]), max(4, int(size)))
    return _font_cache[key]


def fill(text: str, values: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), str(text or ""))


def fields_in(tpl: dict) -> list[str]:
    seen = []
    for e in tpl.get("elements", []):
        for f in re.findall(r"\{(\w+)\}", str(e.get("data", "")) + str(e.get("hrt_text", ""))):
            if f not in seen:
                seen.append(f)
    return seen


def _ink(mask: np.ndarray) -> Image.Image:
    """bool array (True = black) -> 'L' image, black on white."""
    return Image.fromarray(np.where(mask, 0, 255).astype(np.uint8), "L")


def _text(e: dict, values: dict) -> Image.Image:
    f = font(e.get("font", "sans-bold" if e.get("bold") else "sans"), e.get("size", 40))
    txt = fill(e.get("data", ""), values) or " "
    spacing = int(e.get("spacing", 2))
    tmp = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = tmp.multiline_textbbox((0, 0), txt, font=f, spacing=spacing, align=e.get("align", "left"))
    im = Image.new("L", (max(1, r - l), max(1, b - t)), 255)
    d = ImageDraw.Draw(im)
    d.multiline_text((-l, -t), txt, font=f, fill=0, spacing=spacing, align=e.get("align", "left"))
    return im.point(lambda v: 0 if v < 140 else 255)  # smooth outline, then hard black/white for the head


def symbol(e: dict, values: dict):
    """The zxing-cpp barcode for an element; .text is what a scanner should read (EAN/UPC add the check digit)."""
    data = fill(e.get("data", ""), values)
    if not data:
        raise ValueError("empty barcode data")
    return zxingcpp.create_barcode(data, getattr(zxingcpp.BarcodeFormat, CODES[e["type"]]))


def _code(e: dict, values: dict) -> Image.Image:
    kind = e["type"]
    bc = symbol(e, values)
    m = np.array(bc.to_image(scale=1, add_quiet_zones=False)) < 128
    if kind in LINEAR:
        m = m[:1, :]                                  # one row of bars; height is ours to choose
    mod = max(1, int(e.get("module", 2 if kind in LINEAR else 4)))
    m = np.repeat(np.repeat(m, mod, axis=1), 1 if kind in LINEAR else mod, axis=0)
    if kind in LINEAR:
        m = np.repeat(m, max(1, int(e.get("height", 80))), axis=0)
    im = _ink(m)
    side = e.get("hrt", "none")
    if side not in ("below", "above", "left", "right"):
        return im
    # human-readable text next to the code, as part of the same element
    t = _text({"data": e.get("hrt_text") or "{__data}", "font": e.get("hrt_font", "narrow-bold"),
               "size": e.get("hrt_size", 28), "align": "center" if side in ("below", "above") else "left"},
              {**values, "__data": bc.text})
    gap = int(e.get("hrt_gap", 6))
    if side in ("below", "above"):
        out = Image.new("L", (max(im.width, t.width), im.height + gap + t.height), 255)
        cy, ty = (0, im.height + gap) if side == "below" else (t.height + gap, 0)
        out.paste(im, ((out.width - im.width) // 2, cy))
        out.paste(t, ((out.width - t.width) // 2, ty))
    else:
        out = Image.new("L", (im.width + gap + t.width, max(im.height, t.height)), 255)
        cx, tx = (0, im.width + gap) if side == "right" else (t.width + gap, 0)
        out.paste(im, (cx, (out.height - im.height) // 2))
        out.paste(t, (tx, (out.height - t.height) // 2))
    return out


def _image(e: dict) -> Image.Image:
    """An uploaded graphic, scaled to w x h dots (either 0 = keep the aspect), then made black/white."""
    name = Path(str(e.get("src", ""))).name
    f = IMAGES / name
    if not name or not f.is_file():
        raise ValueError("graphic missing; upload it again")
    src = Image.open(f)
    src.load()
    if src.mode in ("RGBA", "LA", "P"):
        src = src.convert("RGBA")
        bg = Image.new("RGBA", src.size, (255, 255, 255, 255))
        src = Image.alpha_composite(bg, src)
    g = src.convert("L")
    w, h = int(e.get("w", 0)), int(e.get("h", 0))
    if w <= 0 and h <= 0:
        h = 118                                        # 10 mm tall
    if w <= 0:                                         # 0 = follow the other side, keeping the shape
        w = max(1, round(h * g.width / g.height))
    if h <= 0:
        h = max(1, round(w * g.height / g.width))
    g = g.resize((w, h), Image.LANCZOS)
    if e.get("dither"):
        return g.convert("1").convert("L")
    th = int(e.get("threshold", 128))
    return g.point(lambda v: 0 if v < th else 255)


def _box(e: dict) -> Image.Image:
    w, h, s = max(1, int(e.get("w", 100))), max(1, int(e.get("h", 60))), max(1, int(e.get("stroke", 3)))
    im = Image.new("L", (w, h), 255)
    if e.get("filled"):
        im.paste(0, (0, 0, w, h))
    else:
        ImageDraw.Draw(im).rectangle((0, 0, w - 1, h - 1), outline=0, width=s)
    return im


def _line(e: dict) -> Image.Image:
    w, s = max(1, int(e.get("w", 100))), max(1, int(e.get("stroke", 3)))
    return Image.new("L", (w, s), 0)


def element_image(e: dict, values: dict) -> Image.Image:
    t = e.get("type")
    if t == "text":
        im = _text(e, values)
    elif t in CODES:
        im = _code(e, values)
    elif t == "image":
        im = _image(e)
    elif t == "box":
        im = _box(e)
    elif t == "line":
        im = _line(e)
    else:
        raise ValueError(f"unknown element type {t!r}")
    rot = int(e.get("rotate", 0)) % 360
    if rot:
        im = im.rotate(rot, expand=True, fillcolor=255)
    if e.get("invert"):
        im = im.point(lambda v: 255 - v)
    return im


def tpl_media(tpl: dict) -> Media:
    """Templates name their roll in "media"; early ones only had a continuous "tape" width."""
    return media(tpl.get("media") or tpl.get("tape") or "29")


def size(tpl: dict) -> tuple[int, int]:
    m = tpl_media(tpl)
    length = m.printable_len if m.die_cut else max(8, min(mm_to_dots(1000), mm_to_dots(float(tpl.get("length_mm", 20)))))
    width = m.printable
    return (width, length) if tpl.get("across") else (length, width)


def render(tpl: dict, values: dict | None = None) -> tuple[Image.Image, list[dict], list[str]]:
    """-> (label image as read, element boxes in dots, warnings)."""
    values = {**tpl.get("fields", {}), **(values or {})}
    w, h = size(tpl)
    img = Image.new("L", (w, h), 255)
    boxes, warn = [], []
    for e in tpl.get("elements", []):
        x, y = int(e.get("x", 0)), int(e.get("y", 0))
        try:
            im = element_image(e, values)
        except Exception as ex:   # bad barcode data etc.: show it, keep drawing the rest
            warn.append(f"{e.get('type')} {e.get('id', '')}: {ex}")
            boxes.append({"id": e.get("id"), "x": x, "y": y, "w": 40, "h": 40, "bad": True})
            continue
        img.paste(0, (x, y), Image.eval(im, lambda v: 255 - v))   # paint only the black
        boxes.append({"id": e.get("id"), "x": x, "y": y, "w": im.width, "h": im.height})
        if x < 0 or y < 0 or x + im.width > w or y + im.height > h:
            warn.append(f"{e.get('type')} {e.get('id', '')} runs off the printable area")
        if e.get("type") in CODES and int(e.get("module", 2 if e.get("type") in LINEAR else 4)) < 2:
            warn.append(f"{e.get('type')} {e.get('id', '')}: 1-dot modules are unlikely to scan")
    return img.point(lambda v: 0 if v < 128 else 255), boxes, warn


def page(img: Image.Image, flip: bool = False, across: bool = False) -> Image.Image:
    """Label as read -> page for the printer (width across the tape, height along it)."""
    img = img.rotate(180) if flip else img
    return img if across else img.rotate(-90, expand=True)


def verify(img: Image.Image, tpl: dict, values: dict | None = None) -> list[dict]:
    """Decode the rendered bitmap and check each barcode reads back as its data."""
    values = {**tpl.get("fields", {}), **(values or {})}
    pad = Image.new("L", (img.width + 80, img.height + 80), 255)
    pad.paste(img, (40, 40))
    found = [(r.format, r.text) for r in zxingcpp.read_barcodes(pad)]
    out = []
    for e in tpl.get("elements", []):
        if e.get("type") in CODES:
            try:
                want = symbol(e, values).text
            except Exception:
                want = fill(e.get("data", ""), values)
            fmt = getattr(zxingcpp.BarcodeFormat, CODES[e["type"]])
            # Compact PDF417 reads as PDF417, UPC-A as EAN-13, DataBar as DataBar Omni: same text is enough there
            ok = any(t == want and (f == fmt or e["type"] in SIBLINGS) for f, t in found)
            out.append({"id": e.get("id"), "type": e["type"], "data": want, "ok": ok})
    return out


STRIP_DEFAULT = {"on": False, "per": 0, "marks": "edge"}
MAX_PAGE = mm_to_dots(1000)                      # the printer takes pages up to 1 m long


def strips(pages: list[Image.Image], per: int = 0, marks: str = "edge") -> list[Image.Image]:
    """Join printer pages end to end, `per` labels to a piece (0 = as many as fit in 1 m), so labels sit at their
    exact pitch with no feed between them; the printer only adds its ~3 mm feed at each end of a piece.
    Cut marks go on the boundary between labels: "edge" = short ticks at both tape edges, "full" = dashed
    line across, "none"."""
    out = []
    i = 0
    while i < len(pages):
        group = [pages[i]]
        i += 1
        while i < len(pages) and (per <= 0 or len(group) < per) and \
                sum(p.height for p in group) + pages[i].height <= MAX_PAGE:
            group.append(pages[i])
            i += 1
        w = group[0].width
        im = Image.new("L", (w, sum(p.height for p in group)), 255)
        y = 0
        d = ImageDraw.Draw(im)
        for k, p in enumerate(group):
            im.paste(p, (0, y))
            if k and marks == "edge":
                tick = max(6, w // 14)
                d.line((0, y, tick, y), fill=0, width=1)
                d.line((w - 1 - tick, y, w - 1, y), fill=0, width=1)
            elif k and marks == "full":
                for x in range(0, w, 12):
                    d.line((x, y, min(w - 1, x + 5), y), fill=0, width=1)
            y += p.height
        out.append(im)
    return out


def calibration(lengths_mm: list[float], tape="29", note: str = "") -> list[Image.Image]:
    """Test labels: a frame on the exact edge of the image, the length written inside, a tick every mm."""
    pages = []
    h = media(tape).printable
    for L in lengths_mm:
        w = max(8, mm_to_dots(L))
        im = Image.new("L", (w, h), 255)
        d = ImageDraw.Draw(im)
        d.fontmode = "1"
        d.rectangle((0, 0, w - 1, h - 1), outline=0, width=2)
        for i in range(1, int(L) + 1):
            x = mm_to_dots(i)
            if x < w - 2:
                d.line((x, 0, x, 18 if i % 5 else 34), fill=0, width=2)
        txt = f"{L:g}mm"
        f = font("sans-bold", 64)
        while f.size > 10 and d.textlength(txt, font=f) > w - 10:
            f = font("sans-bold", f.size - 4)
        d.text((w / 2, h / 2), txt, font=f, fill=0, anchor="mm")
        if note:                                   # e.g. the margin used, so pieces can be told apart
            fn = font("sans-bold", max(10, f.size * 2 // 3))
            d.text((w / 2, h / 2 + f.size), note, font=fn, fill=0, anchor="mm")
        pages.append(im)
    return pages


def info(tpl: dict) -> dict:
    w, h = size(tpl)
    return {"across": bool(tpl.get("across")), "w": w, "h": h, "w_mm": round(dots_to_mm(w), 2), "h_mm": round(dots_to_mm(h), 2),
            "fields": fields_in(tpl), "media": tpl_media(tpl).id, "die_cut": tpl_media(tpl).die_cut}


def media_list() -> dict:
    """For the page: every roll, plus the whole tape width in dots (printable + unprintable edges)."""
    return {"media": [{"id": m.id, "name": m.name(), "kind": m.kind, "width": m.width, "length": m.length,
                       "printable": m.printable, "printable_len": m.printable_len,
                       "total": round(m.width * 300 / 25.4)} for m in MEDIA.values()]}
