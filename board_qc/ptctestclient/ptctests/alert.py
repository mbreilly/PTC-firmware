"""ALERT assert test (procedure 4.5.1.6a). Ported from
qc_firmware/scripts/test_scripts/ptc_board_tests/alert_assert.py.

For each LTC2945 IV sensor, set the max VIN threshold to its minimum so the
sensor flags an overvoltage, then check the sensor STATUS register and the
FPGA alert register. Thresholds are restored afterwards.
"""

import subprocess
from time import sleep
from loguru import logger as lg

from ptctestclient.utils import test_base, qc_result, peek

# LTC2945 registers
ALERT_REG = 0x01
STATUS_REG = 0x02
FAULT_REG = 0x03
MAX_VIN_THRESH_MSB = 0x24
MAX_VIN_THRESH_LSB = 0x25
VIN_OVERVALUE_BIT = 3

# FPGA register 66, active low alert lines (see README register table)
FPGA_ALERT_REG = 0x80020108
FPGA_IV_ALERT_MASK = 0x37f  # VP_12_IV_ALERT[6:0], VP2V5_ALERT[8], VP3V3_ALERT[9]

MUX_ADDR = "0x70"
AUX_MUX_CHANNEL = 0x04
MAIN_MUX_CHANNEL = 0x08
AUX_SENSORS = ["0x6e", "0x6f"]


class alert_test(test_base):

    def __init__(self, sensors: list[str] | None = None):
        self.sensors = sensors or ["0x67", "0x68", "0x69", "0x6a", "0x6b", "0x6c", "0x6d", "0x6e", "0x6f"]
        self.sleep_time = 0.1

    def i2cset(self, addr: str, reg: int, value: int):
        subprocess.run(["i2cset", "-y", "0", addr, hex(reg), hex(value)], check=True)

    def i2cget(self, addr: str, reg: int) -> int:
        out = subprocess.run(["i2cget", "-y", "0", addr, hex(reg)], check=True, capture_output=True, text=True).stdout
        return int(out.strip(), 16)

    def select_mux(self, addr: str):
        channel = AUX_MUX_CHANNEL if addr in AUX_SENSORS else MAIN_MUX_CHANNEL
        subprocess.run(["i2cset", "-y", "-r", "0", MUX_ADDR, hex(channel)], check=True)
        sleep(self.sleep_time)

    def restore(self, addr: str):
        # power-on defaults: max threshold all ones, alerts disabled, faults cleared
        self.i2cset(addr, MAX_VIN_THRESH_MSB, 0xff)
        self.i2cset(addr, MAX_VIN_THRESH_LSB, 0xf0)
        self.i2cset(addr, ALERT_REG, 0x00)
        self.i2cset(addr, FAULT_REG, 0x00)

    def run_test(self) -> qc_result:
        result = qc_result.PASS
        for addr in self.sensors:
            try:
                self.select_mux(addr)
                fpga_before = peek(FPGA_ALERT_REG) & FPGA_IV_ALERT_MASK
                # enable the ALERT pin on VIN overvalue, and drop the threshold to 0
                self.i2cset(addr, ALERT_REG, 1 << VIN_OVERVALUE_BIT)
                self.i2cset(addr, MAX_VIN_THRESH_MSB, 0x00)
                self.i2cset(addr, MAX_VIN_THRESH_LSB, 0x00)
                sleep(self.sleep_time)
                status = self.i2cget(addr, STATUS_REG)
                fpga_after = peek(FPGA_ALERT_REG) & FPGA_IV_ALERT_MASK
            except Exception as e:  # pylint: disable=broad-exception-caught
                lg.error(f"Could not run alert test on sensor {addr}")
                lg.exception(e)
                self.values[f"{addr}_alert"] = None
                result = qc_result.FAIL
                continue
            finally:
                try:
                    self.restore(addr)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    lg.error(f"Could not restore thresholds on sensor {addr}")
                    lg.exception(e)

            sensor_flagged = bool((status >> VIN_OVERVALUE_BIT) & 1)
            # alert lines are active low, so a newly asserted alert clears a bit
            fpga_flagged = (fpga_before & ~fpga_after) != 0
            self.values[f"{addr}_alert"] = {
                "status_reg": hex(status),
                "fpga_alert_reg": hex(fpga_after),
                "sensor_flagged": sensor_flagged,
                "fpga_flagged": fpga_flagged,
            }
            if not (sensor_flagged and fpga_flagged):
                lg.error(f"Alert not seen for sensor {addr}: status {hex(status)}, FPGA {hex(fpga_after)}")
                result = qc_result.FAIL

        if result == qc_result.PASS:
            lg.info("Alert assert test passed.")
        return result
