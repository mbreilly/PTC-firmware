import os
from time import sleep
from loguru import logger as lg

from ptctestclient.utils import test_base, qc_result

class temperature_test(test_base):

    def __init__(self, sensors: list[str] | None = None, ambient: float | None = None, tolerance: float = 5.0):
        """Reads the TMP117 temperature sensors and checks they are near ambient.

        Args:
            sensors (list[str], optional): I2C addresses to read. Defaults to the 4 local sensors.
            ambient (float, optional): Room temperature in degC entered by the tester. When given,
                                       the acceptance window is ambient +/- tolerance (procedure 4.5.1.5).
                                       Otherwise falls back to a 15-30 C window.
            tolerance (float, optional): Allowed deviation from ambient in degC. Defaults to 5.
        """
        # TODO procedure lists 8 temperature sensors, only 4 addresses are known here
        self.sensors = sensors or ['0x48', '0x49', '0x4A', '0x4B']
        self.ambient = ambient
        self.tolerance = tolerance

    def read_temp(self, addr):
        #Read the temperature register 'word'
        i2c_raw = os.popen('i2cget -y 0 ' + addr + ' 0x00 w').read()
        #i2cget gives byte-swapped output
        i2c_dec = ((int((i2c_raw)[4:6],16) << 8) + int((i2c_raw)[2:4],16))
        # Note that two's comp can give neg temp - should never see on PTC
        return i2c_dec * 00.0078125 #conversion to degC on TMP117
 
    def test_init(self) -> bool:
        lg.info("Starting temperature sensor test...")
        self.readings = {v: float(0) for v in self.sensors}
        self.sleep_time = 0.1
        if self.ambient is not None:
            self.temp_accept_low = self.ambient - self.tolerance
            self.temp_accept_high = self.ambient + self.tolerance
        else:
            # room temperature varies significantly, especially in DRL
            # but 15-30 C are ranges that humans can definitely tolerate
            self.temp_accept_low = 15
            self.temp_accept_high = 30
        # just going to return true here since all we're doing is setting up some values
        return True

    def run_test(self) -> qc_result:
        for addr in self.readings.keys():
            try:
                self.readings[addr] = self.read_temp(addr)
                self.values[f'{addr}_temperature'] = round(self.readings[addr], 2)
                sleep(self.sleep_time)
            except Exception as e:
                lg.error(f"Temperature reading failed on sensor {addr}!")
                lg.exception(e)
                self.values[f'{addr}_temperature'] = None

        result = qc_result.PASS
        for a,r in self.readings.items():
            if self.values[f'{a}_temperature'] is None:
                result = qc_result.FAIL
            elif not (self.temp_accept_low <= r <= self.temp_accept_high):
                lg.error(f"Temperature readings outside of normal range. Sensor {a} reported a value of {r}.")
                result = qc_result.FAIL
        if result == qc_result.PASS:
            lg.info("Temperature sensor test passed.")
        return result
