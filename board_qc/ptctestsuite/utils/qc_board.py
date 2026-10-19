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
        return asyncssh.connect(f"{self.ip_address}", username='root', password='', known_hosts=None)

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

    # TODO once I hear back from adrian figure out how we actually
    # want to do this
    async def set_load(self, freq, duty_cycle):
        # TODO later
        addr = "0x80020038"
        val = {}
        async with self.sshclient() as conn:
            r = await conn.run(f"poke {addr} {val}")
    
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