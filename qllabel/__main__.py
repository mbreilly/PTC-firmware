"""python -m qllabel serve | status | print | calibrate   (see README.md)"""

import csv
import json
import sys
from argparse import ArgumentParser
from pathlib import Path

from .printer import PrinterError
from .server import serve
from .station import DATA, Station


def main(argv=None):
    ap = ArgumentParser(prog="qllabel", description="Brother QL label designer and printer")
    ap.add_argument("--data", type=Path, default=DATA, help="templates folder parent (default ~/ql-labels-data)")
    ap.add_argument("--device", help="printer device (default: find the Brother /dev/usb/lpN)")
    ap.add_argument("--dry-run", action="store_true", help="write print jobs to <data>/dry-run/ instead")
    ap.add_argument("--flip", action="store_true", help="turn every label 180 degrees on the tape")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the web designer")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8097)
    sub.add_parser("status", help="ask the printer what is loaded")
    p = sub.add_parser("print", help="print a saved template")
    p.add_argument("template", help="template name or path to a .json file")
    p.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE", help="fill a {field}")
    p.add_argument("--csv", type=Path, help="one label per row; the header row names the fields")
    p.add_argument("--batch", action="store_true", help="print the template's saved batch (number range, CSV or list)")
    p.add_argument("--start", type=int, help="with --batch on a number range: first number")
    p.add_argument("--count", type=int, help="with --batch on a number range: how many")
    p.add_argument("--copies", type=int, default=1)
    p.add_argument("--margin", type=int, help="override the feed margin (dots)")
    p.add_argument("--cut", choices=["each", "end", "none"], help="override when to cut")
    p.add_argument("--strip", type=int, metavar="N", help="print labels end to end, N per piece (0 = all); "
                   "no feed between them, cut marks between labels")
    p.add_argument("--no-strip", action="store_true", help="one piece per label even if the template uses strips")
    p.add_argument("--marks", choices=["edge", "full", "none"], help="cut marks between labels on a strip")
    c = sub.add_parser("calibrate", help="print test labels at given lengths")
    c.add_argument("lengths", nargs="+", type=float, help="label lengths in mm")
    c.add_argument("--margin", type=int, default=35)
    c.add_argument("--cut", choices=["each", "end", "none"], default="each")
    a = ap.parse_args(argv)

    st = Station(a.data, a.device, a.dry_run, a.flip)
    try:
        if a.cmd in (None, "serve"):
            serve(st, getattr(a, "host", "127.0.0.1"), getattr(a, "port", 8097))
        elif a.cmd == "status":
            print(json.dumps(st.status(), indent=1))
        elif a.cmd == "print":
            f = Path(a.template)
            tpl = json.loads(f.read_text()) if f.suffix == ".json" and f.exists() else st.load(a.template)
            base = dict(kv.split("=", 1) for kv in a.set)
            rows = [{**base, **r} for r in csv.DictReader(a.csv.open())] if a.csv else [base]
            over = {k: v for k, v in (("margin", a.margin), ("cut", a.cut)) if v is not None}
            if a.strip is not None or a.no_strip or a.marks:
                over["strip"] = {k: v for k, v in (("on", False if a.no_strip else True if a.strip is not None else None),
                                                   ("per", a.strip), ("marks", a.marks)) if v is not None}
            if a.batch:
                tpl["batch"] = {**(tpl.get("batch") or {}), **{k: v for k, v in (("start", a.start), ("count", a.count)) if v is not None}}
                print(json.dumps(st.print_batch(tpl, a.copies, over)))
            else:
                print(json.dumps(st.print_rows(tpl, rows, a.copies, over)))
        elif a.cmd == "calibrate":
            print(json.dumps(st.calibrate(a.lengths, a.margin, a.cut)))
    except (PrinterError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


sys.exit(main())
