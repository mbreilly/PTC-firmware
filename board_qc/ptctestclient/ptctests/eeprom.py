from ptctestclient.utils import test_base, qc_result
from loguru import logger as lg

import os

class eeprom(test_base):
    # actual test primarily based on Elliot Keener's previous work

    def get_serial(self):
        i2c_raw = os.popen('i2cget -y 0 0x50 0xfa i 6').read()
        return int(''.join(b[2:] for b in i2c_raw.split()), 16)
    
    def run_test(self):
        try:
            eeprom_serial = self.get_serial()
            lg.info(f"Got EEPROM Serial {eeprom_serial}")
        except ValueError as e:
            # before throwing a fail, retry
            lg.exception(e)
            lg.info("Getting EEPROM serial failed on the first attempt. Retrying before marking the test as failed.")
            try:
                eeprom_serial = self.get_serial()
            except ValueError as ee:
                lg.exception(ee)
                return qc_result.FAIL
        # 6 byte globally unique ID, stored as hex so it reads like the label/MAC
        self.values['eeprom_serial'] = f"{eeprom_serial:012x}"
        return qc_result.PASS
        # in Elliot's initial test he uses the EEPROM to assign
        # an IP address. I don't think this will be necessary here
        # TODO verify that simply reading the EEPROM is sufficient
        # to verify functionality