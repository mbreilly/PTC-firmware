from ptctestsuite.utils import test_base, qc_result
from pythonping import ping

from loguru import logger as lg


# this is one of the few tests that needs to be run on the host machine
# there is a slight break in the homogeneity of things (explicitly running this
# instead of just throwing it in a list
# but, it's part of the test plan, and we need to make sure networking functions before
# running the rest of the tests

class gbe_test(test_base):

    def __init__(self, ip: str):
        self._ip = ip

    def test_init(self):
        # nothing to init anymore
        return True

    def run_test(self):
        try:
            response = ping(self._ip, verbose=True, count=3)
            lg.info(f"Attempting to ping PTC at {self._ip}. Response is: {response}")
        except Exception as e:
            lg.error(e)
            return qc_result.FAIL
        return qc_result.PASS

    def test_end(self):
        # No cleanup to do here.
        return True