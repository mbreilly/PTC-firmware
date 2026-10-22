"""Checks that the dev HWDB behaves the way the retest and lookup code relies on.

    python -m ptctestsuite.hwdb_check

It creates one throwaway board with a serial like HISTORY-CHECK-20261021-153000 on the dev
HWDB (cdbdev) and checks:

  1. Searching by serial finds exactly that board, and a near-miss serial finds nothing.
  2. Two QC Test records posted to the board are both kept in its history, so a retest
     never replaces the first run.
  3. The Repair test type exists on the PTC component type (an HWDB admin has to add it).
  4. A photo can be attached to the board.

It refuses to run against the production HWDB. The throwaway board stays in the dev HWDB;
its serial makes it easy to spot.
"""

import asyncio
import base64
import sys
from datetime import datetime

from ptctestsuite.config import parameters
from ptctestsuite.utils.qc_record import qc_record
from ptctestsuite.utils.qc_result import qc_result
from ptctestsuite.utils import hwdb

TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

results: list[tuple[str, bool | None, str]] = []

def report(name: str, ok: bool | None, detail: str) -> None:
    results.append((name, ok, detail))
    mark = {True: "PASS", False: "FAIL", None: "NOTE"}[ok]
    print(f"[{mark}] {name}: {detail}")


async def main() -> int:
    if "cdbdev" not in hwdb.dune_hwdb_api_path and "--allow-production" not in sys.argv:
        print(f"Refusing to run: {hwdb.dune_hwdb_api_path} is not the dev HWDB (cdbdev). "
              "This check creates a throwaway board.")
        return 2
    print(f"Checking {hwdb.dune_hwdb_api_path}, component type {parameters.ptc_part_type_id}\n")
    try:
        await hwdb.check_connection()
    except hwdb.HwdbError as e:
        print(f"Can't reach the HWDB: {e}")
        return 2

    serial = f"HISTORY-CHECK-{datetime.now():%Y%m%d-%H%M%S}"
    q = qc_record(serial, "hwdb_check")
    q.add_result("hwdb_check_step", qc_result.PASS, 1.0, "V", (0.5, 1.5))

    # 1. one board per serial, and the serial search works
    try:
        part_id = (await hwdb.create_hwdb_item(q))["part_id"]
        report("Create board", True, f"{serial} created as {part_id}")
    except hwdb.HwdbError as e:
        report("Create board", False, str(e))
        return summary()
    found = await hwdb.find_parts(serial)
    report("Serial search finds the board", [p["part_id"] for p in found] == [part_id],
           f"found {[p['part_id'] for p in found]}")
    near = await hwdb.find_parts(serial[:-1])
    report("Near-miss serial finds nothing", near == [], f"{serial[:-1]} found {[p['part_id'] for p in near]}")
    try:
        await hwdb.create_hwdb_item(q)
        report("Second board with the same serial is refused", False, "the program created a duplicate")
    except hwdb.HwdbError as e:
        report("Second board with the same serial is refused", True, str(e))

    # 2. test history: both runs kept
    for n in (1, 2):
        q.run_number, q.run_type = n, "First test" if n == 1 else "Retest"
        q.follows_run = 1 if n == 2 else None
        q.tester_notes = f"hwdb_check run {n}"
        await hwdb.upload_test_result(q, part_id)
    try:
        records = await hwdb.get_test_records(part_id, parameters.qc_test_type)
        runs = [r["test_data"].get("Run Number") for r in records]
        report("Both QC Test records kept in the history", runs == [1, 2],
               f"history=true returned {len(records)} record(s) with Run Numbers {runs}")
    except hwdb.HwdbError as e:
        report("Both QC Test records kept in the history", False, f"couldn't read the history: {e}")
    try:
        plain = await hwdb._request("GET", f"{hwdb.dune_hwdb_api_path}/components/{part_id}/tests/"
                                           f"{parameters.qc_test_type}", "read the latest QC Test")
        data = plain.get("data")
        n_plain = len(data) if isinstance(data, list) else (1 if data else 0)
        report("Without history=true", None, f"the HWDB returns {n_plain} record(s) (expected: just the latest)")
    except hwdb.HwdbError as e:
        report("Without history=true", None, str(e))

    # 3. repair records
    try:
        await hwdb.upload_repair_record(part_id, {"n": 1, "date": f"{datetime.now():%Y-%m-%d %H:%M}",
                                                  "repaired_by": "hwdb_check", "after_run": 1,
                                                  "fault_found": "check only", "action_taken": "check only"})
        reps = await hwdb.get_test_records(part_id, parameters.repair_test_type)
        report(f"'{parameters.repair_test_type}' test type", len(reps) == 1, f"repair posted and read back ({len(reps)})")
    except hwdb.HwdbError as e:
        report(f"'{parameters.repair_test_type}' test type", False,
               f"{e} An HWDB admin needs to add a '{parameters.repair_test_type}' test type to component type "
               f"{parameters.ptc_part_type_id}. Until then repairs are kept on the station only.")

    # 4. photos
    try:
        await hwdb.upload_ptc_image(part_id, TINY_PNG, filename=f"{serial}-check.png",
                                    comments="hwdb_check photo", mime="image/png")
        report("Photo upload", True, "1x1 test image attached")
    except hwdb.HwdbError as e:
        report("Photo upload", False, str(e))
    # vendor certificates are uploaded the same way, as PDF or Excel files
    pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
           b"trailer<</Root 1 0 R>>\n%%EOF\n")
    try:
        await hwdb.upload_ptc_image(part_id, pdf, filename=f"{serial}-certificate.pdf", comments="hwdb_check PDF",
                                    mime="application/pdf")
        report("PDF upload (vendor certificates)", True, "a small PDF attached")
    except hwdb.HwdbError as e:
        report("PDF upload (vendor certificates)", False, f"{e} Certificates would then stay on the station only.")

    print(f"\nThe throwaway board {serial} ({part_id}) stays in the dev HWDB.")
    return summary()


def summary() -> int:
    failed = [r for r in results if r[1] is False]
    print("\nAll checks passed." if not failed else
          f"\n{len(failed)} check(s) failed: " + ", ".join(r[0] for r in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
