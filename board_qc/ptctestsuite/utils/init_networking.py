import asyncio
import serial_asyncio

from ptctestsuite.config import parameters
from loguru import logger as lg
import asyncssh

async def init_ptc(serial_port="/dev/ttyUSB0", baudrate=115200, timeout=1, ip_address = parameters.ptc_ip, debug_run = False) -> bool:
    if debug_run:
        return True
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
            return False

        # log into the ptc
        # send username
        writer.write(f"{parameters.ptc_user}{line_end}".encode(encoding))
        await writer.drain()
        await asyncio.sleep(sleep_time)

        # send password
        writer.write(f"{parameters.ptc_password}{line_end}".encode(encoding))
        await writer.drain()
        await asyncio.sleep(sleep_time)

        # assign IP
        iface_str = f"ifconfig eth1 {ip_address} netmask 255.255.255.0{line_end}"
        writer.write(iface_str.encode(encoding))
        await writer.drain()
        await asyncio.sleep(sleep_time)

        # set correct bit to enable GbE
        #writer.write(f"poke 0xff0c0004 0x092e2c4a{line_end}".encode(encoding))
        #await writer.drain()
        #await asyncio.sleep(sleep_time)

        try:
            # again check to see if we are getting anything back
            data = await asyncio.wait_for(reader.read(1024), timeout=0.5)
        except asyncio.TimeoutError:
            print("No response received.")
            return False

        # close the writer
        writer.close()
        await writer.wait_closed()

        # successful init
        return True
    except:
        # something went wrong
        return False
    
async def start_client(ready_signal: asyncio.Event, debug_run=False) -> bool:
    if debug_run:
        ready_signal.set()
        return True
    
    venv_python = f'{parameters.ptc_client_path}/.env/bin/python'

    command = (
        f"test -f {venv_python} &&"
        f"cd /home/root && {venv_python} -u -m ptctestclient"
    )

    try:
        # TODO potentially need to make user/pass configurable
        # TODO set up STDERR handling
        async with asyncssh.connect(f"{parameters.ptc_ip}", username=parameters.ptc_user, password=parameters.ptc_password, known_hosts=None) as conn:
            lg.info(f"Connected to PTC @ {parameters.ptc_ip}")
            async with conn.create_process(command, stderr=asyncssh.STDOUT) as proc:
                # look for server printout when ready and set signal
                async for line in proc.stdout:
                    if "listening" in line.lower():
                        ready_signal.set()
                await proc.wait()
                lg.info(f"PTC client application @ {parameters.ptc_ip} exited")
            await conn.run(f'source {parameters.ptc_client_path}/.env/bin/activate')
    except asyncssh.Error as e:
        lg.error(f"SSH connection failed with error {e}!")
        return False
    return True
