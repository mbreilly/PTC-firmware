from loguru import logger as lg

from ptctestclient.utils import test_base, qc_result, poke

# one enable register per DC-DC converter, see the register table in the README
WIB_POWER_BASE = 0x80020010


class wib_power(test_base):
    """Turns DC-DC converters (WIB 12V outputs) on or off.
    Same as `python3 power_on_wib.py [x] on|off`. Used as a setup step by the host."""

    def __init__(self, converters: list[int] | None = None, on: bool = True):
        self.converters = list(range(6)) if converters is None else converters
        self.on = on

    def run_test(self) -> qc_result:
        try:
            for n in self.converters:
                poke(WIB_POWER_BASE + 4 * n, 1 if self.on else 0)
                lg.info(f"Powering WIB {n} {'on' if self.on else 'off'}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            lg.error("Failed to set WIB power")
            lg.exception(e)
            return qc_result.ERROR
        return qc_result.PASS
