import asyncio
import time

from ptctestsuite.utils import test_base, qc_result
from ptctestsuite.config import parameters
from pythonping import ping
import asyncssh

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
        # pythonping doesn't raise on timeouts, so check the replies
        self.values['packet_loss'] = response.packet_loss
        self.values['rtt_avg_ms'] = round(response.rtt_avg_ms, 3)
        return qc_result.PASS if response.success() else qc_result.FAIL

    def test_end(self):
        # No cleanup to do here.
        return True


async def gbe_throughput_test(ip: str, size_mb: int = parameters.throughput_test_mb) -> tuple[qc_result, float | None]:
    """Streams `size_mb` megabytes from the host to /dev/null on the PTC over ssh and
    measures the rate (procedure 4.4.6.2, acceptance > 12.5 MB/s).

    Returns:
        tuple[qc_result, float | None]: result and throughput in MB/s
    """
    chunk = bytes(1024 * 1024)
    try:
        async with asyncssh.connect(ip, username=parameters.ptc_user,
                                    password=parameters.ptc_password, known_hosts=None) as conn:
            async with conn.create_process("dd of=/dev/null bs=1M", encoding=None) as proc:
                start = time.monotonic()
                for _ in range(size_mb):
                    proc.stdin.write(chunk)
                    await proc.stdin.drain()
                proc.stdin.write_eof()
                await proc.wait()
                elapsed = time.monotonic() - start
    except (OSError, asyncssh.Error) as e:
        lg.error(f"Throughput test failed: {e}")
        return qc_result.ERROR, None
    rate = size_mb / elapsed
    lg.info(f"GbE throughput {rate:.1f} MB/s")
    return (qc_result.PASS if rate > parameters.throughput_min_mb_s else qc_result.FAIL), round(rate, 2)
