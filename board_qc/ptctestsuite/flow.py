"""The PTC QC procedure as a sequence of steps. Runs with any TesterUI."""

import asyncio
import json
from pathlib import Path

from loguru import logger as lg
from websockets.asyncio.client import connect

from ptctestsuite.config import parameters
from ptctestsuite.config.test_names import test_sequence
from ptctestsuite.config.test_names import (pre_som_tests, som_boot_tests, alert_led_tests, crate_address_tests,
                                            timing_tests, ethernet_tests, mcu_tests, ripple_full_load,
                                            load_steps, load_tolerance, reception_checks)
from ptctestsuite.ui.base import TesterUI, Step, TestAborted, step_title
from ptctestsuite.utils import qc_result, qc_record, init_ptc, start_client, manual_test
from ptctestsuite.utils.qc_board import qc_board_handler
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


async def check_hwdb(ui: TesterUI) -> None:
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
        return
    ui.status("Connected to the HWDB.")


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
STEP_NOTES = Step("notes", "Notes and finish", "End", "Add any notes, then finish.", "Finish", kind="notes")

def _load_pct(amps: float) -> int:
    return round(100 * amps / load_steps[-1][1])

def board_plan() -> list[Step]:
    g = "Power checks, no SoM"
    plan = [Step.from_man_test(t, g) for t in pre_som_tests]
    g = "SoM and boot"
    plan += [STEP_SOM_SERIAL] + [Step.from_man_test(t, g) for t in som_boot_tests] + [STEP_AMBIENT]
    g = "Automatic tests"
    plan += [
        _auto("eeprom", "4.5.2", "Reads the unique serial ID from the EEPROM.", g),
        _auto("memory", "4.5", "Runs fillmem on the PTC to check its memory.", g),
        _auto("iv_sensors", "4.5.1", "Reads the voltage and current sensors on the PTC with all WIB outputs on.", g),
        _auto("qc_iv_sensors_25pct", "4.5.1", "Reads the 6 QC board sensors with every converter at 25% load.", g),
        _auto("temperature", "4.5.1", "Reads the board temperature sensors and compares them with the room.", g),
        _auto("alert", "4.5.1", "Triggers each sensor alert and checks the sensor and FPGA both flag it.", g),
    ] + [Step.from_man_test(t, g) for t in alert_led_tests]
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

def ship_plan() -> list[Step]:
    plan = []
    for shipment_type, label in shipment_types.items():
        plan.append(Step(f"{shipment_type}_count_vs_po", step_title(f"{shipment_type}_count_vs_po"), "4.1",
                         f"Count the {label.lower()} received and compare with the purchase order.", label,
                         kind="counts"))
        plan += [Step.from_man_test(t, label) for t in reception_checks[shipment_type]]
    plan.append(STEP_NOTES)
    return plan


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
                ok = await ui.ask_yesno(step)
                q.add_result(test.test_name, qc_result(int(ok)), None, test.unit)

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
    return result, values

async def run_load_tests(ui, plan, ws, q: qc_record, qc: qc_board_handler):
    """DC-DC converter load test (procedure 4.4.1). Steps each converter through the
    load values and reads the load current from the QC board IV sensors."""
    for n in range(6):
        for value, amps in load_steps:
            name = f"load{n}_{_load_pct(amps)}pct"
            ui.running(plan[name])
            if not await qc.set_load(n, value):
                q.add_result(name, qc_result.ERROR)
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


# ---- board test ---------------------------------------------------------------

async def run_ptc_test(ui: TesterUI, entry: dict, debug: bool = False, disable_hwdb: bool = False):
    if not disable_hwdb:
        ui.status("Renewing the HWDB token…")
        await renew_token_if_needed()

    q = qc_record(entry["serial"].strip(), entry["tester"])
    watch(q, ui)
    plan_list = board_plan()
    plan = {s.key: s for s in plan_list}
    ui.begin("board", q.serial_number, q.tester_name, plan_list)
    lg.info(f"Starting new PTC Test Session for {q.serial_number}")
    if not disable_hwdb:
        await check_hwdb(ui)

    # 4.3 manual tests, done before the SoM is installed
    if await ui.confirm("Power checks without the SoM",
                        "Run the manual checks without the SoM (4.3)? The SoM must not be installed for these. Skip them if it already is.",
                        yes="Run them", no="Skip, SoM is installed"):
        await run_manual_tests(ui, q, pre_som_tests)
        await ui.instruct("Install the SoM", "Set all DIP switches OFF, power off, install the SoM and put the PTC "
                                             "back on the QC board.")
    else:
        ui.skipped([t["test_name"] for t in pre_som_tests])

    # 4.3.2 SoM tests
    # the Enclustra label is a Data Matrix code holding only the 10 digit serial printed beside it
    while True:
        q.som_serial = (await ui.ask_text(STEP_SOM_SERIAL)).strip()
        if q.som_serial.isdigit() and len(q.som_serial) == 10:
            break
        if await ui.confirm("Check the SoM serial",
                            f"{q.som_serial or 'That'} doesn’t look like a 10 digit Enclustra serial. Keep it anyway?",
                            yes="Keep it", no="Scan again"):
            break
    ui.saved("som_serial", q.som_serial)
    await run_manual_tests(ui, q, som_boot_tests)
    q.ambient_temperature = await ui.ask_number(STEP_AMBIENT)
    ui.saved("ambient_temperature", f"{q.ambient_temperature:g} °C")

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
            for t in test_sequence:
                _, values = await run_remote_test(ui, plan, ws, q, t['test_type'], t['test_params'], t.get('test_name'))
                if t['test_type'] == 'eeprom' and values:
                    q.eeprom_serial = values.get('eeprom_serial')

            # 4.5.1 sensors: all converters on at 25% load
            ui.status("Turning on the WIB outputs and setting 25% load…")
            await run_remote_test(ui, plan, ws, None, "wib_power", {"on": True})
            for n in range(6):
                await qc.set_load(n, load_steps[0][0])
            await run_remote_test(ui, plan, ws, q, "iv_sensors")
            await run_remote_test(ui, plan, ws, q, "qc_iv_sensors", test_name="qc_iv_sensors_25pct")
            await run_remote_test(ui, plan, ws, q, "temperature", {"ambient": q.ambient_temperature})
            await run_remote_test(ui, plan, ws, q, "alert")
            await run_manual_tests(ui, q, alert_led_tests)

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
            q.add_result("qc_timing_lock",
                         qc_result.ERROR if locked is None else qc_result.PASS if locked else qc_result.FAIL,
                         {"status": hex(status)} if status is not None else None)
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
            ui.running(plan["gbe_throughput"])
            r, rate = await gbe_throughput_test(ptc_ip)
            q.add_result("gbe_throughput", r, rate, "MB/s", (parameters.throughput_min_mb_s, None))
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
        await ui.finish(q, "HWDB upload is off (--disable-hwdb), so nothing was uploaded.", None)
        return
    try:
        from ptctestsuite.utils.hwdb import upload_ptc_image, upload_test_result, create_hwdb_item
        from ptctestsuite.utils.image_capture import get_board_image
        await renew_token_if_needed()
        ui.status("Uploading the results to the HWDB…")
        r = await create_hwdb_item(q)
        await upload_test_result(q, r['part_id'])
        ui.status("Taking the board photo…")
        board_img = await get_board_image()
        await upload_ptc_image(r['part_id'], board_img)
    except Exception as e:
        lg.exception(e)
        _save_unuploaded(q)
        await ui.finish(q, f"The HWDB upload failed. {e} The results were saved to "
                           f"{parameters.unuploaded_results_file} so they can be uploaded later.", False)
        return
    await ui.finish(q, "Uploaded to the HWDB with the board photo.", True)


# ---- shipment entry -----------------------------------------------------------

async def run_reception_check(ui: TesterUI, entry: dict, disable_hwdb: bool = False):
    """Production shipment entry: the reception checks (procedure 4.1), recorded
    once per delivery instead of for every board."""
    po = entry["po"].strip()
    if already_recorded(po):
        await ui.stopped(f"The shipment for PO {po} is already recorded. Nothing to do.")
        return
    r = reception_record(po, entry["tester"])
    watch(r, ui)
    plan_list = ship_plan()
    ui.begin("ship", po, r.tester_name, plan_list)
    if not disable_hwdb:
        await renew_token_if_needed()
        await check_hwdb(ui)

    batch = entry.get("batch")
    r.batch_number = batch if batch is not None else await ui.ask_text(STEP_BATCH)
    for shipment_type, label in shipment_types.items():
        step = next(s for s in plan_list if s.key == f"{shipment_type}_count_vs_po")
        ordered, received = await ui.ask_counts(step)
        count_ok = qc_result.PASS if received == ordered else qc_result.FAIL
        r.add_result(f"{shipment_type}_count_vs_po", count_ok, {"ordered": ordered, "received": received})
        await run_manual_tests(ui, r, reception_checks[shipment_type])

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
        await upload_reception_record(r)
    except Exception as e:
        lg.exception(e)
        await ui.finish(r, f"The HWDB upload failed. {e} The shipment is saved in {parameters.reception_log_file}.",
                        False)
        return
    await ui.finish(r, f"Saved to the HWDB as {parameters.reception_serial_prefix}{po}.", True)


# ---- main loop ----------------------------------------------------------------

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
