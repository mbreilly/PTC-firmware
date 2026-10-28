"""Serial labels for PTC boards that aren't in the database yet, printed on the Brother QL-810W.

The label itself lives in the QL label app (~/apps/ql_labels, http://localhost:8097), template
"ptc-board-10mm": Penn shield, "UPENN/DUNE PTC Production Board {num}" and a Data Matrix holding
PTC{num}. This module picks the numbers: it proposes the next serials that have no HWDB entry, no
record on this station and haven't been printed before, then asks the label app to print them as one
strip. Printed serials are logged in printed_labels.json so they aren't handed out twice. Nothing is
added to the HWDB here; a board gets its entry when it is first tested.
"""

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from loguru import logger as lg

from ptctestsuite.config import parameters
from ptctestsuite.utils import board_records

LABEL_APP = os.environ.get("QL_LABELS_URL", "http://127.0.0.1:8097")
TEMPLATE = "ptc-board-10mm"
PREFIX, DIGITS = "PTC", 3          # the template's Data Matrix holds PTC{num}, num zero-padded to 3
SERIAL_RE = re.compile(rf"^{PREFIX}(\d+)$")
PRINTED = Path(parameters.board_records_dir).parent / "printed_labels.json"
MAX_COUNT = 100


class LabelError(Exception):
    pass


def serial(n: int) -> str:
    return f"{PREFIX}{n:0{DIGITS}d}"


def num(n: int) -> str:
    return f"{n:0{DIGITS}d}"


def printed() -> dict:
    """{serial: [print dates]} for every label printed from this station."""
    try:
        return json.loads(PRINTED.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _log_printed(serials: list[str]) -> None:
    log = printed()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for s in serials:
        log.setdefault(s, []).append(now)
    tmp = PRINTED.with_suffix(".tmp")
    tmp.write_text(json.dumps(log, indent=1))
    tmp.replace(PRINTED)


def _numbers_in_use() -> tuple[set[int], set[int]]:
    """(numbers with a record on this station, numbers already printed)."""
    local = set()
    for d in board_records._all():
        m = SERIAL_RE.match(str(d.get("serial", "")))
        if m:
            local.add(int(m.group(1)))
    done = {int(m.group(1)) for s in printed() if (m := SERIAL_RE.match(s))}
    return local, done


async def propose(start: int | None, count: int, reprint: bool, hwdb_on: bool) -> dict:
    """The next `count` serials from `start` (default: after the highest one used or printed) that have
    no HWDB entry and no station record, and haven't been printed unless `reprint`."""
    from ptctestsuite.utils.hwdb import find_parts
    count = max(1, min(MAX_COUNT, int(count)))
    local, done = _numbers_in_use()
    highest = max(local | done, default=0)
    n = int(start) if start else highest + 1
    out, skipped, hwdb_error = [], [], None
    while len(out) < count and n < 10 ** DIGITS and len(skipped) < 500:
        s = serial(n)
        why = "tested on this station" if n in local else "already printed" if n in done and not reprint else None
        if not why and hwdb_on and not hwdb_error:
            try:
                if await find_parts(s):
                    why = "in the HWDB"
            except Exception as e:      # HWDB down: say so, still propose from local knowledge
                hwdb_error = f"The HWDB couldn't be searched ({e}), so only this station's records were checked."
                lg.error(hwdb_error)
        if why:
            skipped.append({"serial": s, "why": why})
        else:
            out.append({"serial": s, "num": num(n), "printed_before": n in done})
        n += 1
    return {"serials": out, "skipped": skipped[-20:], "skipped_count": len(skipped), "highest": highest,
            "highest_serial": serial(highest) if highest else None, "hwdb_checked": hwdb_on and not hwdb_error,
            "hwdb_error": hwdb_error, "template": TEMPLATE}


# ---- the QL label app ------------------------------------------------------------------

def _call(path: str, body: dict | None = None, timeout: float = 120) -> dict:
    req = urllib.request.Request(LABEL_APP + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except Exception:
            msg = None
        raise LabelError(msg or f"The label app answered HTTP {e.code}.")
    except (urllib.error.URLError, OSError) as e:
        raise LabelError("The label app isn't running. Start it with ~/apps/ql-labels.sh on the Pi, then try again. "
                         f"({e})")


async def template() -> dict:
    return await asyncio.to_thread(_call, "/api/template?name=" + TEMPLATE)


async def preview_png(n: str) -> bytes:
    import base64
    tpl = await template()
    r = await asyncio.to_thread(_call, "/api/preview", {"template": tpl, "values": {"num": n}})
    return base64.b64decode(r["png"])


async def status() -> dict:
    try:
        return await asyncio.to_thread(_call, "/api/status", None, 10)
    except LabelError as e:
        return {"ok": False, "error": str(e)}


async def print_serials(serials: list[str]) -> dict:
    nums = []
    for s in serials:
        m = SERIAL_RE.match(s)
        if not m:
            raise LabelError(f"{s} isn't a {PREFIX}### serial.")
        nums.append(num(int(m.group(1))))
    if not nums or len(nums) > MAX_COUNT:
        raise LabelError(f"Print 1 to {MAX_COUNT} labels at a time.")
    tpl = await template()
    lg.info(f"Printing PTC labels {serials[0]}..{serials[-1]} ({len(nums)})")
    r = await asyncio.to_thread(_call, "/api/print", {"template": tpl, "rows": [{"num": n} for n in nums]}, 300)
    _log_printed(serials)
    return {**r, "serials": serials}
