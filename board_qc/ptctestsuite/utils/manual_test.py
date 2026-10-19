from .test_base import test_base
from .qc_result import qc_result
from loguru import logger as lg

class manual_test(test_base):

    def __init__(self, test_name: str = "Manual Test", test_message: str = "Did the test pass? ", accepts_value: bool = False,
                 limits: tuple[float, float] | None = None, unit: str | None = None):
        """Constructor for configurable manual test class

        Args:
            test_name (str, optional): What the test is for. Defaults to "Manual Test".
            test_message (str, optional): How to prompt the tester. Defaults to "Did the test pass? ".
            accepts_value (bool, optional): Denotes if the test accepts a value or not. Defaults to False.
            limits (tuple[float, float], optional): Inclusive acceptance range for the value. When set,
                the result is decided from the value. Defaults to None.
            unit (str, optional): Unit of the value. Defaults to None.
        """
        self._test_name = test_name 
        # overriding this for the dict of pretty print names
        self.__class__.__name__ = test_name
        # setting this as error by default
        self._test_status = qc_result.ERROR
        self._test_value = None
        self._test_message = test_message
        self._accepts_value = accepts_value
        self._limits = limits
        self._unit = unit
    
    @property
    def accepts_value(self) -> bool:
        return self._accepts_value

    @property
    def limits(self) -> tuple[float, float] | None:
        return self._limits

    @property
    def unit(self) -> str | None:
        return self._unit
        
    @property
    def message(self) -> str:
        return self._test_message
    
    @property
    def test_name(self) -> str:
        return self._test_name

    @test_name.setter
    def test_name(self, value: str) -> None:
        try:
            self._test_name = str(value)
            self.__class__.__name__ = str(value)
        except:
            raise ValueError("Cannot cast passed value to a string.")

    @property
    def test_status(self) -> qc_result:
        return self._test_status

    # simple getter and setter method for this one. 
    # expectation is that the tester will indicate pass or fail
    # TODO review if that is the preferred behaviour
    @test_status.setter
    def test_status(self, status: qc_result) -> None:
        self._test_status = status

    def test_init(self):
        return True
    
    def test_end(self):
        return True

    # getter and setter method here in case we'd like
    # the tester to supply a reading
    # this will be a string so we can store repns of arbitrary
    # types, and we will not be doing any checking
    @property
    def test_value(self):
        return self._test_value
    
    @test_value.setter
    def test_value(self, value: str):
        self._test_value = value

    def evaluate(self, value: float) -> qc_result:
        """Decides PASS/FAIL for a reading against the test limits."""
        self._test_value = value
        lo, hi = self._limits
        self._test_status = qc_result.PASS if lo <= value <= hi else qc_result.FAIL
        if self._test_status == qc_result.FAIL:
            lg.warning(f"{self._test_name} reading {value} {self._unit or ''} outside {lo}-{hi}")
        return self._test_status

    def run_test(self) -> qc_result:
        return self._test_status
