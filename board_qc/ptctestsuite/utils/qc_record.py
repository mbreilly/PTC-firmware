from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
import time

from ptctestsuite.utils.qc_result import qc_result

@dataclass
class qc_record:
    serial_number: str
    tester_name: str
    # each entry is {"result": qc_result, "value": ..., "unit": ..., "limits": ...}
    test_status: dict = field(default_factory=dict)
    tester_notes: str = ""
    # I'm assuming the testing will be done here at Penn - but we can reconfigure if necessary
    test_location: str = "University of Pennsylvania"
    test_datetime: datetime = field(default_factory=datetime.now)
    # Enclustra SoM serial, scanned before the SoM tests (procedure 4.3.2)
    som_serial: str | None = None
    # globally unique ID read from the PTC EEPROM (procedure 4.5.2)
    eeprom_serial: str | None = None
    # room temperature entered by the tester, reference for the temperature sensors
    ambient_temperature: float | None = None
    # file names of the front and back photos (procedure 4.1.3), as uploaded to the HWDB
    photos: dict = field(default_factory=dict)
    # retests: every run of a board is kept; this one's number and why it was run
    run_number: int = 1
    run_type: str = "First test"            # First test, Retest, Retest after repair
    follows_run: int | None = None          # the run this one retests
    after_repair: int | None = None         # the repair made since that run
    retest_reason: str | None = None
    # serials that should only be on one board but were seen on another
    som_moved_from: str | None = None
    eeprom_also_on: list | None = None

    def add_result(self, test_name: str, result: qc_result, value=None, unit: str | None = None, limits=None):
        self.test_status[test_name] = {"result": result, "value": value, "unit": unit,
                                       "limits": list(limits) if limits is not None else None}

    @property
    def overall_result(self) -> qc_result:
        """PASS only if every recorded test passed (procedure 4.5.3)."""
        if not self.test_status:
            return qc_result.ERROR
        results = [t["result"] for t in self.test_status.values()]
        if all(r == qc_result.PASS for r in results):
            return qc_result.PASS
        if any(r == qc_result.FAIL for r in results):
            return qc_result.FAIL
        return qc_result.ERROR

    def gen_hwdb_datasheet(self):

        def drop_none(obj: dict):
            return {k: v for k,v in obj.items() if v is not None}

        def clean_enums(obj):
            if isinstance(obj, dict):
                d = drop_none(obj)
                return {k: clean_enums(v) for k, v in d.items()}
            elif isinstance(obj, list):
                return [clean_enums(v) for v in obj]
            elif isinstance(obj, Enum):
                return obj.name
            return obj
        
        dd = asdict(self)
        dd['overall_result'] = self.overall_result
        dd = clean_enums(dd)
        dd['test_date'] = dd['test_datetime'].strftime("%Y-%m-%d")
        dd['test_time'] = f"{dd['test_datetime'].strftime('%H:%M:%S')} {time.tzname[0]}"
        dd.pop('test_datetime')
        #return yaml.dump(dd, sort_keys=False)
        return dd
