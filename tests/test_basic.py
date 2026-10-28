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
    job = build_job(pages, JobOptions(media="29", margin=0, cut="each"))
    assert job.startswith(b"\x00" * 400 + b"\x1b@")
    assert job.count(b"\x1biz") == 2 and job.endswith(b"\x1a") and job.count(b"\x1bid\x00\x00") == 2
    i = job.index(b"\x1biz")
    assert job[i+3:i+7] == bytes([0xCE, 0x0A, 29, 0]) and int.from_bytes(job[i+7:i+11], "little") == R.mm_to_dots(12)

def test_calibration():
    for p in R.calibration([25, 10, 5, 3]):
        assert p.height == 306

def test_across():
    t = {"tape": 29, "length_mm": 10, "across": True, "elements": [{"id": "a", "type": "datamatrix", "x": 200, "y": 20, "module": 6, "data": "PTC001"}]}
    img, _, _ = R.render(t)
    assert img.size == (306, R.mm_to_dots(10))          # read across: 306 wide, 10 mm tall
    assert R.page(img, across=True).size == (306, R.mm_to_dots(10))
    assert R.verify(img, t)[0]["ok"]

def test_die_cut():
    t = {"media": "29x90", "elements": [{"id": "a", "type": "qr", "x": 20, "y": 20, "module": 6, "data": "PTC001"}]}
    img, _, _ = R.render(t)
    assert img.size == (991, 306)                          # length fixed by the label, not length_mm
    job = build_job([R.page(img)], JobOptions(media="29x90", margin=35))
    i = job.index(b"\x1biz")
    assert job[i+4:i+7] == bytes([0x0B, 29, 90]) and b"\x1bid\x00\x00" in job   # die-cut type, no margin
    assert R.tpl_media({"tape": 62}).id == "62"            # old templates with only "tape" still work

def test_strips():
    t = {"media": "29", "length_mm": 10, "across": True, "fields": {"num": "001"},
         "elements": [{"id": "a", "type": "datamatrix", "x": 200, "y": 20, "module": 6, "data": "PTC{num}"}]}
    pages = [R.page(R.render(t, {"num": f"{i:03d}"})[0], across=True) for i in range(1, 6)]
    s = R.strips(pages, per=2, marks="edge")
    assert [p.height for p in s] == [236, 236, 118]           # 2 + 2 + 1 labels at exactly 118 dots each
    assert s[0].getpixel((0, 118)) == 0 and s[0].getpixel((150, 118)) == 255   # tick at the edge only
    assert len(R.strips(pages, per=0)) == 1
