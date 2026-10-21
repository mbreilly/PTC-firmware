"""Builds the board design file for the orientation check from the PCB's ODB++ and its BOM.

    python -m ptctestsuite.design_import --odb ptc4a_v1j_odb.tgz --bom PTC_CORE_ENG_BILL_OF_MATERIALS.CSV

It reads every placed part (position, rotation, side, package outline and pin 1) from the ODB++,
decides from the BOM which parts are polarised (ICs, oscillators and crystals, tantalum and
polymer aluminium capacitors, LEDs, Schottky diodes; bidirectional TVS and ESD diodes are not),
and writes them with the board outline and the fiducials to parameters.board_design_file. The
setup page uses this to place the parts to check on each reference photo. Rerun it whenever the
board design changes.
"""

import csv
import json
import re
import tarfile
import tempfile
from argparse import ArgumentParser
from pathlib import Path

from ptctestsuite.config import parameters

# Parts that can't be seen in a board photo, by BOM value: (match, reason)
HIDDEN = [("LTM8064", "under a heatsink")]


def _find_step(root: Path) -> Path:
    for stephdr in root.rglob("stephdr"):
        if (stephdr.parent / "layers" / "comp_+_top" / "components").is_file():
            return stephdr.parent
    raise SystemExit(f"No ODB++ step with component layers found in {root}")


def _records(path: Path):
    for line in path.read_text(encoding="latin-1").splitlines():
        t = line.split(";")[0].split()
        if t:
            yield t


def read_odb(step: Path) -> dict:
    pkgs, cur = [], None
    for t in _records(step / "eda" / "data"):
        if t[0] == "PKG":
            cur = {"name": t[1], "bbox": [float(v) for v in t[3:7]]}
            pkgs.append(cur)
    parts, fiducials = [], {}
    for side in ("top", "bot"):
        c = None
        for t in _records(step / "layers" / f"comp_+_{side}" / "components"):
            if t[0] == "CMP":
                c = {"ref": t[6], "side": side, "x": float(t[2]), "y": float(t[3]), "rot": float(t[4]),
                     "mirror": t[5] == "M", "package": pkgs[int(t[1])]["name"], "bbox": pkgs[int(t[1])]["bbox"],
                     "pins": {}}
                parts.append(c)
                if c["ref"].startswith("FID"):
                    fiducials[c["ref"]] = {"side": side, "x": c["x"], "y": c["y"]}
            elif t[0] == "TOP" and c is not None:
                c["pins"][t[-1]] = [float(t[2]), float(t[3])]
    xs, ys = [], []
    for t in _records(step / "profile"):
        if t[0] in ("OB", "OS"):
            xs.append(float(t[1])); ys.append(float(t[2]))
    return {"parts": parts, "fiducials": fiducials,
            "outline": {"xmin": min(xs), "xmax": max(xs), "ymin": min(ys), "ymax": max(ys)}}


def classify(desc: str, part_type: str) -> str | None:
    d, p = desc.upper(), part_type.upper()
    if "TANT" in d:
        return "tantalum"
    if "ALUM" in d or "POLY" in p:
        return "electrolytic"
    if "LED" in d:
        return "led"
    if "SCHOTTKY" in d or ("DIODE" in d and "TVS" not in d):
        return "diode"
    if d.startswith("IC") or any(k in d for k in ("CONVERTER", "MCU", "SENSOR", "MULTIPLEXER", "OSC", "CRYSTAL")):
        return "ic"
    return None   # passives, connectors, switches, bidirectional TVS/ESD, transistors (can't go in reversed)


def read_bom(path: Path) -> dict:
    out = {}
    with path.open(encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f):
            kind = classify(r.get("Description", ""), r.get("Part Type", ""))
            if not kind:
                continue
            for ref in r["Part Reference"].split(","):
                out[ref.strip()] = {"kind": kind, "value": r.get("Value", "").strip(),
                                    "description": re.sub(r"\s+", " ", r.get("Description", "")).strip()}
    return out


def build(odb: Path, bom: Path, name: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = odb
        if odb.is_file():
            with tarfile.open(odb) as tf:
                tf.extractall(tmp, filter="data")
            root = Path(tmp)
        design = read_odb(_find_step(root))
    pol = read_bom(bom)
    parts = []
    for c in design["parts"]:
        if c["ref"] not in pol:
            continue
        info = pol[c["ref"]]
        pin1 = c["pins"].get("1") or c["pins"].get("A1")
        hidden = next((why for match, why in HIDDEN if match in info["value"]), None)
        parts.append({"ref": c["ref"], "side": c["side"], "x": c["x"], "y": c["y"], "rot": c["rot"],
                      "mirror": c["mirror"], "package": c["package"], "bbox": c["bbox"], "pin1": pin1,
                      "kind": info["kind"], "value": info["value"], "description": info["description"],
                      "hidden": hidden})
    return {"name": name, "units": "inch", "outline": design["outline"], "fiducials": design["fiducials"],
            "parts": sorted(parts, key=lambda p: (p["side"], p["ref"]))}


if __name__ == "__main__":
    ap = ArgumentParser(prog="python -m ptctestsuite.design_import")
    ap.add_argument("--odb", required=True, type=Path, help="ODB++ as a .tgz, or its unpacked folder")
    ap.add_argument("--bom", required=True, type=Path, help="bill of materials CSV")
    ap.add_argument("--name", default=None, help="design name (default: from the ODB++ file name)")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "config" / parameters.board_design_file)
    a = ap.parse_args()
    d = build(a.odb, a.bom, a.name or a.odb.name.split("_odb")[0].split(".")[0])
    a.out.write_text(json.dumps(d, indent=1))
    from collections import Counter
    shown = [p for p in d["parts"] if not p["hidden"]]
    print(f"Wrote {a.out}: {len(d['parts'])} polarised parts "
          f"({', '.join(f'{n} {k}' for k, n in sorted(Counter(p['kind'] for p in d['parts']).items()))}), "
          f"{len(d['parts']) - len(shown)} can't be seen, {len(d['fiducials'])} fiducials.")
