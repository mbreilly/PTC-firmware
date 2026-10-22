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
# Each delivery holds one kind of product, so it gets its own HWDB entry with this code in its name
shipment_codes = {"front_panels": "FP", "bare_pcbs": "BARE", "assembled_pcbs": "ASSY"}

@dataclass
class reception_record(qc_record):
    # serial_number holds the purchase order number for a shipment
    batch_number: str = ""
    product_type: str = ""   # a key of shipment_types: one kind of product per delivery
    documents: list = field(default_factory=list)   # file names of the vendor certificates

    @property
    def key(self) -> str:
        return delivery_key(self.serial_number, self.product_type, self.batch_number)

    @property
    def hwdb_serial(self) -> str:
        """The delivery's own HWDB entry, e.g. SHIPMENT-PO-2026-118-FP-B07."""
        name = f"{parameters.reception_serial_prefix}{self.serial_number}-{shipment_codes.get(self.product_type, 'ALL')}"
        return f"{name}-{self.batch_number}" if self.batch_number else name

    def gen_hwdb_datasheet(self):
        dd = super().gen_hwdb_datasheet()
        dd['purchase_order'] = dd.pop('serial_number')
        dd['product_type'] = shipment_types.get(self.product_type, self.product_type)
        dd.pop('som_serial', None)
        dd.pop('eeprom_serial', None)
        dd.pop('ambient_temperature', None)
        for k in ('run_number', 'run_type', 'follows_run', 'after_repair', 'retest_reason',
                  'som_moved_from', 'eeprom_also_on'):
            dd.pop(k, None)
        return dd


def delivery_key(purchase_order: str, product_type: str, batch: str = "") -> str:
    return "|".join((purchase_order.strip(), product_type, batch.strip()))


def already_recorded(purchase_order: str, product_type: str, batch: str = "") -> bool:
    """Checks the local log so the same delivery (order, product and batch) isn't recorded twice.
    Other products, or another batch, on the same purchase order are separate deliveries."""
    path = Path(parameters.reception_log_file)
    if not path.exists():
        return False
    key = delivery_key(purchase_order, product_type, batch)
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
    lg.info(f"Saved reception record {record.hwdb_serial}")
