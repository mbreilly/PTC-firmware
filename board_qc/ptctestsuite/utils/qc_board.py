# This is a utility to handle setting loads on the QC board

import asyncio
from loguru import logger as lg
from ptctestsuite.config import parameters

# can reuse this function to setup ssh, just need to change the IP
from ptctestsuite.utils import init_ptc

import serial_asyncio
# can do this entirely over serial in theory
# will need to test and then think about this
import asyncssh

# want to track QC board state
class qc_board_handler:
    def __init__(self, serial_port='/dev/ttyUSB1', baudrate=115200, ip_address = parameters.qc_ip, debug_run = False) -> bool:
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.ip_address = ip_address
        self.debug_run = debug_run

    def pwm_value(self, freq: int, duty_cycle: float) -> str:
        """Computes hex value for PWM parameters

        Args:
            freq (int): Frequency in MHz
            duty_cycle (float): Duty cycle as a decimal (float between 0 and 1) 

        Returns:
            str: PWM hex value
        """
        # do nothing for now until I figure this out
        return ""

    # sshclient wrapper function
    def sshclient(self) -> asyncssh.SSHClientConnection:
        return asyncssh.connect(f"{self.ip_address}", username=parameters.qc_user, password=parameters.qc_password, known_hosts=None)

    async def setup_networking(self) -> bool:
        timeout = 1
        lg.info("Setting up QC Board Networking")
        # init_ptc now returns the discovered DHCP IP (or None on failure), so
        # we treat a present IP as success. Note: the QC board may use a
        # different interface than `end1`; this will be revisited when QC DHCP
        # discovery is added.
        discovered_ip = await init_ptc(
            serial_port=self.serial_port,
            baudrate=self.baudrate,
            timeout=timeout,
            debug_run = self.debug_run 
        )
        if discovered_ip is not None:
            self.ip_address = discovered_ip
        lg.info(f"Set up QC board networking with status {discovered_ip}")
        return discovered_ip is not None

    async def poke(self, addr: int, value: int) -> bool:
        if self.debug_run:
            lg.info(f"[debug] QC board poke {hex(addr)} {hex(value)}")
            return True
        try:
            async with self.sshclient() as conn:
                r = await conn.run(f"poke {hex(addr)} {hex(value)}", check=True)
            return True
        except (OSError, asyncssh.Error) as e:
            lg.error(f"QC board poke {hex(addr)} {hex(value)} failed: {e}")
            return False

    async def peek(self, addr: int) -> int | None:
        if self.debug_run:
            lg.info(f"[debug] QC board peek {hex(addr)}")
            return parameters.qc_timing_locked_value if addr == parameters.qc_timing_status_addr else 0
        try:
            async with self.sshclient() as conn:
                r = await conn.run(f"peek {hex(addr)}", check=True)
            return int(r.stdout.strip().split()[-1], 16)
        except (OSError, asyncssh.Error, ValueError, IndexError) as e:
            lg.error(f"QC board peek {hex(addr)} failed: {e}")
            return None

    async def timing_lock(self) -> tuple[bool | None, int | None]:
        """Resets the QC board timing endpoint and reads its status (procedure 4.5.4).
        Only channel 0 for now, as in procedures v1.4.

        Returns:
            tuple[bool | None, int | None]: locked (None if the board couldn't be read) and the status value
        """
        for value in (0x00000400, 0x00000000):
            if not await self.poke(parameters.qc_timing_ctrl_addr, value):
                return None, None
        status = await self.peek(parameters.qc_timing_status_addr)
        if status is None:
            return None, None
        return status == parameters.qc_timing_locked_value, status

    async def set_load(self, converter: int, value: int) -> bool:
        """Sets the PWM load on one DC-DC converter output (procedure 4.4.1).

        Args:
            converter (int): DC-DC converter / WIB number, 0-5
            value (int): PWM register value, e.g. 0x216 for 25% load

        Returns:
            bool: True if the register writes succeeded
        """
        addr = parameters.qc_load_conv0_addr - 4 * converter
        # procedure writes 0x316 first, then the load value
        if not await self.poke(addr, parameters.qc_load_enable_value):
            return False
        ok = await self.poke(addr, value)
        await asyncio.sleep(parameters.load_settle_time)
        return ok

    async def load_off(self, converter: int) -> bool:
        addr = parameters.qc_load_conv0_addr - 4 * converter
        return await self.poke(addr, parameters.qc_load_off_value)

    # have decided to use context managers instead to avoid not closing the SSH
    # session instead we just close it every time :) I don't think it'll be that
    # bad but can refactor later if we need to 
    """
    # create an ssh client on the QC board
    async def start_ssh(self) -> asyncssh.SSHClientConnection:
        try:
            conn = asyncssh.connect(f"{self.ip_address}", username='root', password='', known_hosts=None)
        except asyncssh.Error as e:
            lg.critical("SSH Connection Error!")
            return # type: ignore
        return conn # type: ignore
    """