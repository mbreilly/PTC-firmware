"""A stand-in for the PTC test client, for trying the test station without hardware.

    python -m ptctestsuite.fake_ptc                 every automatic test passes
    python -m ptctestsuite.fake_ptc --fail temperature load2_75pct

Then, in another terminal:  python -m ptctestsuite --debug --disable-hwdb
It answers on localhost:8765 like ptctestclient does on the PTC, with made-up readings.
"""

import asyncio
import json
import random
from argparse import ArgumentParser

from websockets.asyncio.server import serve

from ptctestsuite.config import parameters

parser = ArgumentParser(prog="python -m ptctestsuite.fake_ptc")
parser.add_argument("--fail", nargs="*", default=[], help="test names that should fail")
parser.add_argument("--delay", type=float, default=0.8, help="seconds each test takes")
args = parser.parse_args()


def readings(name: str, params: dict) -> dict:
    if name == "eeprom":
        return {"eeprom_serial": "0x" + "".join(random.choice("0123456789ABCDEF") for _ in range(12))}
    if name == "iv_sensors":
        v = {f"wib{n}_v": round(random.uniform(12.1, 12.25), 3) for n in range(6)}
        v.update(som_v=12.18, som_i=round(random.uniform(0.8, 1.2), 3), v2p5=2.51, v3p3=3.31)
        return v
    if name == "temperature":
        return {f"t{n}": round(params.get("ambient", 24) + random.uniform(0.5, 3), 1) for n in range(4)}
    if name.startswith("load") or name.startswith("qc_iv_sensors"):
        mid = (params.get("i_min", 1.4) + params.get("i_max", 1.6)) / 2
        return {"current_a": round(mid + random.uniform(-0.04, 0.04), 3)}
    if name == "timing":
        return {"status": "0x8", "locked": True}
    if name == "alert":
        return {"flagged": "all"}
    return {}


async def handler(ws):
    async for raw in ws:
        t = json.loads(raw)
        name = t.get("test_name", t["test_type"])
        await asyncio.sleep(args.delay if t["test_type"] != "wib_power" else 0.1)
        result = 0 if name in args.fail else 1
        await ws.send(json.dumps({"test_name": name, "test_result": result,
                                  "test_values": readings(name, t.get("test_params", {}))}))
        print(f"{name}: {'FAIL' if result == 0 else 'PASS'}")


async def main():
    async with serve(handler, "localhost", parameters.ws_port) as server:
        print(f"Fake PTC listening on localhost:{parameters.ws_port}")
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
