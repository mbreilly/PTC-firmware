import prompt_toolkit as ptk
import asyncio
import json

from loguru import logger as lg

from prompt_toolkit.shortcuts import choice, message_dialog, input_dialog, confirm
from prompt_toolkit.filters import is_done

from ptctestsuite.ptctests import dummy_test
from ptctestsuite.utils import qc_result, qc_record, init_ptc, start_client, async_yesno, manual_test
from websockets.asyncio.client import connect
from ptctestsuite.config import test_sequence
from ptctestsuite.config.test_names import (pre_som_tests, som_boot_tests, alert_led_tests, crate_address_tests,
                                            timing_tests, ethernet_tests, mcu_tests, ripple_full_load,
                                            load_steps, load_tolerance)
from ptctestsuite.ptctests import gbe_test, gbe_throughput_test
from ptctestsuite.utils.qc_board import qc_board_handler
from ptctestsuite.utils.hwdb import upload_ptc_image, upload_test_result, create_hwdb_item, renew_token, upload_reception_record
from ptctestsuite.utils.reception import reception_record, shipment_types, already_recorded, save_locally
from ptctestsuite.config.test_names import reception_checks
from ptctestsuite.utils.image_capture import get_board_image

from argparse import ArgumentParser

from ptctestsuite.config import parameters

renewal_needed = asyncio.Event()

async def token_renew_signal():
    while True:
        await asyncio.sleep(parameters.token_renewal_interval)
        renewal_needed.set()

parser = ArgumentParser()
parser.add_argument('--debug', action='store_true')
parser.add_argument('--disable-hwdb', action='store_true')

args = parser.parse_args()

lg.remove()
lg.add("ptctests.log", rotation='500MB', level="INFO")

# keeping this for the entire run of the script
tester_name = ptk.prompt("Tester Name: ")
# test sequence for automated tests goes here. This is a list of tests and their parameters

# for now, store these here. Can determine later if we want to go
# direct to HWDB, or store them and then upload after verification
test_runs = []

# always renew the to on launch
renewal_needed.set()

async def ask_float(session: ptk.PromptSession, message: str) -> float:
    """Prompts until the tester enters a number."""
    while True:
        ans = await session.prompt_async(message)
        try:
            return float(ans.strip())
        except ValueError:
            print("Please enter a number.")

async def run_manual_tests(session: ptk.PromptSession, q: qc_record, tests: list):
    for t in tests:
        with manual_test(**t) as test:
            if test.limits is not None:
                lo, hi = test.limits
                unit = f" {test.unit}" if test.unit else ""
                value = await ask_float(session, f"{test.message} [{lo}-{hi}{unit}]: ")
                result = test.evaluate(value)
                print(f"  -> {result.name}")
                q.add_result(test.test_name, result, value, test.unit, test.limits)
                continue
            result = await async_yesno(session, test.message)
            test_val = None
            if test.accepts_value:
                unit = f" ({test.unit})" if test.unit else ""
                test_val = await session.prompt_async(f"What was the value of the tested parameter{unit}? ")
            q.add_result(test.test_name, qc_result(int(result)), test_val, test.unit)

async def run_remote_test(ws, q: qc_record | None, test_type: str, test_params: dict | None = None,
                          test_name: str | None = None, limits=None, unit: str | None = None):
    """Runs a test on the PTC client and records its result and measured values.
    Pass q=None for setup steps that should not be recorded."""
    t = {"test_type": test_type, "test_params": test_params or {}, "test_name": test_name or test_type}
    print(f"Running {t['test_name']} with parameters {t['test_params']}")
    lg.info(f"Running {t['test_name']} with parameters {t['test_params']}")
    await ws.send(json.dumps(t))
    msg = json.loads(await ws.recv())
    result = qc_result(int(msg['test_result']))
    values = msg.get('test_values') or None
    print(f"  -> {result.name}")
    if q is not None:
        q.add_result(msg['test_name'], result, values, unit, limits)
    return result, values

async def run_load_tests(ws, session: ptk.PromptSession, q: qc_record, qc: qc_board_handler):
    """DC-DC converter load test (procedure 4.4.1). Steps each converter through the
    load values and reads the load current from the QC board IV sensors."""
    for n in range(6):
        for value, amps in load_steps:
            pct = round(100 * amps / load_steps[-1][1])
            name = f"load{n}_{pct}pct"
            if not await qc.set_load(n, value):
                q.add_result(name, qc_result.ERROR)
                continue
            await run_remote_test(ws, q, "qc_iv_sensors",
                                  {"converters": [n], "i_min": amps - load_tolerance, "i_max": amps + load_tolerance},
                                  test_name=name, limits=(amps - load_tolerance, amps + load_tolerance), unit='A')
        # still at the highest load here
        await run_manual_tests(session, q, [ripple_full_load(n)])
        await qc.set_load(n, load_steps[0][0])

def print_summary(q: qc_record):
    print(f"\n==== {q.serial_number} summary ====")
    for name, t in q.test_status.items():
        value = t['value']
        if isinstance(value, dict):
            value = ", ".join(f"{k}={v}" for k, v in value.items())
        print(f"{t['result'].name:6} {name}" + (f": {value}" if value is not None else ""))
    print(f"Overall: {q.overall_result.name}\n")

async def run_ptc_test():
    global tester_name, test_sequence 
    hwdb_disabled = args.disable_hwdb

    if not hwdb_disabled:
        if renewal_needed.is_set():
            await renew_token()
            renewal_needed.clear()
        
    ptc_ip = "localhost" if args.debug else parameters.ptc_ip
    
    session = ptk.PromptSession()
    ptc_serial = await session.prompt_async("PTC Serial Number: ")
    q = qc_record(ptc_serial, tester_name)
    lg.info(f"Starting new PTC Test Session.")

    # 4.3 manual tests, done before the SoM is installed
    if await async_yesno(session, "Run the manual tests without the SoM (4.3)? Answer n if the SoM is already installed"):
        await run_manual_tests(session, q, pre_som_tests)
        await session.prompt_async("Set all DIP switches OFF, power off, install the SoM and reinsert the PTC. Press Enter when ready.")

    # 4.3.2 SoM tests
    # the Enclustra label is a Data Matrix code holding only the 10 digit serial printed beside it
    while True:
        q.som_serial = (await session.prompt_async("Enclustra SoM Serial Number (scan the code on the SoM label): ")).strip()
        if q.som_serial.isdigit() and len(q.som_serial) == 10:
            break
        if await async_yesno(session, f"'{q.som_serial}' doesn't look like a 10 digit Enclustra serial. Keep it anyway?"):
            break
    await run_manual_tests(session, q, som_boot_tests)
    q.ambient_temperature = await ask_float(session, "Room temperature (C): ")

    # try to init the PTC on the default serial port
    net_status = await init_ptc(debug_run=args.debug)
    if not net_status:
        ptc_serial_port = await session.prompt_async("Connection failed on the default serial port. Enter a different port to attempt connection again: ", default="/dev/ttyUSB1")
        # this is kind of goofy, maybe rework this?
        net_status = await init_ptc(serial_port=ptc_serial_port, debug_run=args.debug)
        if not net_status:
            lg.critical("PTC Network Configuration Failed!")
            return
    
    server_listening = asyncio.Event()
    client_task = asyncio.create_task(start_client(server_listening, debug_run=args.debug))
    # start client task
    if not args.debug:
        try:
            lg.info("Waiting for PTC Application to Initialize....")
            await asyncio.wait_for(server_listening.wait(), timeout=20)
        except asyncio.TimeoutError:
            lg.critical("PTC Application failed to start within 20 seconds!")
            client_task.cancel()

    qc = qc_board_handler(debug_run=args.debug)
    async with connect(f"ws://{ptc_ip}:{parameters.ws_port}") as ws:
        for t in test_sequence:
            _, values = await run_remote_test(ws, q, t['test_type'], t['test_params'], t.get('test_name'))
            if t['test_type'] == 'eeprom' and values:
                q.eeprom_serial = values.get('eeprom_serial')

        # 4.4.2 sensors: all converters on at 25% load
        await run_remote_test(ws, None, "wib_power", {"on": True})
        for n in range(6):
            await qc.set_load(n, load_steps[0][0])
        await run_remote_test(ws, q, "iv_sensors")
        await run_remote_test(ws, q, "qc_iv_sensors", test_name="qc_iv_sensors_25pct")
        await run_remote_test(ws, q, "temperature", {"ambient": q.ambient_temperature})
        await run_remote_test(ws, q, "alert")
        await run_manual_tests(session, q, alert_led_tests)

        # 4.4.1 load test
        await run_load_tests(ws, session, q, qc)
        for n in range(6):
            await qc.load_off(n)
        await run_remote_test(ws, None, "wib_power", {"on": False})

        # 4.4.3 crate address, 4.4.5 timing
        await run_manual_tests(session, q, crate_address_tests)
        await run_remote_test(ws, q, "timing")
        await run_manual_tests(session, q, timing_tests)

    # 4.4.6 Ethernet, from the host
    if args.debug:
        lg.info("Skipping GbE ping and throughput in debug mode")
    else:
        with gbe_test() as t:
            r = t.run_test()
            q.add_result("gbe_ping", r, t.values)
        r, rate = await gbe_throughput_test()
        q.add_result("gbe_throughput", r, rate, "MB/s", (parameters.throughput_min_mb_s, None))
    await run_manual_tests(session, q, ethernet_tests)

    # 4.4.4 microcontroller and EtherCAT, from the Windows machine
    await run_manual_tests(session, q, mcu_tests)

    # cancel client task
    client_task.cancel()
    print_summary(q)
    add_notes = await async_yesno(session, "Do you want to add notes?")
    if add_notes:
        note_text = await input_dialog(title="Notes", text="Enter tester notes here:").run_async()
        if note_text is not None:
            q.tester_notes = note_text
    test_runs.append(q)
    # wait for client task to exit before finishing
    try:
        await client_task
    except asyncio.CancelledError:
        pass
    if not hwdb_disabled:
        r = await create_hwdb_item(q)
        await upload_test_result(q, r['part_id'])
        # now, image capture
        board_img = await get_board_image()
        await upload_ptc_image(r['part_id'], board_img)

async def run_reception_check():
    """Production shipment entry: the 7 reception checks (procedure 4.1), recorded
    once per delivery instead of for every board."""
    session = ptk.PromptSession()
    po = await session.prompt_async("Purchase order number: ")
    if already_recorded(po):
        print(f"Shipment for PO {po} was already recorded. Nothing to do.")
        return
    r = reception_record(po, tester_name)
    r.batch_number = await session.prompt_async("Production batch number (if any): ")

    for shipment_type, label in shipment_types.items():
        print(f"\n--- {label} ---")
        # count vs purchase order, every shipment type
        ordered = await ask_float(session, f"{label}: quantity on the purchase order: ")
        received = await ask_float(session, f"{label}: quantity received: ")
        count_ok = qc_result.PASS if received == ordered else qc_result.FAIL
        print(f"  -> {count_ok.name}")
        r.add_result(f"{shipment_type}_count_vs_po", count_ok, {"ordered": ordered, "received": received})
        await run_manual_tests(session, r, reception_checks[shipment_type])

    if await async_yesno(session, "Do you want to add notes?"):
        r.tester_notes = await session.prompt_async("Notes: ")
    print_summary(r)
    save_locally(r)
    if not args.disable_hwdb:
        if renewal_needed.is_set():
            await renew_token()
            renewal_needed.clear()
        await upload_reception_record(r)

async def async_entry():
    renewal_task = asyncio.create_task(token_renew_signal())
    session = ptk.PromptSession()
    while True:
        print("\n1. Production board entry (test a PTC)\n2. Production shipment entry (reception checks, once per delivery)\n3. Quit")
        sel = (await session.prompt_async("Choose 1, 2 or 3: ")).strip()
        if sel == '1':
            await run_ptc_test()
        elif sel == '2':
            await run_reception_check()
        elif sel == '3':
            break
    renewal_task.cancel()

if __name__ == "__main__":
    asyncio.run(async_entry()) 
