# QL label designer

Design and print labels on the Brother QL-810W (USB) without Brother's driver, so the feed margin and
label length are whatever we send. Stand-alone for now; meant to be called from PTC later.

    ~/apps/ql-labels.sh                       designer at http://localhost:8097
    ~/apps/ql-labels.sh serve --host 0.0.0.0  also reachable from the network
    ~/apps/ql-labels.sh print NAME --set serial=PTC-00123 [--copies 2] [--margin 0] [--cut end]
    ~/apps/ql-labels.sh print NAME --csv serials.csv        (header row = field names)
    ~/apps/ql-labels.sh calibrate 10 6 4 3 --margin 0       test labels at those lengths
    ~/apps/ql-labels.sh status
    ~/apps/ql-labels.sh --dry-run ...         write jobs to ~/ql-labels-data/dry-run/ instead

- `qllabel/printer.py`  raster protocol (ESC i z / M / A / K / d, 90-byte lines) and status replies, on /dev/usb/lpN.
- `qllabel/render.py`   templates -> 300 dpi bitmaps: text, graphics (PNG; `assets/` are built in), boxes, lines and
  19 symbologies (DataMatrix, QR, Micro QR, rMQR, Aztec, PDF417, Code 128/39/93, EAN/UPC, ITF, Codabar, DataBar),
  optionally with readable text beside the code;
  every barcode is decoded back from the bitmap before printing and the job is refused if one doesn't read.
- `qllabel/station.py`, `server.py`, `static/`  the web designer; `/colors` is the colour designer.
- Batches (saved per template): a number range with preamble/suffix/digits that can carry on numbering, a CSV
  (uploaded on the batch tab, columns mapped to {fields}), or a typed list. `print NAME --batch` prints it.
- Templates: `~/ql-labels-data/templates/*.json`. Positions/sizes in dots (300 dpi; 11.8 dots per mm),
  x along the tape, y across it (306 printable dots on 29 mm tape). `{field}` placeholders in data.
- `/dev/usb/lp0` is group `lp`; the launcher uses `sg lp` when the shell predates joining the group.
- Tests: `.venv/bin/python -m pytest tests` (or run the test functions directly; pytest isn't installed).
