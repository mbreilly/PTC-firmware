from abc import ABC, abstractmethod
from .qc_result import qc_result

from ptctestsuite.config.test_names import test_pretty_names

from loguru import logger as lg

# Here, we lay out the interface definition for a test.
# These will be classes, simply because it gives me the ability to write an interface, 
# and have the tests comply with it.
# The intent is to have the lifetime be handled using the `with` statment, e.g.
# with test_name as t:
#   << potentially do some work here >>
#   t.run_test()
#   << potentially more work here >>

class test_base(ABC):

    # measured values recorded alongside the result.
    # Created lazily since not every test calls super().__init__
    @property
    def values(self) -> dict:
        if not hasattr(self, '_values'):
            self._values = {}
        return self._values

    # writing this so the method can be called easily from an overrided init
    def log_test_init(self):
        lg.info(f"Starting {test_pretty_names[self.__class__.__name__]} test...")
    
    @abstractmethod
    def test_init(self) -> bool:
        """ Test Init Stub. Returns boolean indicating if initialization passed or failed"""
        # Default of simply logging that test has initialized
        self.log_test_init()
        return True


    @abstractmethod 
    def run_test(self) -> qc_result:
        """ Test run stub. Returns a `qc_result` object indication the outcome of the test"""
        pass

    def log_test_end(self):
        lg.info(f"Finished {test_pretty_names[self.__class__.__name__]} test.")

    @abstractmethod
    def test_end(self) -> bool:
        """Test de-init stub. Returns boolean indicating status"""
        # Similar to initialize method
        self.log_test_end()
        return True

    def __enter__(self):
        test_init_status = self.test_init()
        if not test_init_status:
            # TODO maybe change these to use logging instead of throwing a runtime error?
            raise RuntimeError(f"{test_pretty_names[self.__class__.__name__]} Test Initialization Failed") 
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        test_end_status = self.test_end()
        if not test_end_status:
            # TODO maybe change these to use logging instead of throwing a runtime error?
            raise RuntimeError(f"{test_pretty_names[self.__class__.__name__]} Test Exit Failed")

