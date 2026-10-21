import asyncio
import httpx
import aiofiles

from pathlib import Path

from loguru import logger as lg

from ptctestsuite.utils.qc_record import qc_record
from ptctestsuite.utils.qc_result import qc_result
from ptctestsuite.config.parameters import repair_test_type, qc_test_type
from ptctestsuite.config.parameters import reception_part_type_id, reception_serial_prefix, ptc_part_type_id, ptc_qc_test_id, bearer_token_path, dune_hwdb_api_path, local_cache_file, token_renewal_interval
from collections.abc import Buffer

from datetime import datetime

# rolling my own implementation for the HWDB here, since I see no need to pull in the entire library
# for what we need to do
# plus, I will have to write my own code to massage my own structures into the HWDB format,
# so might as well take the extra step to make a POST/GET request

"""
bearer_token = None
with open(Path(bearer_token_path)) as bt:
    bearer_token = bt.read()

request_header = {"Authorization": f"Bearer {bearer_token}"}
"""

# TODO take qc result or serial?
# we are NOT doing this - afaik the HWDB is structured in a way that makes this
# very expensive. We will store locally, and can spin up a REDIS instance in
# case we have multiple testers
"""
async def check_item_exists(item: qc_record) -> dict:
    # For this one, it looks like I have to get a list of hwitems matching the PTC Component type ID, parse the datasheet
    # and then check if an item with the serial already exists
    # Since we reference items by an ID assigned at upload time, there's no other way to do this it seems

    # first, let's craft our request
    p = f"{dune_hwdb_api_path}/component-types/{ptc_part_type_id}/components"
    async with httpx.AsyncClient() as client:
        r = await client.get(p, headers=request_header)
        p = r.json()
    
    # ok - now need to get the QC reports? unless serial goes in some other field
    
    # we know the structure from the wiki
    #parts = [i['component_id'] for i in p["data"]]


    return dict() 
"""


async def renew_token():
    lg.info('Renewing HWDB Token')
    process = await asyncio.create_subprocess_exec(
        'htgettoken', '--vaultserver=htvaultprod.fnal.gov', '--issuer=fermilab',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    ) 
    print("HWDB Token Needs Renewal --- follow the instructions below")
    while True:
        line = await process.stdout.readline()
        line = line.decode('utf-8').strip()
        if not line:
            break
        print(line)
    await process.wait()

class HwdbError(Exception):
    """The HWDB couldn't be reached or refused a request. The message is shown to the tester."""


async def auth_header():
    try:
        async with aiofiles.open(Path(bearer_token_path), 'r') as f:
            token = (await f.read()).strip()
    except OSError as e:
        raise HwdbError(f"Can't read the HWDB token at {bearer_token_path} ({e.strerror}). "
                        "Run htgettoken to get a new one.") from e
    return {"Authorization": f"Bearer {token}"}


async def _request(method: str, path: str, what: str, **kwargs) -> dict:
    """Sends one request to the HWDB and returns the JSON reply.

    Raises HwdbError when the HWDB can't be reached or doesn't answer with 200 OK,
    so a failed upload is never reported as a success.
    """
    ah = await auth_header()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, path, headers=ah, **kwargs)
    except httpx.HTTPError as e:
        raise HwdbError(f"Can't connect to the HWDB at {dune_hwdb_api_path} while trying to {what} "
                        f"({type(e).__name__}). Check the network connection.") from e
    if resp.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        raise HwdbError(f"The HWDB refused the request to {what} (HTTP {resp.status_code}). "
                        "The token has probably expired; run htgettoken to renew it.")
    if resp.status_code != httpx.codes.OK:
        raise HwdbError(f"The HWDB couldn't {what} (HTTP {resp.status_code}): {resp.text.strip().splitlines()[0][:200] if resp.text.strip() else "no details"}")
    return resp.json()


async def check_connection() -> None:
    """Raises HwdbError if the HWDB can't be reached with the current token."""
    await _request("GET", f"{dune_hwdb_api_path}/users/whoami", "check the connection")
    

def _part_id(item: dict) -> str | None:
    if item.get("part_id"):
        return str(item["part_id"])
    href = str(item.get("href") or "")
    return href.rstrip("/").rsplit("/", 1)[-1] or None


async def find_parts(serial_number: str, part_type_id: str = ptc_part_type_id) -> list[dict]:
    """Every HWDB entry of this component type with exactly this serial number.
    The HWDB itself doesn't stop two entries sharing a serial, so the program checks.
    Returns [{"part_id": ..., "created": ...}]."""
    p = f"{dune_hwdb_api_path}/component-types/{part_type_id}/components"
    found, page = [], 1
    while True:
        rj = await _request("GET", p, f"look up serial {serial_number}",
                            params={"serial_number": serial_number, "page": page, "size": 100})
        for item in rj.get("data") or []:
            if str(item.get("serial_number", "")).strip() == serial_number and _part_id(item):
                found.append({"part_id": _part_id(item), "created": item.get("created") or item.get("creation_date")})
        if not (rj.get("pagination") or {}).get("next") or page >= 20:
            return found
        page += 1


async def get_test_records(part_id: str, test_type: str) -> list[dict]:
    """Every record of one test type on a part, oldest first, including earlier runs.
    Returns [{"created": ..., "test_data": {...}, "comments": ...}]."""
    p = f"{dune_hwdb_api_path}/components/{part_id}/tests/{test_type}"
    rj = await _request("GET", p, f"read the {test_type} history of {part_id}", params={"history": "true"})
    data = rj.get("data") or []
    if isinstance(data, dict):
        data = [data]
    out = []
    for t in data:
        out.append({"created": t.get("created"), "test_data": t.get("test_data") or {}, "comments": t.get("comments")})
    return sorted(out, key=lambda t: str(t["created"] or ""))


async def upload_repair_record(part_id: str, repair: dict) -> dict:
    """Adds a repair record to the board's HWDB entry. Earlier runs and repairs are untouched."""
    p = f"{dune_hwdb_api_path}/components/{part_id}/tests"
    test_data = {
        "Repair Number": repair["n"], "Repair Date": repair["date"], "Repaired By": repair["repaired_by"],
        "After Run": repair.get("after_run"), "For Steps": repair.get("for_steps") or [],
        "Fault Found": repair.get("fault_found", ""), "Action Taken": repair.get("action_taken", ""),
        "Parts Replaced": repair.get("parts_replaced", ""), "Photos": repair.get("photos") or [],
    }
    rj = await _request("POST", p, f"add repair {repair['n']} to {part_id}",
                        json={"comments": repair.get("notes") or "", "test_data": test_data,
                              "test_type": repair_test_type})
    lg.info(f"Posted repair {repair['n']} for part {part_id}")
    return rj


async def check_item_exists(item: qc_record) -> bool:
    """Checks if an entry for a board already exists

    Args:
        item (qc_record): qc_record of the board

    Returns:
        bool: Flag indicating if the board exists in the log
    """
    return bool(await find_parts(str(item.serial_number)))

async def create_hwdb_item(item: qc_record, part_type_id: str = ptc_part_type_id, serial_number: str | None = None) -> dict:
    serial_number = serial_number or str(item.serial_number)
    # a serial must only ever have one entry: refuse rather than make a second one
    existing = await find_parts(serial_number, part_type_id)
    if existing:
        raise HwdbError(f"{serial_number} already has an HWDB entry ({existing[0]['part_id']}). "
                        "Results must be added to it, not to a new entry.")
    # first, craft the request
    p = f"{dune_hwdb_api_path}/component-types/{part_type_id}/components"
    # hardcoding some things for now, we can change later if needed (unlikely)
    req_payload = {
        'comments': 'Test', 
        'country_code': "US", 
        'institution': {"id": 191}, 
        'manufacturer': {"id": 67}, 
        'serial_number': serial_number, 
        'component_type': {"part_type_id": part_type_id},
        'specifications': {'DATA': {}}
    }
    lg.info(f'Creating HWDB entry for {serial_number}')
    rj = await _request("POST", p, f"create the entry for {serial_number}", json=req_payload)
    lg.info(f'Created HWDB entry for {serial_number}, has component id {rj['component_id']}')
    return rj


async def upload_test_result(item: qc_record, part_id: str) -> dict:
    p = f"{dune_hwdb_api_path}/components/{part_id}/tests"

    # TODO get Martin to update the HWDB keys
    test_res = item.gen_hwdb_datasheet()
    test_res['Test Date'] = test_res['test_date']
    test_res['Test Time'] = test_res['test_time']
    test_res.pop('test_date')
    test_res.pop('test_time')
    test_res['Operator Name'] = test_res['tester_name']
    test_res.pop('tester_name')
    test_res['Test Location'] = 'University of Pennsylvania'
    test_res.pop('test_location')
    test_res.pop('tester_notes', None)
    test_res['Overall Result'] = test_res.pop('overall_result')
    if 'som_serial' in test_res:
        test_res['SoM Serial Number'] = test_res.pop('som_serial')
    if 'eeprom_serial' in test_res:
        test_res['EEPROM Serial ID'] = test_res.pop('eeprom_serial')
    if 'ambient_temperature' in test_res:
        test_res['Ambient Temperature (C)'] = test_res.pop('ambient_temperature')
    for old, new in (('run_number', 'Run Number'), ('run_type', 'Run Type'), ('follows_run', 'Follows Run'),
                     ('after_repair', 'After Repair'), ('retest_reason', 'Retest Reason'),
                     ('som_moved_from', 'SoM Moved From'), ('eeprom_also_on', 'EEPROM Also On')):
        if old in test_res:
            test_res[new] = test_res.pop(old)

    req_payload = {
        'comments': item.tester_notes,
        #'test_data': {'': str(item.gen_hwdb_datasheet())},
        #'test_data': item.gen_hwdb_datasheet(),
        'test_data': test_res,
        'test_type': qc_test_type
    }
    lg.info(f"Posting test result for board {item.serial_number} to HWDB")

    rj = await _request("POST", p, f"add the test results for board {item.serial_number}", json=req_payload)
    lg.info(f"Successfully posted test results for board {item.serial_number}")
    return rj


async def upload_ptc_image(part_id: str, image: Buffer, filename: str | None = None,
                           comments: str = "Board Image", mime: str = "image/png") -> dict:
    p = f"{dune_hwdb_api_path}/components/{part_id}/images"
    data = {'image': (filename or f'boardimage-{part_id}.png', image, mime)}
    json_payload = {"comments": comments}

    rj = await _request("POST", p, f"upload the image for part {part_id}", data=json_payload, files=data)
    lg.info(f"Successfully uploaded {filename or 'image'} for part {part_id}")
    return rj


async def upload_reception_record(record) -> dict:
    """Creates an entry for the shipment in the same HWDB as the boards and attaches
    the one-time reception checks (procedure 4.1) to it as a test."""
    item = await create_hwdb_item(record, part_type_id=reception_part_type_id,
                                  serial_number=f"{reception_serial_prefix}{record.serial_number}")
    p = f"{dune_hwdb_api_path}/components/{item['part_id']}/tests"
    test_res = record.gen_hwdb_datasheet()
    test_res['Test Date'] = test_res.pop('test_date')
    test_res['Test Time'] = test_res.pop('test_time')
    test_res['Operator Name'] = test_res.pop('tester_name')
    test_res['Test Location'] = test_res.pop('test_location')
    test_res.pop('tester_notes', None)
    test_res['Overall Result'] = test_res.pop('overall_result')
    req_payload = {
        'comments': record.tester_notes,
        'test_data': test_res,
        'test_type': 'Reception Check'
    }
    rj = await _request("POST", p, f"add the reception record for PO {record.serial_number}", json=req_payload)
    lg.info(f"Posted reception record for PO {record.serial_number}")
    return rj
