# fillmem will be installed on the ptc image 
# sh allows you to import commands as though they are python functions - pretty cool!
import sh
from ptctestclient.utils import qc_result
from ptctestclient.utils import test_base

from loguru import logger as lg

class memory(test_base):
    def run_test(self) -> qc_result:
        try:
            sh.fillmem()
        except sh.ErrorReturnCode:
            lg.error("Memory test failed!")
            return qc_result.FAIL
        return qc_result.PASS