"""This station's own record of every board it has tested, one JSON file per serial.

The HWDB is the master copy. These files let the GUI list boards waiting for a retest
and recently tested boards (the HWDB can't list boards by their latest result), show a
board's history when the HWDB can't be reached, and spot a SoM or EEPROM that has
turned up on a second board. Records are only ever added to: a retest adds a run and a
repair adds a repair, and nothing earlier is changed.
"""

import fnmatch
import json
import re
from datetime import datetime
from pathlib import Path

from loguru import logger as lg

from ptctestsuite.config import parameters
from ptctestsuite.ui.base import format_value, step_title, Step
from ptctestsuite.utils.qc_result import qc_result


def _folder() -> Path:
    p = Path(parameters.board_records_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p

def _path(serial: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", serial).strip("._") or "board"
    return _folder() / f"{safe}.json"

def load(serial: str) -> dict | None:
    p = _path(serial)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        lg.error(f"Can't read the station record for {serial}: {e}")
        return None
    return data if data.get("serial") == serial else None

def _save(data: dict) -> None:
    p = _path(data["serial"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    tmp.replace(p)   # never leaves a half-written record

def _blank(serial: str) -> dict:
    return {"serial": serial, "part_id": None, "runs": [], "repairs": []}


def _acceptance(limits, unit) -> str:
    if not limits:
        return ""
    return Step("x", "x", limits=tuple(limits), unit=unit).acceptance or ""


def step_results(record) -> dict:
    """Every step's result in a form that can be shown later: {key: {title, result, value, accept}}."""
    out = {}
    for key, t in record.test_status.items():
        r = t["result"]
        out[key] = {"title": step_title(key), "result": r.name if isinstance(r, qc_result) else str(r),
                    "value": format_value(t.get("value"), t.get("unit")),
                    "accept": _acceptance(t.get("limits"), t.get("unit"))}
    return out


def save_run(record, part_id: str | None, uploaded: bool) -> dict:
    """Adds a finished run to the board's record and returns the run entry."""
    data = load(record.serial_number) or _blank(record.serial_number)
    if part_id:
        data["part_id"] = part_id
    run = {
        "n": record.run_number, "type": record.run_type, "follows_run": record.follows_run,
        "after_repair": record.after_repair, "retest_reason": record.retest_reason,
        "date": record.test_datetime.strftime("%Y-%m-%d %H:%M"), "tester": record.tester_name,
        "overall": record.overall_result.name, "som_serial": record.som_serial,
        "eeprom_serial": record.eeprom_serial, "photos": dict(record.photos), "notes": record.tester_notes,
        "results": step_results(record), "uploaded": uploaded,
    }
    data["runs"] = [r for r in data["runs"] if r.get("n") != run["n"]] + [run]
    _save(data)
    return run


def save_repair(serial: str, repair: dict, part_id: str | None, uploaded: bool) -> None:
    data = load(serial) or _blank(serial)
    if part_id:
        data["part_id"] = part_id
    entry = dict(repair, uploaded=uploaded)
    data["repairs"] = [r for r in data["repairs"] if r.get("n") != entry["n"]] + [entry]
    _save(data)


def set_part_id(serial: str, part_id: str) -> None:
    data = load(serial) or _blank(serial)
    if data.get("part_id") != part_id:
        data["part_id"] = part_id
        _save(data)


# ---- lists and search -----------------------------------------------------------

def _all() -> list[dict]:
    out = []
    for p in sorted(_folder().glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("serial"):
            out.append(d)
    return out

def latest_run(data: dict) -> dict | None:
    return max(data.get("runs") or [], key=lambda r: r.get("n") or 0, default=None)

def summary(data: dict) -> dict:
    """One line about a board for the lookup lists."""
    run = latest_run(data)
    failed = [v["title"] for v in (run or {}).get("results", {}).values() if v["result"] in ("FAIL", "ERROR")]
    last_repair = max(data.get("repairs") or [], key=lambda r: r.get("n") or 0, default=None)
    repaired_since = bool(run and last_repair and last_repair.get("after_run") == run.get("n"))
    return {"serial": data["serial"], "result": run["overall"] if run else "NONE",
            "date": run["date"] if run else "", "run": run["n"] if run else 0,
            "failed": failed, "repaired_since": repaired_since}

def waiting_for_retest() -> list[dict]:
    """Boards whose latest run didn't pass, or that were repaired since it, oldest first."""
    rows = [summary(d) for d in _all()]
    return sorted([r for r in rows if r["result"] in ("FAIL", "ERROR") or r["repaired_since"]], key=lambda r: r["date"])

def recent(n: int = 8) -> list[dict]:
    rows = [summary(d) for d in _all() if d.get("runs")]
    return sorted(rows, key=lambda r: r["date"], reverse=True)[:n]

def search(pattern: str) -> list[dict]:
    """Serials matching pattern, where * matches any part. Without *, matches anywhere in the serial."""
    pat = pattern.strip()
    if not pat:
        return []
    if "*" not in pat and "?" not in pat:
        pat = f"*{pat}*"
    rows = [summary(d) for d in _all() if fnmatch.fnmatch(d["serial"].upper(), pat.upper())]
    return sorted(rows, key=lambda r: r["serial"])


# ---- serials that should only be on one board -----------------------------------

def _boards_with(field: str, value: str, exclude_serial: str) -> list[dict]:
    if not value:
        return []
    hits = []
    for d in _all():
        if d["serial"] == exclude_serial:
            continue
        runs = [r for r in d.get("runs", []) if r.get(field) == value]
        if runs:
            r = max(runs, key=lambda x: x.get("n") or 0)
            hits.append({"serial": d["serial"], "run": r.get("n"), "date": r.get("date")})
    return hits

def boards_with_som(som_serial: str, exclude_serial: str) -> list[dict]:
    return _boards_with("som_serial", som_serial, exclude_serial)

def boards_with_eeprom(eeprom_serial: str, exclude_serial: str) -> list[dict]:
    return _boards_with("eeprom_serial", eeprom_serial, exclude_serial)


def now() -> datetime:
    return datetime.now()
