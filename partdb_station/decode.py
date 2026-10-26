"""Find the barcodes in a photo of a label (zxing-cpp: DataMatrix, QR, Code 128 and the rest)."""

import io

import zxingcpp
from PIL import Image, ImageOps

MAX_SIDE = 2000   # big phone and DSLR photos are shrunk first; label codes stay readable


def decode(data: bytes) -> list[dict]:
    """Every code found, biggest (most likely the label's main code) first."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("L")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    found = zxingcpp.read_barcodes(img, text_mode=zxingcpp.TextMode.Plain)
    if not found:
        # small codes on a wide shot: try once more at double size around the middle
        w, h = img.size
        crop = img.crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4)).resize((w, h))
        found = zxingcpp.read_barcodes(crop, text_mode=zxingcpp.TextMode.Plain)
    out = []
    for r in found:
        p = r.position
        xs = [p.top_left.x, p.top_right.x, p.bottom_left.x, p.bottom_right.x]
        ys = [p.top_left.y, p.top_right.y, p.bottom_left.y, p.bottom_right.y]
        out.append({"format": str(r.format), "text": r.text, "area": (max(xs) - min(xs)) * (max(ys) - min(ys))})
    # 2D codes carry the most, so they go ahead of 1D ones of the same size
    out.sort(key=lambda c: (c["format"] in ("Data Matrix", "QR Code", "Micro QR Code", "Aztec"), c["area"]), reverse=True)
    return out
