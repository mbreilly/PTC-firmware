"""The PTC QC procedure as a sequence of steps. Runs with any TesterUI."""

import asyncio
import json
from pathlib import Path

from loguru import logger as lg
from websockets.asyncio.client import connect

from ptctestsuite.config import parameters
from ptctestsuite.config.test_names import test_sequence
from ptctestsuite.config.test_names import prep_checklist
from ptctestsuite.config.test_names import (pre_som_tests, som_boot_tests, alert_led_tests, crate_address_tests,
                                            timing_tests, ethernet_tests, mcu_tests, ripple_full_load,
                                            load_steps, load_tolerance, reception_checks)
from ptctestsuite.ui.base import TesterUI, Step, TestAborted, step_title, format_value
from ptctestsuite.utils import qc_result, qc_record, init_ptc, start_client, manual_test
from ptctestsuite.utils.qc_board import qc_board_handler
from ptctestsuite.utils.photos import save_board_photo
from ptctestsuite.utils import board_records
from ptctestsuite.utils.reception import reception_record, shipment_types, already_recorded, save_locally

renewal_needed = asyncio.Event()

async def token_renew_signal():
    while True:
        await asyncio.sleep(parameters.token_renewal_interval)
        renewal_needed.set()

async def renew_token_if_needed():
    from ptctestsuite.utils.hwdb import renew_token
    if renewal_needed.is_set():
        await renew_token()
        renewal_needed.clear()


async def check_hwdb(ui: TesterUI) -> bool:
    """Tells the tester before the run starts if the HWDB can't be reached, so they
    know the results won't upload. They can carry on and upload the saved results later."""
    from ptctestsuite.utils.hwdb import check_connection, HwdbError
    ui.status("Checking the HWDB connection…")
    try:
        await check_connection()
    except HwdbError as e:
        lg.error(f"HWDB connection check failed: {e}")
        if not await ui.confirm("Can't reach the HWDB",
                                f"{e} You can still run the test. The results will be saved on this computer, "
                                "but they won't be uploaded.",
                                yes="Continue without the HWDB", no="Stop"):
            raise TestAborted()
        return False
    ui.status("Connected to the HWDB.")
    return True


# ---- the plan: every step in order, for the GUI step list ---------------------

def _auto(key, section, prompt, group, limits=None, unit=None) -> Step:
    return Step(key=key, title=step_title(key), section=section, prompt=prompt, group=group, kind="auto",
                limits=limits, unit=unit)

STEP_SOM_SERIAL = Step("som_serial", "Scan SoM serial", "4.3.2",
                       "Scan the Data Matrix code on the Enclustra SoM label.", "SoM and boot", kind="scan")
STEP_AMBIENT = Step("ambient_temperature", "Room temperature", "4.5.1",
                    "Enter the room temperature. The board temperature sensors are compared with it.",
                    "SoM and boot", kind="number", unit="°C")
STEP_BATCH = Step("batch_number", "Batch number", "4.1", "Enter the production batch number, if there is one.",
                  "Shipment", kind="scan")
STEP_PHOTO_FRONT = Step("photo_front", "Front photo", "4.1.3",
                        "Put the board front side up under the camera, line it up with the ghost image and "
                        "take the photo. You can choose an image file instead.", "Board photos", kind="photo", how=[
    "Take the PTC out of the test stand, if it’s in. Wear your ESD strap.",
    "Lay it on the mat under the camera, front side up (heatsinks and DC-DC converters), with the D-sub connector and "
    "SFP cages at the top. The SoM isn’t fitted yet.",
    "Move the board until its edges, connectors and mounting holes sit under the ghost outline. Use the Ghost "
    "slider to fade it in and out.",
    "Check there’s no glare on the chips and the serial label is readable.",
    "Press Take photo, or Space. Look at it and press Retake if it’s blurry or out of line.",
    "No ghost yet? This is the first board. If the photo is well lined up, leave “Save as the ghost” ticked so the "
    "next boards line up to it.",
    "Took the photo with another camera? Use Choose file instead."])
STEP_PHOTO_BACK = Step("photo_back", "Back photo", "4.1.3",
                       "Turn the board over, line it up with the ghost image and take the photo.",
                       "Board photos", kind="photo", how=[
    "Turn the board over top to bottom, so the D-sub connector and SFP cages end up at the bottom. Don’t move the "
    "camera or lights.",
    "Line it up with the back ghost the same way.",
    "Press Take photo, check it, and retake if needed.",
    "No back ghost yet? Leave “Save as the ghost” ticked on a good photo."])
def _orient_step(side: str) -> Step:
    return Step(f"orientation_{side}", f"{side.capitalize()} orientation check", "4.1.3",
                f"The program checked that the polarised parts on the {side} are the right way round. Confirm any "
                "it flagged.", "Board photos", kind="inspect", how=[
        "Green boxes look right. Red ones look reversed and orange ones don’t match the reference: answer each "
        "flagged part.",
        "Compare the two closeups: the known-good reference on the left, this board on the right. Look at the band "
        "on capacitors and diodes and the pin 1 dot or marking on ICs.",
        "If a part really is reversed, answer Reversed. It’s saved as FAIL so the board goes for repair.",
        "If glare or a blurred photo caused the flag, press Retake photo.",
        "This check helps the visual inspection; it doesn’t replace it."])

STEP_ORIENT = {"front": _orient_step("front"), "back": _orient_step("back")}
STEP_PAGE_POWER = Step("page_power", "Power checks, no SoM", "4.3.1",
                       "With no SoM fitted, take each reading and check each LED. Next test unlocks when all are filled in.",
                       "Power checks, no SoM", kind="page", how=[
    "Power the QC board with no SoM in the PTC.",
    "Read the 48 V current on the supply’s display and measure VP12_LOCAL on the DVM.",
    "For each DC-DC converter set SWT1 to that converter’s position only, measure the voltage at its RIPPLE test "
    "point on the DVM, read its switching period on the scope (AC, 20 mV, 2 µs) and check its WIB LED.",
    "Tab or Enter moves to the next box. A reading outside its limits turns orange: check it, as it’s saved as FAIL."])
STEP_PAGE_SOM = Step("page_som", "SoM and boot", "4.3.2",
                     "Fit the SoM and boot the PTC. Fill in everything on this page; Next test unlocks when it’s complete.",
                     "SoM and boot", kind="page", how=[
    "Power off. Scan the Data Matrix code on the SoM, then fit it, checking the connector keying.",
    "Power on and read the boot current a few seconds later; watch the amber LED on the SoM.",
    "Check the front panel LEDs once it has booted, then log in as root on the serial port (115200 8N1).",
    "Run init 0, power off for 60 s and power on; do this 5 times and count the good boots.",
    "Enter the room temperature from the bench thermometer."])
STEP_PAGE_AUTO = Step("page_auto", "Automatic tests", "4.5.1",
                      "These run on the PTC one after another. Watch the OVER TEMP LED while the sensor alert test runs.",
                      "Automatic tests", kind="page", how=[
    "The tests start by themselves and each shows its result as it finishes.",
    "While the sensor alert test runs, watch the OVER TEMP LED on the front panel: it should light red.",
    "When every test has finished, answer the OVER TEMP LED question. Next test then unlocks."])
AUTO_PAGE_KEYS = ["eeprom", "memory", "iv_sensors", "qc_iv_sensors_25pct", "temperature", "alert"]


def _hide(step: Step) -> Step:
    step.hidden = True
    return step


def page_field(step: Step) -> dict:
    """One check on a page, from its Step."""
    kind = {"number": "number", "yesno": "yesno", "judged": "judged"}.get(step.kind, "text")
    question = kind == "yesno"
    return {"key": step.key, "label": step.prompt if question else step.title, "hint": "" if question else step.prompt,
            "kind": kind, "unit": "µs" if step.unit == "us" else step.unit, "limits": step.limits,
            "acceptance": step.acceptance or ("You decide" if kind == "judged" else "")}


def record_page_answers(q: qc_record, tests: list, answers: dict) -> None:
    """Records a page's man_test answers exactly as run_manual_tests would, one result per check."""
    for t in tests:
        with manual_test(**t) as test:
            v = answers[test.test_name]
            if test.limits is not None:
                q.add_result(test.test_name, test.evaluate(float(v)), float(v), test.unit, test.limits)
            elif test.accepts_value:
                q.add_result(test.test_name, qc_result(int(bool(v["ok"]))), _number_or_text(v["value"]), test.unit)
            else:
                q.add_result(test.test_name, qc_result(int(bool(v))), "Yes" if v else "No", test.unit)


def report_page(ui: TesterUI, q: qc_record, step: Step, keys: list[str]) -> None:
    """Puts the page's overall result on its entry in the step list."""
    bad = [k for k in keys if k in q.test_status and q.test_status[k]["result"] != qc_result.PASS]
    worst = qc_result.ERROR if any(q.test_status[k]["result"] == qc_result.ERROR for k in bad) else qc_result.FAIL
    ui.result(step.key, worst if bad else qc_result.PASS,
              f"All {len(keys)} fine" if not bad else f"{len(bad)} of {len(keys)} not fine: " + ", ".join(step_title(k) for k in bad))


STEP_PREP = Step("prep", "Prepare the test stand", "4.2.3",
                 "Seat the PTC on the QC board and power the QC board up. Tick each row as you do it.",
                 "Test stand preparation", kind="checklist", how=[
    "Work down the list. Each row says what to check.",
    "Read the voltage and current on the 24 V supply’s display once the amber LED on the QC board starts blinking.",
    "If the amber LED stays solid or doesn’t light, stop and call a Penn electronics engineer.",
    "The network check runs by itself. If it fails, check the Ethernet cable and give the QC board time to boot, "
    "then press Check again.",
    "Every row and both readings go to the HWDB with the results."])

STEP_RETEST_REASON = Step("retest_reason", "Reason for the retest", "Retest",
                          "Why is this board being retested without a repair? For example: loose cable on the "
                          "QC board, wrong jumper, scope set up wrong.", "Retest", kind="scan")
STEP_NOTES = Step("notes", "Notes and finish", "End", "Add any notes, then finish.", "Finish", kind="notes")

def _load_pct(amps: float) -> int:
    return round(100 * amps / load_steps[-1][1])

def board_plan() -> list[Step]:
    g = "Power checks, no SoM"
    plan = [STEP_PHOTO_FRONT, STEP_ORIENT["front"], STEP_PHOTO_BACK, STEP_ORIENT["back"], STEP_PREP]
    plan += [Step(t["key"], t["title"], "4.2.3", t["detail"], "Test stand preparation", kind="check", hidden=True)
             for t in prep_checklist]
    plan += [STEP_PAGE_POWER] + [_hide(Step.from_man_test(t, g)) for t in pre_som_tests]
    g = "SoM and boot"
    plan += [STEP_PAGE_SOM] + [_hide(s) for s in [STEP_SOM_SERIAL] + [Step.from_man_test(t, g) for t in som_boot_tests]
                                + [STEP_AMBIENT]]
    g = "Automatic tests"
    plan += [STEP_PAGE_AUTO] + [_hide(s) for s in [
        _auto("eeprom", "4.5.2", "Reads the unique serial ID from the EEPROM.", g),
        _auto("memory", "4.5", "Runs fillmem on the PTC to check its memory.", g),
        _auto("iv_sensors", "4.5.1", "Reads the voltage and current sensors on the PTC with all WIB outputs on.", g),
        _auto("qc_iv_sensors_25pct", "4.5.1", "Reads the 6 QC board sensors with every converter at 25% load.", g),
        _auto("temperature", "4.5.1", "Reads the board temperature sensors and compares them with the room.", g),
        _auto("alert", "4.5.1", "Triggers each sensor alert and checks the sensor and FPGA both flag it.", g),
    ] + [Step.from_man_test(t, g) for t in alert_led_tests]]
    g = "DC-DC load test"
    for n in range(6):
        for _, amps in load_steps:
            plan.append(_auto(f"load{n}_{_load_pct(amps)}pct", "4.4.1",
                              f"Sets the QC board load on converter {n} and reads the load current.", g,
                              (amps - load_tolerance, amps + load_tolerance), "A"))
        plan.append(Step.from_man_test(ripple_full_load(n), g))
    g = "Crate address and timing"
    plan += [Step.from_man_test(t, g) for t in crate_address_tests]
    plan += [_auto("timing", "4.5.4", "Reads the timing status register. It should read 0x8, locked.", g),
             _auto("qc_timing_lock", "4.5.4", "Resets the QC board timing endpoint (channel 0). It should read 0x18000000.", g)]
    plan += [Step.from_man_test(t, g) for t in timing_tests]
    g = "Ethernet"
    plan += [
        _auto("gbe_ping", "4.5.5", "Pings the PTC at the address it got from DHCP.", g),
        _auto("gbe_throughput", "4.5.5", f"Sends {parameters.throughput_test_mb} MB to the PTC and measures the speed.",
              g, (parameters.throughput_min_mb_s, None), "MB/s"),
    ] + [Step.from_man_test(t, g) for t in ethernet_tests]
    g = "MCU and EtherCAT"
    plan += [Step.from_man_test(t, g) for t in mcu_tests]
    plan.append(STEP_NOTES)
    return plan

STEP_SHIP_TYPE = Step("product_type", "What’s in this shipment?", "4.1",
                      "Each delivery holds one kind of product. Choose it, and only its checks follow.", "Shipment",
                      kind="choice", how=[
    "Check the packing list and the boxes: front panels, bare PCBs and assembled PCBs arrive separately.",
    "Choose the kind of product in this delivery. Only its checks follow.",
    "If the same purchase order delivers another product later, enter that delivery separately."])


STEP_FP_PHOTO = Step("front_panel_photo", "Front panel photo", "4.1.1",
                     "Put a front panel from this delivery under the camera, line it up with the ghost image and take "
                     "the photo. You can choose an image file instead.", "Front panels", kind="photo", how=[
    "Take one front panel from the delivery. Handle it by the edges; wear gloves if the finish marks easily.",
    "Lay it under the camera outside face up, the same way round every time, and line it up with the ghost outline.",
    "Check there’s no glare on the printing and the openings are sharp, then press Take photo, or Space.",
    "No ghost yet? This is the first delivery. If the photo is well lined up, leave “Save as the ghost” ticked so the "
    "next deliveries line up to it.",
    "The photo is kept on the station and uploaded to this delivery’s HWDB entry."])


def ship_plan(product_type: str | None = None) -> list[Step]:
    """The shipment entry: the product choice, then the checks for that product only."""
    plan = [STEP_SHIP_TYPE]
    if product_type:
        label = shipment_types[product_type]
        plan.append(Step(f"{product_type}_count_vs_po", step_title(f"{product_type}_count_vs_po"), "4.1",
                         f"Count the {label.lower()} received and compare with the purchase order.", label,
                         kind="counts"))
        if product_type == "front_panels":
            plan.append(STEP_FP_PHOTO)
        plan += [Step.from_man_test(t, label) for t in reception_checks[product_type]]
    plan.append(STEP_NOTES)
    return plan


def ship_options() -> list[dict]:
    out = []
    for key, label in shipment_types.items():
        names = []
        for t in reception_checks[key]:   # "Bare PCB vendor certificate" -> "vendor certificate"
            n = step_title(t["test_name"]).removeprefix(label[:-1] + " ")
            names.append(n[0].lower() + n[1:] if not n.split()[0].isupper() else n)
        checks = ["count against the PO"] + (["photo"] if key == "front_panels" else []) + names
        out.append({"key": key, "label": label, "detail": f"{len(checks)} checks: " + ", ".join(checks)})
    return out


# ---- helpers ------------------------------------------------------------------

def watch(record: qc_record, ui: TesterUI) -> None:
    """Tells the UI about every result as it is recorded."""
    add = record.add_result
    def add_and_report(test_name, result, value=None, unit=None, limits=None):
        add(test_name, result, value, unit, limits)
        ui.result(test_name, result, value, unit, limits)
    record.add_result = add_and_report

def _number_or_text(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value

async def run_manual_tests(ui: TesterUI, q: qc_record, tests: list):
    for t in tests:
        step = Step.from_man_test(t)
        with manual_test(**t) as test:
            if test.limits is not None:
                value = await ui.ask_number(step)
                q.add_result(test.test_name, test.evaluate(value), value, test.unit, test.limits)
            elif test.accepts_value:
                ok, value = await ui.ask_judged(step)
                q.add_result(test.test_name, qc_result(int(ok)), _number_or_text(value), test.unit)
            else:
                ok = await ui.ask_yesno(step)   # worded so that Yes is the good answer
                q.add_result(test.test_name, qc_result(int(ok)), "Yes" if ok else "No", test.unit)

async def run_remote_test(ui: TesterUI, plan: dict, ws, q: qc_record | None, test_type: str,
                          test_params: dict | None = None, test_name: str | None = None, limits=None,
                          unit: str | None = None):
    """Runs a test on the PTC client and records its result and measured values.
    Pass q=None for setup steps that should not be recorded."""
    t = {"test_type": test_type, "test_params": test_params or {}, "test_name": test_name or test_type}
    lg.info(f"Running {t['test_name']} with parameters {t['test_params']}")
    if q is not None:
        ui.running(plan.get(t["test_name"]) or _auto(t["test_name"], "", "", ""))
    await ws.send(json.dumps(t))
    msg = json.loads(await ws.recv())
    result = qc_result(int(msg['test_result']))
    values = msg.get('test_values') or None
    lg.info(f"{t['test_name']} -> {result.name}")
    if q is not None:
        q.add_result(msg['test_name'], result, values, unit, limits)
        step = plan.get(msg['test_name']) or _auto(msg['test_name'], "", "", "")
        await ui.after_auto(step, result, format_value(values, unit))
    return result, values

async def run_load_tests(ui, plan, ws, q: qc_record, qc: qc_board_handler):
    """DC-DC converter load test (procedure 4.4.1). Steps each converter through the
    load values and reads the load current from the QC board IV sensors."""
    for n in range(6):
        for value, amps in load_steps:
            name = f"load{n}_{_load_pct(amps)}pct"
            ui.running(plan[name])
            if not await qc.set_load(n, value):
                q.add_result(name, qc_result.ERROR, "The QC board load couldn’t be set")
                await ui.after_auto(plan[name], qc_result.ERROR, "The QC board load couldn’t be set")
                continue
            await run_remote_test(ui, plan, ws, q, "qc_iv_sensors",
                                  {"converters": [n], "i_min": amps - load_tolerance, "i_max": amps + load_tolerance},
                                  test_name=name, limits=(amps - load_tolerance, amps + load_tolerance), unit='A')
        # still at the highest load here
        await run_manual_tests(ui, q, [ripple_full_load(n)])
        await qc.set_load(n, load_steps[0][0])

def _save_unuploaded(record) -> None:
    """Keeps a copy of results that didn't reach the HWDB so they can be uploaded later."""
    with Path(parameters.unuploaded_results_file).open("a") as f:
        f.write(json.dumps(record.gen_hwdb_datasheet(), default=str) + "\n")


# ---- board history: every run and repair of one serial ------------------------

class BoardHistory:
    """What is known about one serial, from the HWDB and this station's records.
    Runs and repairs from both are merged by number; nothing is ever dropped."""

    def __init__(self, serial: str):
        self.serial = serial
        self.part_ids: list[str] = []      # HWDB entries with this serial: should be 0 or 1
        self.local = board_records.load(serial)
        self.hwdb_runs: list[dict] = []
        self.hwdb_repairs: list[dict] = []
        self.hwdb_checked = False
        self.hwdb_error: str | None = None

    @property
    def duplicate(self) -> bool:
        return len(self.part_ids) > 1

    @property
    def part_id(self) -> str | None:
        if len(self.part_ids) == 1:
            return self.part_ids[0]
        if not self.part_ids and not self.hwdb_checked and self.local:
            return self.local.get("part_id")
        return None

    def _merged(self, local: list, hwdb: list) -> list:
        by_n = {r["n"]: r for r in hwdb if r.get("n") is not None}
        by_n.update({r["n"]: r for r in local if r.get("n") is not None})   # this station's copy has more detail
        return [by_n[n] for n in sorted(by_n)]

    @property
    def runs(self) -> list[dict]:
        return self._merged((self.local or {}).get("runs", []), self.hwdb_runs)

    @property
    def repairs(self) -> list[dict]:
        return self._merged((self.local or {}).get("repairs", []), self.hwdb_repairs)

    @property
    def found(self) -> bool:
        return bool(self.runs or self.repairs or self.part_ids)

    @property
    def last_run(self) -> dict | None:
        return self.runs[-1] if self.runs else None

    @property
    def next_run_number(self) -> int:
        # an HWDB entry with no readable runs still means the board was tested once
        return max([r["n"] for r in self.runs] + [1 if self.part_ids else 0]) + 1

    @property
    def next_repair_number(self) -> int:
        return max([r["n"] for r in self.repairs] + [0]) + 1

    def failed_steps(self) -> list[tuple[str, str]]:
        run = self.last_run or {}
        return [(k, v["title"]) for k, v in run.get("results", {}).items() if v["result"] in ("FAIL", "ERROR")]

    def view(self) -> dict:
        """Everything the UI needs to show this board's history, newest first."""
        items = []
        for r in self.runs:
            res = r.get("results", {})
            label = f"Run {r['n']}, " + ("first test" if r.get("type") == "First test" else
                                         f"after repair {r['after_repair']}" if r.get("after_repair") else "retest")
            items.append({"kind": "run", "n": r["n"], "title": label, "date": r.get("date", ""),
                          "who": r.get("tester", ""), "result": r.get("overall", ""),
                          "reason": r.get("retest_reason"), "steps": len(res),
                          "failed": [v for v in res.values() if v["result"] in ("FAIL", "ERROR")],
                          "all": list(res.values()), "photos": r.get("photos") or {},
                          "notes": r.get("notes") or "", "uploaded": r.get("uploaded", True)})
        for p in self.repairs:
            items.append({"kind": "repair", "n": p["n"], "title": f"Repair {p['n']}", "date": p.get("date", ""),
                          "who": p.get("repaired_by", ""), "after_run": p.get("after_run"),
                          "for_steps": p.get("for_steps") or [], "fault": p.get("fault_found", ""),
                          "action": p.get("action_taken", ""), "parts": p.get("parts_replaced", ""),
                          "notes": p.get("notes", ""), "photos": p.get("photos") or [],
                          "uploaded": p.get("uploaded", True)})
        # newest first, in the order things happened: run 1, repairs after run 1, run 2, ...
        items.sort(key=lambda i: (i["n"], 0) if i["kind"] == "run" else (i.get("after_run") or 0, 1), reverse=True)
        last = self.last_run
        runs = [r for r in self.runs]
        return {"serial": self.serial, "part_id": self.part_id, "part_ids": self.part_ids,
                "som": next((r.get("som_serial") for r in reversed(runs) if r.get("som_serial")), None),
                "eeprom": next((r.get("eeprom_serial") for r in reversed(runs) if r.get("eeprom_serial")), None),
                "latest": {"n": last["n"], "result": last.get("overall")} if last else None,
                "runs": len(self.runs), "repairs": len(self.repairs), "items": items,
                "next_run": self.next_run_number,
                "failed": [t for _, t in self.failed_steps()],
                "source": "HWDB and this station" if self.hwdb_checked and not self.hwdb_error else "this station only",
                "warning": self.hwdb_error}


def _run_from_hwdb(i: int, t: dict) -> dict:
    d = t.get("test_data") or {}
    results = {}
    for key, v in (d.get("test_status") or {}).items():
        if isinstance(v, dict):
            results[key] = {"title": step_title(key), "result": str(v.get("result", "")),
                            "value": format_value(v.get("value"), v.get("unit")), "accept": ""}
    return {"n": d.get("Run Number") or i + 1, "type": d.get("Run Type") or "First test",
            "after_repair": d.get("After Repair"), "retest_reason": d.get("Retest Reason"),
            "date": f"{d.get('Test Date', '')} {str(d.get('Test Time', ''))[:5]}".strip(),
            "tester": d.get("Operator Name", ""), "overall": d.get("Overall Result", ""),
            "som_serial": d.get("SoM Serial Number"), "eeprom_serial": d.get("EEPROM Serial ID"),
            "photos": {}, "notes": t.get("comments") or "", "results": results, "uploaded": True}

def _repair_from_hwdb(i: int, t: dict) -> dict:
    d = t.get("test_data") or {}
    return {"n": d.get("Repair Number") or i + 1, "date": d.get("Repair Date", ""),
            "repaired_by": d.get("Repaired By", ""), "after_run": d.get("After Run"),
            "for_steps": d.get("For Steps") or [], "fault_found": d.get("Fault Found", ""),
            "action_taken": d.get("Action Taken", ""), "parts_replaced": d.get("Parts Replaced", ""),
            "photos": d.get("Photos") or [], "notes": t.get("comments") or "", "uploaded": True}


async def load_history(serial: str, use_hwdb: bool) -> BoardHistory:
    h = BoardHistory(serial)
    if not use_hwdb:
        return h
    from ptctestsuite.utils.hwdb import find_parts, get_test_records, HwdbError
    try:
        h.part_ids = [p["part_id"] for p in await find_parts(serial)]
        h.hwdb_checked = True
    except HwdbError as e:
        lg.error(f"Couldn't look up {serial} in the HWDB: {e}")
        h.hwdb_error = f"The HWDB couldn’t be searched for {serial}, so only this station’s records are shown. {e}"
        return h
    if len(h.part_ids) == 1:
        pid = h.part_ids[0]
        board_records.set_part_id(serial, pid) if h.local else None
        try:
            h.hwdb_runs = [_run_from_hwdb(i, t) for i, t in enumerate(await get_test_records(pid, parameters.qc_test_type))]
        except HwdbError as e:
            lg.warning(f"Couldn't read the QC test history of {pid}: {e}")
            h.hwdb_error = f"The HWDB found {serial} ({pid}) but its earlier runs couldn’t be read. {e}"
        try:
            h.hwdb_repairs = [_repair_from_hwdb(i, t) for i, t in
                              enumerate(await get_test_records(pid, parameters.repair_test_type))]
        except HwdbError as e:
            lg.info(f"No repair records read for {pid}: {e}")
    return h


def duplicate_message(h: BoardHistory) -> str:
    return (f"{h.serial} has {len(h.part_ids)} entries in the HWDB ({', '.join(h.part_ids)}). A serial must have "
            "exactly one, or its history ends up split between them. The test can’t go on until someone with HWDB "
            "admin rights removes or merges the extra entry. Then scan the serial again.")


async def record_repair(ui: TesterUI, h: BoardHistory, tester: str, use_hwdb: bool) -> tuple[dict, str]:
    """Asks for a repair record and its close-up photos, saves it here and adds it to the board's HWDB
    entry as its own record. Returns the repair and a sentence saying where it was saved."""
    last = h.last_run
    n = h.next_repair_number
    form = await ui.ask_repair({"serial": h.serial, "n": n, "after_run": last["n"] if last else None,
                                "after_date": last.get("date") if last else "", "repaired_by": tester,
                                "failed": [{"key": k, "title": t} for k, t in h.failed_steps()]})
    titles = dict(h.failed_steps())
    photos = []
    for i in range(parameters.max_repair_photos):
        step = Step(f"repair{n}_photo{i + 1}", f"Repair photo {i + 1}", "Repair",
                    "Take a close-up of the defect or the repair. Press Done when you have no more photos.",
                    "Repair", kind="photo")
        photo = await ui.ask_photo(step, "closeup", optional=True)
        if photo is None:
            break
        path = save_board_photo(f"{h.serial}-repair{n}", photo)
        photos.append((path.name, photo))
    repair = {"n": n, "date": board_records.now().strftime("%Y-%m-%d %H:%M"),
              "repaired_by": form["repaired_by"].strip(), "after_run": last["n"] if last else None,
              "for_steps": [titles.get(k, k) for k in form.get("for_steps", [])],
              "fault_found": form.get("fault_found", "").strip(), "action_taken": form.get("action_taken", "").strip(),
              "parts_replaced": form.get("parts_replaced", "").strip(), "notes": form.get("notes", "").strip(),
              "photos": [name for name, _ in photos]}
    uploaded, where = False, "on this station only (HWDB upload is off)"
    if use_hwdb and h.part_id:
        from ptctestsuite.utils.hwdb import upload_repair_record, upload_ptc_image, HwdbError
        try:
            ui.status(f"Adding repair {n} to {h.serial} in the HWDB…")
            await upload_repair_record(h.part_id, repair)
            for i, (name, p) in enumerate(photos, 1):
                await upload_ptc_image(h.part_id, p.data, filename=name, comments=f"Repair {n}, close-up {i}",
                                       mime=p.mime)
            uploaded, where = True, f"in the HWDB on {h.part_id} and on this station"
        except HwdbError as e:
            lg.exception(e)
            where = (f"on this station only, because the HWDB upload failed: {e} If the HWDB says the "
                     f"{parameters.repair_test_type} test type doesn’t exist, it has to be added to the PTC component "
                     "type by an HWDB admin")
    elif use_hwdb:
        where = "on this station only, because this board has no HWDB entry yet"
    board_records.save_repair(h.serial, repair, h.part_id, uploaded)
    return repair, where


# ---- board photos and the orientation check -------------------------------------

async def take_and_check_photo(ui: TesterUI, q: qc_record, side: str, step: Step):
    """Takes one board photo and checks its polarised parts against the reference for that side.
    Returns the photo and the orientation check image (None if the check isn't set up)."""
    from ptctestsuite.utils import inspection
    key = STEP_ORIENT[side].key
    while True:
        photo = await ui.ask_photo(step, side)
        if not inspection.is_set_up(side):
            ui.skipped([key])
            lg.info(f"No orientation reference for the {side} yet; check skipped")
            return photo, None
        ui.status(f"Checking the parts on the {side}…")
        result = await asyncio.to_thread(inspection.inspect, side, photo.data)
        answer = await ui.ask_inspection(STEP_ORIENT[side], result)
        if answer.get("retake"):
            continue
        break
    if not result.aligned:
        q.add_result(key, qc_result.ERROR, {"checked": 0, "not_checked": result.message})
        return photo, None
    answers = answer.get("answers") or {}
    reversed_ = [r.ref for r in result.flagged if answers.get(r.ref) != "correct"]
    confirmed = [r.ref for r in result.flagged if answers.get(r.ref) == "correct"]
    q.add_result(key, qc_result.FAIL if reversed_ else qc_result.PASS,
                 {"checked": len(result.results), "reversed": reversed_, "flagged_but_correct": confirmed})
    return photo, inspection.overlay_from(result, answers)


# ---- test stand checklist ------------------------------------------------------

async def check_qc_board_network(debug: bool) -> dict:
    """Whether the QC board answers on its SSH port, which is how the program talks to it."""
    if debug:
        return {"ok": True, "detail": "Not checked in debug mode."}
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(parameters.qc_ip, 22),
                                           parameters.qc_board_network_timeout)
        writer.close()
        return {"ok": True, "detail": f"Answered at {parameters.qc_ip}."}
    except (OSError, asyncio.TimeoutError):
        return {"ok": False, "detail": f"No answer from {parameters.qc_ip}. Check the Ethernet cable and give the QC "
                                       "board time to finish booting, then press Check again."}


async def run_prep_checklist(ui: TesterUI, q: qc_record, debug: bool) -> None:
    """Procedure 4.2.3. Every row is saved under its own key; the QC board supply voltage and
    current are checked against qc_board_supply_v_limits and qc_board_current_ma_limits."""
    network = await check_qc_board_network(debug)
    answer = None
    while True:
        answer = await ui.ask_checklist(STEP_PREP, prep_checklist, network, answer)
        if not answer.get("recheck"):
            break
        network = await check_qc_board_network(debug)
    v_lo, v_hi = parameters.qc_board_supply_v_limits
    i_lo, i_hi = parameters.qc_board_current_ma_limits
    all_ok = True
    for item in prep_checklist:
        key, kind = item["key"], item.get("kind")
        if kind == "network":
            ok = network["ok"]
            q.add_result(key, qc_result(int(ok)), network["detail"])
        elif kind == "power":
            volts, milliamps = float(answer["voltage"]), float(answer["current"])
            ok = v_lo <= volts <= v_hi and i_lo <= milliamps <= i_hi
            q.add_result(key, qc_result(int(ok)), {"voltage_v": volts, "current_ma": milliamps})
        else:
            ok = bool(answer["ticks"].get(key))
            q.add_result(key, qc_result(int(ok)), "Yes" if ok else "No")
        all_ok = all_ok and ok
    ui.result(STEP_PREP.key, qc_result(int(all_ok)), f"{float(answer['voltage']):g} V, {float(answer['current']):g} mA")


# ---- board test ---------------------------------------------------------------

async def run_ptc_test(ui: TesterUI, entry: dict, debug: bool = False, disable_hwdb: bool = False,
                       preset: str | None = None):
    """One run of the board test. If the serial was tested before, the run is added to that board as
    the next run number (after an optional repair record); nothing from earlier runs is changed.
    preset skips the "tested before" question: "retest", "repair" (repair, then retest) or "repair_only"."""
    serial = entry["serial"].strip()
    if not disable_hwdb:
        ui.status("Renewing the HWDB token…")
        await renew_token_if_needed()

    q = qc_record(serial, entry["tester"])
    watch(q, ui)
    plan_list = board_plan()
    plan = {s.key: s for s in plan_list}
    ui.begin("board", q.serial_number, q.tester_name, plan_list)
    lg.info(f"Starting new PTC Test Session for {q.serial_number}")
    use_hwdb = await check_hwdb(ui) if not disable_hwdb else False

    # one serial, one board: find every earlier run and repair before testing
    ui.status(f"Looking up {serial}…")
    hist = await load_history(serial, use_hwdb)
    if hist.duplicate:
        await ui.stopped(duplicate_message(hist), title=f"{serial} has {len(hist.part_ids)} entries in the HWDB")
        return
    if hist.hwdb_error and not await ui.confirm(
            "Earlier runs couldn’t be checked", f"{hist.hwdb_error} Carry on with the test?",
            yes="Carry on", no="Stop"):
        raise TestAborted()
    retake_photos = True
    if hist.found:
        choice = preset or await ui.ask_retest_choice(hist.view())
        if choice == "cancel":
            return
        last = hist.last_run
        q.run_number = hist.next_run_number
        q.follows_run = last["n"] if last else None
        if choice in ("repair", "repair_only"):
            repair, where = await record_repair(ui, hist, q.tester_name, use_hwdb)
            if choice == "repair_only":
                await ui.stopped(f"Repair {repair['n']} for {serial} was saved {where}. The board is on the "
                                 "Waiting for a retest list until it’s retested.", title=f"Repair {repair['n']} saved")
                return
            ui.status(f"Repair {repair['n']} saved {where}.")
            q.run_type, q.after_repair = "Retest after repair", repair["n"]
            ui.set_run(f"Run {q.run_number}, after repair {repair['n']}")
        else:
            q.run_type = "Retest"
            q.retest_reason = (await ui.ask_text(STEP_RETEST_REASON)).strip()
            ui.saved("retest_reason", q.retest_reason)
            ui.set_run(f"Run {q.run_number}, retest")
            retake_photos = False   # the board hasn't changed, so the first photos still stand
    elif preset == "repair_only":
        await ui.stopped(f"{serial} hasn’t been tested yet, so there’s nothing to repair against.", title="No runs yet")
        return

    # 4.1.3 photos of the front and back, kept here and uploaded to the HWDB with the results
    photos = {}
    overlays = {}   # orientation check images, uploaded with the photos
    if not retake_photos:
        ui.skipped([STEP_PHOTO_FRONT.key, STEP_PHOTO_BACK.key, STEP_ORIENT["front"].key, STEP_ORIENT["back"].key])
    for side, step in (("front", STEP_PHOTO_FRONT), ("back", STEP_PHOTO_BACK)) if retake_photos else ():
        photo, overlay = await take_and_check_photo(ui, q, side, step)
        path = save_board_photo(q.serial_number, photo)
        photos[side] = photo
        q.photos[side] = path.name
        ui.saved(step.key, path.name)
        if overlay:
            overlays[side] = (path.with_name(path.stem + "-orientation.jpg").name, overlay)
            path.with_name(overlays[side][0]).write_bytes(overlay)

    # 4.2.3 test stand checklist: seat the board and power the QC board up
    await run_prep_checklist(ui, q, debug)

    # 4.3 manual tests, done before the SoM is installed
    if await ui.confirm("Power checks without the SoM",
                        "Run the manual checks without the SoM (4.3)? The SoM must not be installed for these. Skip them if it already is.",
                        yes="Run them", no="Skip, SoM is installed"):
        fields = {f["key"]: f for f in (page_field(Step.from_man_test(t)) for t in pre_som_tests)}
        board_rows = [k for k in fields if not k.startswith(("ripple", "wib"))]
        layout = {"rows": board_rows, "grid": {
            "columns": [{"label": "Output at RIPPLE n", "hint": fields["ripple0"]["acceptance"] + " on the DVM"},
                        {"label": "Switching period", "hint": fields["ripple0_switch_period"]["acceptance"] + " on the scope"},
                        {"label": "WIB n LED on?", "hint": "Yes"}],
            "rows": [{"label": f"DC-DC {n}", "hint": f"SWT1 position {n + 1} only",
                      "keys": [f"ripple{n}", f"ripple{n}_switch_period", f"wib{n}_led"]} for n in range(6)]}}
        answers = await ui.ask_page(STEP_PAGE_POWER, list(fields.values()), layout)
        record_page_answers(q, pre_som_tests, answers)
        report_page(ui, q, STEP_PAGE_POWER, list(fields))
        await ui.instruct("Install the SoM", "Set all DIP switches OFF, power off, install the SoM and put the PTC "
                                             "back on the QC board.")
    else:
        ui.skipped([STEP_PAGE_POWER.key] + [t["test_name"] for t in pre_som_tests])

    # 4.3.2 SoM tests
    # the Enclustra label is a Data Matrix code holding only the 10 digit serial printed beside it
    som_fields = [page_field(STEP_SOM_SERIAL)] + [page_field(Step.from_man_test(t)) for t in som_boot_tests] \
        + [page_field(STEP_AMBIENT)]
    answers, note = None, None
    while True:
        answers = await ui.ask_page(STEP_PAGE_SOM, som_fields, {"rows": [f["key"] for f in som_fields]},
                                    previous=answers, note=note)
        note = None
        q.som_serial = str(answers["som_serial"]).strip()
        if not (q.som_serial.isdigit() and len(q.som_serial) == 10) and not await ui.confirm(
                "Check the SoM serial",
                f"{q.som_serial or 'That'} doesn’t look like a 10 digit Enclustra serial. Keep it anyway?",
                yes="Keep it", no="Scan again"):
            answers.pop("som_serial"); note = "Scan the SoM serial again."
            continue
        # a SoM should only ever be on one PTC: warn (don't block) if it was recorded on another
        others = board_records.boards_with_som(q.som_serial, serial)
        if others:
            o = others[0]
            if not await ui.confirm(
                    "This SoM is already recorded on another board",
                    f"SoM {q.som_serial} was recorded on {o['serial']} in run {o['run']} on {o['date']}. A SoM should "
                    "only be on one PTC. If it was moved to this board on purpose, keep it and the move is noted with "
                    "the results. Otherwise scan the SoM again.",
                    yes="Keep it, the SoM was moved", no="Scan again"):
                answers.pop("som_serial"); note = "Scan the SoM serial again."
                continue
            q.som_moved_from = o["serial"]
        break
    ui.saved("som_serial", q.som_serial + (f", moved from {q.som_moved_from}" if q.som_moved_from else ""))
    record_page_answers(q, som_boot_tests, answers)
    q.ambient_temperature = float(answers["ambient_temperature"])
    ui.saved("ambient_temperature", f"{q.ambient_temperature:g} °C")
    report_page(ui, q, STEP_PAGE_SOM, [t["test_name"] for t in som_boot_tests])

    # try to init the PTC on the default serial port, discovering its DHCP IP
    ui.status("Setting up the PTC network over the serial port…")
    ptc_ip = await init_ptc(debug_run=debug)
    if ptc_ip is None:
        port_step = Step("serial_port", "PTC serial port", "4.2",
                         "The PTC didn’t answer on /dev/ttyUSB0. Check the USB serial cable, then enter the port to try.",
                         kind="scan")
        ptc_serial_port = await ui.ask_text(port_step, default="/dev/ttyUSB1")
        ui.status("Setting up the PTC network over the serial port…")
        ptc_ip = await init_ptc(serial_port=ptc_serial_port, debug_run=debug)
        if ptc_ip is None:
            lg.critical("PTC Network Configuration Failed!")
            await ui.stopped("The PTC network setup failed on both serial ports. Check the serial cable and power, "
                             "then start the test again.")
            return

    server_listening = asyncio.Event()
    client_task = asyncio.create_task(start_client(server_listening, ip_address=ptc_ip, debug_run=debug))
    if not debug:
        try:
            ui.status("Starting the test program on the PTC…")
            lg.info("Waiting for PTC Application to Initialize....")
            await asyncio.wait_for(server_listening.wait(), timeout=20)
        except asyncio.TimeoutError:
            lg.critical("PTC Application failed to start within 20 seconds!")
            client_task.cancel()
            await ui.stopped("The test program on the PTC didn’t start within 20 seconds. Check the network cable "
                             "to the PTC, then start the test again.")
            return

    try:
        qc = qc_board_handler(debug_run=debug)
        async with connect(f"ws://{ptc_ip}:{parameters.ws_port}") as ws:
            ui.begin_page(STEP_PAGE_AUTO, [{"key": k, "label": plan[k].title} for k in AUTO_PAGE_KEYS])
            for t in test_sequence:
                _, values = await run_remote_test(ui, plan, ws, q, t['test_type'], t['test_params'], t.get('test_name'))
                if t['test_type'] == 'eeprom' and values:
                    q.eeprom_serial = values.get('eeprom_serial')
                    others = board_records.boards_with_eeprom(q.eeprom_serial, serial)
                    if others:
                        q.eeprom_also_on = [o["serial"] for o in others]
                        await ui.instruct(
                            "This EEPROM ID is already recorded on another board",
                            f"EEPROM ID {q.eeprom_serial} was also recorded on {', '.join(q.eeprom_also_on)}. Each PTC "
                            "should have its own. The test carries on and this is noted with the results; please tell "
                            "a Penn electronics engineer, as the serial label may be on the wrong board.")

            # 4.5.1 sensors: all converters on at 25% load
            ui.status("Turning on the WIB outputs and setting 25% load…")
            await run_remote_test(ui, plan, ws, None, "wib_power", {"on": True})
            for n in range(6):
                await qc.set_load(n, load_steps[0][0])
            await run_remote_test(ui, plan, ws, q, "iv_sensors")
            await run_remote_test(ui, plan, ws, q, "qc_iv_sensors", test_name="qc_iv_sensors_25pct")
            await run_remote_test(ui, plan, ws, q, "temperature", {"ambient": q.ambient_temperature})
            await run_remote_test(ui, plan, ws, q, "alert")
            led = [page_field(Step.from_man_test(t)) for t in alert_led_tests]
            answers = await ui.ask_page(STEP_PAGE_AUTO, led, {"rows": [f["key"] for f in led], "progress": True})
            record_page_answers(q, alert_led_tests, answers)
            ui.end_page()
            report_page(ui, q, STEP_PAGE_AUTO, AUTO_PAGE_KEYS + [t["test_name"] for t in alert_led_tests])

            # 4.4.1 load test
            await run_load_tests(ui, plan, ws, q, qc)
            ui.status("Turning the loads and WIB outputs off…")
            for n in range(6):
                await qc.load_off(n)
            await run_remote_test(ui, plan, ws, None, "wib_power", {"on": False})

            # 4.5.2 crate address, 4.5.4 timing
            await run_manual_tests(ui, q, crate_address_tests)
            await run_remote_test(ui, plan, ws, q, "timing")
            ui.running(plan["qc_timing_lock"])
            locked, status = await qc.timing_lock()
            r = qc_result.ERROR if locked is None else qc_result.PASS if locked else qc_result.FAIL
            values = {"status": hex(status)} if status is not None else None
            q.add_result("qc_timing_lock", r, values)
            await ui.after_auto(plan["qc_timing_lock"], r, format_value(values) if values else "The QC board didn’t answer")
            await run_manual_tests(ui, q, timing_tests)

        # 4.5.5 Ethernet, from the host
        if debug:
            lg.info("Skipping GbE ping and throughput in debug mode")
            ui.skipped(["gbe_ping", "gbe_throughput"])
        else:
            from ptctestsuite.ptctests import gbe_test, gbe_throughput_test
            ui.running(plan["gbe_ping"])
            with gbe_test(ptc_ip) as t:
                r = await asyncio.to_thread(t.run_test)
                q.add_result("gbe_ping", r, t.values)
                await ui.after_auto(plan["gbe_ping"], r, format_value(t.values))
            ui.running(plan["gbe_throughput"])
            r, rate = await gbe_throughput_test(ptc_ip)
            q.add_result("gbe_throughput", r, rate, "MB/s", (parameters.throughput_min_mb_s, None))
            await ui.after_auto(plan["gbe_throughput"], r, format_value(rate, "MB/s"))
        await run_manual_tests(ui, q, ethernet_tests)

        # 4.5.3 microcontroller and EtherCAT, from the Windows machine
        await run_manual_tests(ui, q, mcu_tests)
    finally:
        client_task.cancel()
        try:
            await client_task
        except asyncio.CancelledError:
            pass

    ui.summary(q)
    notes = await ui.ask_notes()
    if notes:
        q.tester_notes = notes

    if disable_hwdb:
        board_records.save_run(q, hist.part_id, uploaded=False)
        await ui.finish(q, f"HWDB upload is off (--disable-hwdb), so nothing was uploaded. Run {q.run_number} and the "
                           f"photos are saved on this station.", None)
        return
    part_id, results_uploaded, photos_uploaded = hist.part_id, False, []
    try:
        from ptctestsuite.utils.hwdb import upload_ptc_image, upload_test_result, create_hwdb_item, find_parts, HwdbError
        await renew_token_if_needed()
        ui.status("Uploading the results to the HWDB…")
        if part_id is None:
            # check again: the HWDB may have been unreachable when the run started
            existing = await find_parts(serial)
            if len(existing) > 1:
                raise HwdbError(f"{serial} now has {len(existing)} HWDB entries "
                                f"({', '.join(e['part_id'] for e in existing)}). Nothing was added to any of them.")
            if existing:
                part_id = existing[0]["part_id"]
                lg.warning(f"{serial} already had HWDB entry {part_id}; adding run {q.run_number} to it")
            else:
                part_id = (await create_hwdb_item(q))['part_id']
        await upload_test_result(q, part_id)
        results_uploaded = True
        for side, photo in photos.items():
            ui.status(f"Uploading the {side} photo to the HWDB…")
            await upload_ptc_image(part_id, photo.data, filename=q.photos[side],
                                   comments=f"Run {q.run_number}, board photo, {side}", mime=photo.mime)
            if side in overlays:
                await upload_ptc_image(part_id, overlays[side][1], filename=overlays[side][0],
                                       comments=f"Run {q.run_number}, orientation check, {side}", mime="image/jpeg")
            photos_uploaded.append(side)
    except Exception as e:
        lg.exception(e)
        board_records.save_run(q, part_id, uploaded=results_uploaded)
        if not results_uploaded:
            _save_unuploaded(q)
            message = (f"The HWDB upload failed. {e} The results were saved to {parameters.unuploaded_results_file} "
                       f"and the photos are in {parameters.photo_dir}, so they can be uploaded later.")
        else:
            missing = " and ".join(s for s in photos if s not in photos_uploaded)
            message = (f"The results were uploaded (part {part_id}), but the {missing} photo upload failed. {e} "
                       f"The photos are in {parameters.photo_dir}. Add the missing photo to part {part_id} "
                       f"rather than running the test again.")
        await ui.finish(q, message, False)
        return
    board_records.save_run(q, part_id, uploaded=True)
    what = "the results and the front and back photos" if photos else "the results"
    await ui.finish(q, f"Uploaded {what} to the HWDB as run {q.run_number} of {serial} ({part_id}).", True)


# ---- shipment entry -----------------------------------------------------------

async def run_reception_check(ui: TesterUI, entry: dict, disable_hwdb: bool = False):
    """Production shipment entry: the reception checks (procedure 4.1), recorded
    once per delivery instead of for every board."""
    po = entry["po"].strip()
    r = reception_record(po, entry["tester"])
    watch(r, ui)
    ui.begin("ship", po, r.tester_name, ship_plan())
    if not disable_hwdb:
        await renew_token_if_needed()
        await check_hwdb(ui)

    batch = entry.get("batch")
    r.batch_number = (batch if batch is not None else await ui.ask_text(STEP_BATCH)).strip()
    # one kind of product per delivery: choose it, then only its checks
    r.product_type = await ui.ask_choice(STEP_SHIP_TYPE, ship_options())
    label = shipment_types[r.product_type]
    if already_recorded(po, r.product_type, r.batch_number):
        await ui.stopped(f"{label} on purchase order {po}" + (f", batch {r.batch_number}," if r.batch_number else "")
                         + " are already recorded. Nothing to do.", title="Already recorded")
        return
    ui.begin("ship", f"{po}, {label}", r.tester_name, ship_plan(r.product_type))
    ui.saved(STEP_SHIP_TYPE.key, label)
    step = Step(f"{r.product_type}_count_vs_po", step_title(f"{r.product_type}_count_vs_po"), "4.1",
                f"Count the {label.lower()} received and compare with the purchase order.", label, kind="counts")
    ordered, received = await ui.ask_counts(step)
    count_ok = qc_result.PASS if received == ordered else qc_result.FAIL
    r.add_result(f"{r.product_type}_count_vs_po", count_ok, {"ordered": ordered, "received": received})
    panel_photo = None
    if r.product_type == "front_panels":
        # a photo of one front panel from the delivery, lined up with its own ghost like the board photos
        panel_photo = await ui.ask_photo(STEP_FP_PHOTO, "front_panel")
        path = save_board_photo(r.hwdb_serial, panel_photo)
        r.photos["front_panel"] = path.name
        ui.saved(STEP_FP_PHOTO.key, path.name)
    await run_manual_tests(ui, r, reception_checks[r.product_type])

    notes = await ui.ask_notes()
    if notes:
        r.tester_notes = notes
    ui.summary(r)
    save_locally(r)
    if disable_hwdb:
        await ui.finish(r, "Saved on this computer. HWDB upload is off (--disable-hwdb).", None)
        return
    try:
        from ptctestsuite.utils.hwdb import upload_reception_record
        await renew_token_if_needed()
        ui.status("Uploading the shipment to the HWDB…")
        item = await upload_reception_record(r)
    except Exception as e:
        lg.exception(e)
        await ui.finish(r, f"The HWDB upload failed. {e} The shipment is saved in {parameters.reception_log_file}"
                           + (f" and the photo in {parameters.photo_dir}" if panel_photo else "") + ".", False)
        return
    if panel_photo:
        try:
            from ptctestsuite.utils.hwdb import upload_ptc_image
            ui.status("Uploading the front panel photo to the HWDB…")
            await upload_ptc_image(item["part_id"], panel_photo.data, filename=r.photos["front_panel"],
                                   comments="Front panel photo", mime=panel_photo.mime)
        except Exception as e:
            lg.exception(e)
            await ui.finish(r, f"Saved to the HWDB as {r.hwdb_serial}, but the front panel photo upload failed. {e} "
                               f"The photo is in {parameters.photo_dir}; add it to {item['part_id']} by hand.", False)
            return
        await ui.finish(r, f"Saved to the HWDB as {r.hwdb_serial}, with the front panel photo.", True)
        return
    await ui.finish(r, f"Saved to the HWDB as {r.hwdb_serial}.", True)


# ---- main loop ----------------------------------------------------------------

async def run_lookup(ui: TesterUI, entry: dict, debug: bool = False, disable_hwdb: bool = False):
    """Look up a board by serial (read-only). From its history the tester can start a retest
    or record a repair, which run through the normal board test."""
    query = entry["query"].strip()
    use_hwdb = False
    if not disable_hwdb:
        from ptctestsuite.utils.hwdb import check_connection, HwdbError
        try:
            await renew_token_if_needed()
            await check_connection()
            use_hwdb = True
        except Exception as e:
            lg.warning(f"Lookup without the HWDB: {e}")
    while True:
        if "*" in query or "?" in query:
            rows = board_records.search(query)
            query = await ui.pick_board(query, rows)
            if not query:
                return
            continue
        h = await load_history(query, use_hwdb)
        if not h.found:
            near = board_records.search(query)
            if near:
                query = await ui.pick_board(query, near)
                if not query:
                    return
                continue
            where = ("this station’s records or the HWDB" if use_hwdb else
                     "this station’s records (the HWDB is switched off)" if disable_hwdb else
                     "this station’s records (the HWDB couldn’t be reached)")
            await ui.stopped(f"No board with serial {query} was found in {where}.", title="Board not found")
            return
        if not use_hwdb and h.hwdb_error is None:
            h.hwdb_error = ("HWDB lookup is switched off (--disable-hwdb), so only this station’s records are shown."
                            if disable_hwdb else "The HWDB couldn’t be reached, so only this station’s records are shown.")
        action = await ui.show_board(h.view())
        if action == "retest":
            await run_ptc_test(ui, {"mode": "board", "tester": entry["tester"], "serial": query}, debug, disable_hwdb)
        elif action in ("repair", "repair_only"):
            await run_ptc_test(ui, {"mode": "board", "tester": entry["tester"], "serial": query}, debug, disable_hwdb,
                               preset="repair_only")
        return


async def main_loop(ui: TesterUI, debug: bool = False, disable_hwdb: bool = False):
    renewal_needed.set()  # always renew the token on launch
    renewal_task = asyncio.create_task(token_renew_signal())
    try:
        while True:
            entry = await ui.start()
            if entry["mode"] == "quit":
                break
            try:
                if entry["mode"] == "board":
                    await run_ptc_test(ui, entry, debug=debug, disable_hwdb=disable_hwdb)
                elif entry["mode"] == "lookup":
                    await run_lookup(ui, entry, debug=debug, disable_hwdb=disable_hwdb)
                else:
                    await run_reception_check(ui, entry, disable_hwdb=disable_hwdb)
            except TestAborted:
                lg.warning("Run stopped by the tester. Nothing was uploaded.")
                await ui.stopped("You stopped the test. Nothing was uploaded for this run.")
            except Exception as e:
                lg.exception(e)
                await ui.stopped(f"The test stopped because of an error: {e}. Details are in ptctests.log.")
    finally:
        renewal_task.cancel()
