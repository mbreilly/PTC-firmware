import asyncio
import httpx
import aiofiles

from pathlib import Path

from loguru import logger as lg

from ptctestsuite.utils.qc_record import qc_record
from ptctestsuite.utils.qc_result import qc_result
from ptctestsuite.config.parameters import ptc_part_type_id, ptc_qc_test_id, bearer_token_path, dune_hwdb_api_path, local_cache_file, token_renewal_interval
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

async def auth_header():
    async with aiofiles.open(Path(bearer_token_path), 'r') as f:
        token = (await f.read()).strip()
    return {"Authorization": f"Bearer {token}"}
    

async def check_item_exists(item: qc_record) -> bool:
    """Checks if an entry for a board already exists

    Args:
        item (qc_record): qc_record of the board

    Returns:
        bool: Flag indicating if the board exists in the log
    """
    # TODO !!!! ignoring while testing !!!!
    return False
    serial_number = item.serial_number
    async with aiofiles.open(Path(local_cache_file), 'r') as f:
        existing_boards = [l.strip() async for l in f]
    if serial_number in existing_boards:
        return True
    return False

async def create_hwdb_item(item: qc_record) -> dict:
    item_exists = await check_item_exists(item)
    if item_exists:
        lg.error("Item Already Exists in HWDB!")
        return dict()
    # first, craft the request
    p = f"{dune_hwdb_api_path}/component-types/{ptc_part_type_id}/components"
    # hardcoding some things for now, we can change later if needed (unlikely)
    req_payload = {
        'comments': 'Test', 
        'country_code': "US", 
        'institution': {"id": 191}, 
        'manufacturer': {"id": 67}, 
        'serial_number': str(item.serial_number), 
        'component_type': {"part_type_id": ptc_part_type_id},
        'specifications': {'DATA': {}}
    }
    ah = await auth_header()
    async with httpx.AsyncClient() as client:
        lg.info(f'Creating HWDB entry for board {item.serial_number}')
        resp = await client.post(p, json=req_payload, headers=ah)

    if resp.status_code == httpx.codes.OK:
        rj = resp.json()
        lg.info(f'Created HWDB entry for board {item.serial_number}, has component id {rj['component_id']}')
        return rj
    else:
        lg.critical(f"Failed to create entry for board {item.serial_number} in HWDB!")
        print(resp.json())
        return dict()


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

    req_payload = {
        'comments': item.tester_notes,
        #'test_data': {'': str(item.gen_hwdb_datasheet())},
        #'test_data': item.gen_hwdb_datasheet(),
        'test_data': test_res,
        'test_type': 'QC Test'
    }
    lg.info(f"Posting test result for board {item.serial_number} to HWDB")

    ah = await auth_header()
    async with httpx.AsyncClient() as client:
        resp = await client.post(p, json=req_payload, headers=ah)
    #print(resp.json())
    if resp.status_code == httpx.codes.OK:
        lg.info(f"Successfully posted test results for board {item.serial_number}")
        return resp.json()
    else:
        lg.critical(f"Failed to add test results for board {item.serial_number} to HWDB!")
        return dict()


async def upload_ptc_image(part_id: str, image: Buffer) -> dict:
    p = f"{dune_hwdb_api_path}/components/{part_id}/images"
    data = {'image': (f'boardimage-{part_id}.png', image, 'application/png')}
    json_payload = {"comments": "Board Image"}

    ah = await auth_header()
    async with httpx.AsyncClient() as client:
        resp = await client.post(p, headers=ah, data=json_payload, files=data)
    

    if resp.status_code == httpx.codes.OK:
        lg.info(f"Successfully uploaded image for part {part_id}")
        return resp.json()
    else:
        lg.critical(f"Failed to upload image for part {part_id}!")
        return dict()