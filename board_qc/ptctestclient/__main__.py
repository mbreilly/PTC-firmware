from ptctestclient.comm import send_test_result
from ptctestclient.ptctests import dummy_client, eeprom, temperature_test, iv_sensors_test, qc_iv_sensors_test, alert_test, timing_test, wib_power, memory
from ptctestclient.utils import qc_result

import asyncio
import json
from websockets.asyncio.server import serve

from loguru import logger as lg

test_registry = {
    "dummy_test": dummy_client,
    "eeprom": eeprom,
    "temperature": temperature_test,
    "iv_sensors": iv_sensors_test,
    "qc_iv_sensors": qc_iv_sensors_test,
    "alert": alert_test,
    "timing": timing_test,
    "wib_power": wib_power,
    "memory": memory,
}

async def run_test(ws):
    async for message in ws:
        try:
            test_info = json.loads(message) 
        except:
            lg.critical(f"Invalid JSON Paylod! Got {message}")
            continue
        # the host can name a run so repeated tests (e.g. one per load step) stay separate
        test_name = test_info.get('test_name', test_info['test_type'])
        # TODO figure out a way to avoid blindly accessing parameters 
        # - some way to establish and communicate structure?
        test_params = test_info['test_params']
        try:
            with test_registry[test_info['test_type']](**test_params) as t:
                lg.info(f"Running Test {test_info['test_type']}")
                r = t.run_test()
                lg.info(f"Test Result: {r}")
                values = t.values
        except Exception as e:
            # always answer so the host isn't left waiting
            lg.exception(e)
            r = qc_result.ERROR
            values = {"error": str(e)}
        await send_test_result(ws, test_name, r, values)

async def main():
    async with serve(run_test, "0.0.0.0", 8765) as server:
        print("Server Listening")
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
