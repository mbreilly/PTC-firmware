# One-time shipment reception checks (procedure 4.1). Front panels, bare PCBs and
# assembled PCBs are checked once per delivery, so they get their own record
# instead of being repeated in every board's QC record.

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time

from loguru import logger as lg

from ptctestsuite.config import parameters
from ptctestsuite.utils.qc_record import qc_record

shipment_types = {
    "front_panels": "Front panels",
    "bare_pcbs": "Bare PCBs",
    "assembled_pcbs": "Assembled PCBs",
}

@dataclass
class reception_record(qc_record):
    # serial_number holds the purchase order number for a shipment
    batch_number: str = ""

    @property
    def key(self) -> str:
        return self.serial_number

    def gen_hwdb_datasheet(self):
        dd = super().gen_hwdb_datasheet()
        dd['purchase_order'] = dd.pop('serial_number')
        dd.pop('som_serial', None)
        dd.pop('eeprom_serial', None)
        dd.pop('ambient_temperature', None)
        dd.pop('photos', None)
        for k in ('run_number', 'run_type', 'follows_run', 'after_repair', 'retest_reason',
                  'som_moved_from', 'eeprom_also_on'):
            dd.pop(k, None)
        return dd


def already_recorded(purchase_order: str) -> bool:
    """Checks the local log so the same delivery isn't recorded twice."""
    path = Path(parameters.reception_log_file)
    if not path.exists():
        return False
    key = purchase_order
    with path.open() as f:
        for line in f:
            try:
                if json.loads(line).get('key') == key:
                    return True
            except json.JSONDecodeError:
                continue
    return False


def save_locally(record: reception_record) -> None:
    entry = record.gen_hwdb_datasheet()
    entry['key'] = record.key
    with Path(parameters.reception_log_file).open('a') as f:
        f.write(json.dumps(entry) + "\n")
    lg.info(f"Saved reception record for PO {record.serial_number}")
