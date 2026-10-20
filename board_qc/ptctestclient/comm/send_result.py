import asyncio
import websockets
import json
from ptctestclient.utils import qc_result

async def send_test_result(websocket: websockets.ClientConnection, test_name: str, test_result: qc_result, test_values: dict | None = None):
    msg = {"test_name": test_name, "test_result": test_result, "test_values": test_values or {}}
    await websocket.send(json.dumps(msg))
