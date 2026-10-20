from time import sleep
from loguru import logger as lg

from ptctestclient.utils import test_base, qc_result, peek, poke

TIMING_CTRL = 0x80020004
TIMING_STATUS = 0x80020104
# endpoint state that means the PTC has locked to the timing stream
TIMING_STAT_GOOD = 0x8


class timing_test(test_base):
    """Timing RX test (procedure 4.5.4.1a). Resets the timing endpoint and checks it
    comes back with status 0x8 and timing_lock set. Needs the timing master running."""

    def __init__(self, settle_time: float = 1.0):
        self.settle_time = settle_time

    def run_test(self) -> qc_result:
        try:
            # select PTC SFP as timing source and hold the endpoint in reset
            poke(TIMING_CTRL, 0x00010400)
            sleep(self.settle_time)
            self.values['status_in_reset'] = hex(peek(TIMING_STATUS))
            # release the reset
            poke(TIMING_CTRL, 0x00010000)
            sleep(self.settle_time)
            status = peek(TIMING_STATUS)
        except Exception as e:  # pylint: disable=broad-exception-caught
            lg.error("Failed to access timing registers")
            lg.exception(e)
            return qc_result.ERROR

        timing_stat = (status >> 24) & 0xF
        timing_lock = (status >> 28) & 0x1
        self.values['status_register'] = hex(status)
        self.values['timing_stat'] = hex(timing_stat)
        self.values['timing_lock'] = timing_lock

        if timing_stat == TIMING_STAT_GOOD and timing_lock:
            lg.info(f"Timing endpoint locked, status {hex(status)}")
            return qc_result.PASS
        lg.error(f"Timing endpoint not locked, status {hex(status)}")
        return qc_result.FAIL
