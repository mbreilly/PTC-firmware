import prompt_toolkit as ptk
import asyncio
import json

from loguru import logger as lg

from prompt_toolkit.shortcuts import choice, message_dialog, input_dialog, confirm
from prompt_toolkit.filters import is_done

from ptctestsuite.ptctests import dummy_test
from ptctestsuite.utils import qc_result, qc_record, init_ptc, start_client, async_yesno, manual_test
from websockets.asyncio.client import connect
from ptctestsuite.config import manual_tests, test_sequence
from ptctestsuite.utils.hwdb import upload_ptc_image, upload_test_result, create_hwdb_item, renew_token
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

async def run_ptc_test():
    global tester_name, test_sequence 
    hwdb_disabled = args.disable_hwdb

    if not hwdb_disabled:
        if renewal_needed.is_set():
            await renew_token()
            renewal_needed.clear()
        
    session = ptk.PromptSession()
    ptc_serial = await session.prompt_async("PTC Serial Number: ")

    # try to init the PTC on the default serial port, discovering its DHCP IP
    ptc_ip = await init_ptc(debug_run=args.debug)
    if ptc_ip is None:
        ptc_serial_port = await session.prompt_async("Connection failed on the default serial port. Enter a different port to attempt connection again: ", default="/dev/ttyUSB1")
        # this is kind of goofy, maybe rework this?
        ptc_ip = await init_ptc(serial_port=ptc_serial_port, debug_run=args.debug)
        if ptc_ip is None:
            lg.critical("PTC Network Configuration Failed!")
            return
    
    server_listening = asyncio.Event()
    client_task = asyncio.create_task(start_client(server_listening, ip_address=ptc_ip, debug_run=args.debug))
    # start client task
    if not args.debug:
        try:
            lg.info("Waiting for PTC Application to Initialize....")
            await asyncio.wait_for(server_listening.wait(), timeout=20)
        except asyncio.TimeoutError:
            lg.critical("PTC Application failed to start within 20 seconds!")
            client_task.cancel()
   
    
    q = qc_record(ptc_serial, tester_name)
    lg.info(f"Starting new PTC Test Session.")
    # do the manual tests here
    async with connect(f"ws://{ptc_ip}:{parameters.ws_port}") as ws:
        for t in test_sequence:
            print(f"Running {t['test_type']} with parameters {t['test_params']}")
            lg.info(f"Running {t['test_type']} with parameters {t['test_params']}")
            await ws.send(json.dumps(t))
            msg = await ws.recv()
            msg = json.loads(msg)
            # TODO need to implement value handling for auto tests - TODO
            test_val = None
            q.test_status[msg['test_name']] = {"result": qc_result(int(msg['test_result'])), "value": None}
    
    for t in manual_tests:
        with manual_test(**t) as test:
            result = await async_yesno(session, test.message)
            test_val = None
            if test.accepts_value:
                test_val = await session.prompt_async("What was the value of the tested parameter? ")
            q.test_status[test.test_name] = {"result": qc_result(int(result)), "value": test_val}
    # or here....
    # cancel client task
    client_task.cancel()
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

async def async_entry():
    test_again = True
    renewal_task = asyncio.create_task(token_renew_signal())
    while(test_again):
        await run_ptc_test()
        resp = input("Do you want to run another test? (y/n)")
        test_again = resp.lower() in ('y', 'yes')
    renewal_task.cancel()

if __name__ == "__main__":
    asyncio.run(async_entry()) 
