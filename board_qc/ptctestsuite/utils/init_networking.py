import asyncio
import re
import serial_asyncio

from ptctestsuite.config import parameters
from loguru import logger as lg

import asyncssh

# command to get the DHCP-assigned IP of the PTC's end1 interface
PTC_IP_CMD = "ip -br addr show end1 | awk '{print $3}' | cut -d/ -f1"
# a simple IPv4 pattern used to extract the address from the serial output
IP_RE = re.compile(r'(\d{1,3}\.){3}\d{1,3}')

async def _discover_ptc_ip(reader, writer, line_end='\r\n', encoding='utf-8', sleep_time=1):
    """Send the IP discovery command over the serial link and return the address."""
    writer.write(f"{PTC_IP_CMD}{line_end}".encode(encoding))
    await writer.drain()
    await asyncio.sleep(sleep_time)
    try:
        # read enough bytes to capture the command output
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
    except asyncio.TimeoutError:
        lg.error("Timed out reading PTC IP address.")
        return None

    output = data.decode(encoding, errors='replace')
    m = IP_RE.search(output)
    if m:
        lg.info(f"Discovered PTC IP: {m.group(0)}")
        return m.group(0)

    lg.error(f"Could not parse PTC IP from output: {output!r}")
    return None

async def init_ptc(serial_port="/dev/ttyUSB0", baudrate=115200, timeout=1, debug_run=False) -> str | None:
    """Configure networking over serial and return the DHCP-assigned PTC IP.

    Returns the discovered `end1` IP address (or "localhost" in debug mode),
    or None if the serial login / IP discovery fails.
    """
    if debug_run:
        return "localhost"
    try:
        # double newline to ensure command gets executed 
        line_end = '\r\n'
        encoding = 'utf-8'
        # sleep time between commands
        sleep_time = 1
        
        # establish a serial connection
        reader, writer = await serial_asyncio.open_serial_connection(url=serial_port, baudrate=baudrate, timeout=timeout)
        
        # send newline to clear the buffer
        writer.write(f"{line_end}".encode(encoding))
        await writer.drain()
        await asyncio.sleep(sleep_time)
        try:
            # read some data to see if we are getting anything back
            data = await asyncio.wait_for(reader.read(1024), timeout=0.5)
        except asyncio.TimeoutError:
            lg.error("No response received.")
            return None

        # log into the ptc
        # send username
        writer.write(f"{parameters.ptc_user}{line_end}".encode(encoding))
        await writer.drain()
        await asyncio.sleep(sleep_time)

        # send password
        writer.write(f"{parameters.ptc_password}{line_end}".encode(encoding))
        await writer.drain()
        await asyncio.sleep(sleep_time)

        try:
            # again check to see if we are getting anything back
            data = await asyncio.wait_for(reader.read(1024), timeout=0.5)
        except asyncio.TimeoutError:
            lg.error("No response received.")
            return None

        # get the DHCP-assigned IP of the PTC's end1 interface
        ptc_ip = await _discover_ptc_ip(reader, writer, line_end, encoding, sleep_time)

        # close the writer
        writer.close()
        await writer.wait_closed()

        return ptc_ip
    except:
        # something went wrong
        return None
    
async def start_client(ready_signal: asyncio.Event, ip_address: str, debug_run=False) -> bool:
    if debug_run:
        ready_signal.set()
        return True

    command = (
        f"python3 -u -m ptctestclient"
    )

    try:
        # TODO potentially need to make user/pass configurable
        # TODO set up STDERR handling
        async with asyncssh.connect(f"{ip_address}", username=parameters.ptc_user, password=parameters.ptc_password, known_hosts=None) as conn:
            lg.info(f"Connected to PTC @ {ip_address}")
            async with conn.create_process(command, stderr=asyncssh.STDOUT) as proc:
                # look for server printout when ready and set signal
                async for line in proc.stdout:
                    if "listening" in line.lower():
                        ready_signal.set()
                await proc.wait()
                lg.info(f"PTC client application @ {ip_address} exited")
    except asyncssh.Error as e:
        lg.error(f"SSH connection failed with error {e}!")
        return False
    return True
