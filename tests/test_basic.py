import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qllabel import render as R
from qllabel.printer import build_job, JobOptions, TAPES, raster_lines
from PIL import Image

TPL = {"tape": 29, "length_mm": 12, "fields": {"serial": "PTC-00123"}, "elements": [
    {"id": "a", "type": "datamatrix", "x": 10, "y": 10, "module": 5, "data": "{serial}"},
    {"id": "b", "type": "text", "x": 100, "y": 20, "size": 36, "data": "{serial}", "rotate": 0},
    {"id": "c", "type": "code128", "x": 10, "y": 150, "module": 2, "height": 80, "data": "{serial}"},
    {"id": "d", "type": "qr", "x": 30, "y": 240, "module": 3, "data": "x"},
]}

def test_render_and_verify():
    img, boxes, warn = R.render(TPL)
    assert img.size == (R.mm_to_dots(12), 306)
    checks = R.verify(img, TPL)
    print(warn, checks)
    ok = {c["id"]: c["ok"] for c in checks}
    assert ok["a"] and ok["d"] and not ok["c"]   # c is cut off by the 12 mm edge

def test_raster_layout():
    img = Image.new("L", (306, 3), 255)
    img.putpixel((0, 0), 0)          # first printable dot
    data = raster_lines(img, 29)
    assert len(data) == 3 * 93 and data[:3] == b"g\x00\x5a"
    line = data[3:93]
    bit = [i for i in range(720) if line[i // 8] >> (7 - i % 8) & 1]
    assert bit == [6 + 306 - 1]      # 29 mm tape: pins 6..311, mirrored (as brother_ql does)

def test_job_shape():
    pages = [R.page(R.render(TPL)[0])] * 2
    job = build_job(pages, JobOptions(margin=0, cut="each"))
    assert job.startswith(b"\x00" * 400 + b"\x1b@")
    assert job.count(b"\x1biz") == 2 and job.endswith(b"\x1a") and job.count(b"\x1bid\x00\x00") == 2
    i = job.index(b"\x1biz")
    assert job[i+3:i+7] == bytes([0xCE, 0x0A, 29, 0]) and int.from_bytes(job[i+7:i+11], "little") == R.mm_to_dots(12)

def test_calibration():
    for p in R.calibration([25, 10, 5, 3]):
        assert p.height == 306
