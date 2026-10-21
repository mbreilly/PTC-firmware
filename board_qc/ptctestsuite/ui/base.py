"""The tester interface the test flow talks to.

The flow in ptctestsuite.flow never prompts directly. It asks a TesterUI for each
reading or answer, so the same flow runs in the terminal (TerminalUI) and in the
browser GUI (GuiUI).
"""

import re
from dataclasses import dataclass, asdict

from ptctestsuite.utils.qc_result import qc_result


class TestAborted(Exception):
    """The tester stopped the run. Nothing is uploaded."""


@dataclass
class Step:
    """One thing the tester does or watches, shown as a row in the GUI step list."""
    key: str                      # result key in the QC record
    title: str                    # short name for the step list
    section: str = ""             # procedure section, e.g. "4.3.1"
    prompt: str = ""              # instruction shown to the tester
    group: str = ""               # heading in the step list
    kind: str = "manual"          # manual, auto, scan, counts, number, notes, photo
    limits: tuple | None = None   # (lo, hi); hi may be None for "more than lo"
    unit: str | None = None
    how: list | None = None       # "How to run this test": short instructions, one per line
    hidden: bool = False          # recorded and shown in the results, but not listed on its own in the step list

    @property
    def acceptance(self) -> str | None:
        unit = f" {'µs' if self.unit == 'us' else self.unit}" if self.unit else ""
        if self.kind == "yesno":
            return "Yes"   # every yes/no question is worded so that Yes is the good answer
        if self.limits is None:
            return None
        lo, hi = self.limits
        if hi is None:
            return f"More than {_num(lo)}{unit}"
        if lo == hi:
            return f"{_num(lo)}{unit}"
        places = max(_places(lo), _places(hi))
        return f"{_num(lo, places)}–{_num(hi, places)}{unit}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["acceptance"] = self.acceptance
        return d

    @classmethod
    def from_man_test(cls, t: dict, group: str = "") -> "Step":
        """Builds a step from a man_test() dict in config.test_names."""
        section, prompt = split_section(t["test_message"])
        if t.get("limits") is not None:
            kind = "number"
        elif t.get("accepts_value"):
            kind = "judged"
        else:
            kind = "yesno"
        return cls(key=t["test_name"], title=step_title(t["test_name"]), section=section, prompt=prompt,
                   group=group, kind=kind, limits=t.get("limits"), unit=t.get("unit"))


def _places(x) -> int:
    text = repr(x)
    return len(text.split(".")[1]) if "." in text else 0

def _num(x, places: int | None = None) -> str:
    """12.0 -> '12.0', 12.35 -> '12.35', 100 -> '100', with a fixed number of places if given."""
    return f"{x:.{_places(x) if places is None else places}f}"


_SECTION = re.compile(r"^\[([^\]]+)\]\s*(.*)$", re.S)

def split_section(message: str) -> tuple[str, str]:
    """'[4.3.1] Measure X' -> ('4.3.1', 'Measure X')"""
    m = _SECTION.match(message)
    return (m.group(1), m.group(2)) if m else ("", message)


_TITLES = {
    "bare_power": "48 V input current, no SoM",
    "vp12_local": "VP12_LOCAL voltage",
    "local_led_12v": "12V LOCAL LED",
    "som_serial": "Scan SoM serial",
    "som_insertion": "SoM insertion",
    "boot_current": "Boot current",
    "amber_led_blinking": "SoM amber LED",
    "12v_local_led_boot": "12V LOCAL LED after boot",
    "pg_led_boot": "PG LED",
    "fpga_done_led_boot": "FPGA DONE LED",
    "serial_connection": "Serial console login",
    "repeat_boots": "Repeat boot, 5 cycles",
    "ambient_temperature": "Room temperature",
    "eeprom": "EEPROM read",
    "iv_sensors": "PTC voltage and current sensors",
    "qc_iv_sensors_25pct": "QC board sensors at 25% load",
    "temperature": "Temperature sensors",
    "alert": "Sensor alerts",
    "over_temp_led": "OVER TEMP LED",
    "timing": "Timing lock",
    "timing_link_led": "Timing LINK LED",
    "timing_rx_led": "RX LED",
    "timing_rtt": "Timing round trip",
    "timing_tx_led": "TX LED",
    "gbe_ping": "Ethernet ping",
    "gbe_throughput": "Ethernet throughput",
    "gbe_link_led": "GbE LINK LED",
    "aux_led": "AUX LED",
    "mcu_program_jtag": "Program MCU over JTAG",
    "mcu_program_insitu": "Program MCU in situ",
    "ecat_link_led": "EtherCAT LINK LED",
    "ecat_lost_frames": "EtherCAT lost frames",
    "ecat_debug_leds": "EtherCAT debug LEDs",
    "ecat_run_led": "ECAT RUN LED",
    "front_panels_count_vs_po": "Front panel count",
    "fp_microscope_sample": "Front panel microscope sample",
    "fp_mechanical_fit_sample": "Front panel fit sample",
    "bare_pcbs_count_vs_po": "Bare PCB count",
    "bare_pcb_certificate_review": "Bare PCB vendor certificate",
    "assembled_pcbs_count_vs_po": "Assembled PCB count",
    "assembled_pcb_certificate_review": "Assembled PCB vendor certificate",
    "batch_number": "Batch number",
    "notes": "Notes and finish",
    "photo_front": "Front photo",
    "photo_back": "Back photo",
    "retest_reason": "Reason for the retest",
}
_PATTERNS = [
    (re.compile(r"^ripple(\d)$"), lambda m: f"DC-DC {m[1]} output"),
    (re.compile(r"^ripple(\d)_switch_period$"), lambda m: f"DC-DC {m[1]} switching period"),
    (re.compile(r"^ripple(\d)_full_load$"), lambda m: f"DC-DC {m[1]} ripple at full load"),
    (re.compile(r"^wib(\d)_led$"), lambda m: f"WIB {m[1]} LED"),
    (re.compile(r"^load(\d)_(\d+)pct$"), lambda m: f"DC-DC {m[1]} load at {m[2]}%"),
    (re.compile(r"^crate_addr_(\d)$"), lambda m: f"Crate address switch {int(m[1]) + 1}"),
]

def step_title(key: str) -> str:
    if key in _TITLES:
        return _TITLES[key]
    for pat, fn in _PATTERNS:
        m = pat.match(key)
        if m:
            return fn(m)
    return key.replace("_", " ").capitalize()


def format_value(value, unit: str | None = None) -> str:
    """Readable one-line form of a stored value."""
    if value is None:
        return ""
    def num(v):
        return int(v) if isinstance(v, float) and v.is_integer() else v
    if isinstance(value, dict):
        text = ", ".join(f"{k}={num(v)}" for k, v in value.items())
    elif isinstance(value, float):
        text = f"{value:g}"
    else:
        text = str(value)
    shown = "µs" if unit == "us" else unit
    return f"{text} {shown}" if unit and not isinstance(value, dict) else text


class TesterUI:
    """What the test flow needs from a user interface.

    Methods that wait for the tester are async. Methods that only report progress
    are plain functions and must not block.
    """

    # --- screens -------------------------------------------------------------
    async def start(self) -> dict:
        """Returns {"mode": "board" | "ship" | "lookup" | "quit", "tester": str,
        "serial": str, "po": str, "batch": str | None, "query": str}."""
        raise NotImplementedError

    def begin(self, mode: str, ident: str, tester: str, plan: list[Step]) -> None:
        """A board test or shipment entry has started; plan is every step in order."""

    def summary(self, record) -> None:
        """All steps done, before notes and upload."""

    async def finish(self, record, upload_message: str, upload_ok: bool | None) -> None:
        """Show the final result and wait until the tester is ready for the next one."""
        raise NotImplementedError

    async def stopped(self, message: str, title: str | None = None) -> None:
        """The run could not continue. Show why and wait to go back to the start."""
        raise NotImplementedError

    # --- questions -----------------------------------------------------------
    async def ask_number(self, step: Step) -> float:
        raise NotImplementedError

    async def ask_yesno(self, step: Step) -> bool:
        raise NotImplementedError

    async def ask_judged(self, step: Step) -> tuple[bool, str]:
        """A reading with no fixed limits: the tester enters it and decides pass or fail."""
        raise NotImplementedError

    async def ask_text(self, step: Step, default: str = "") -> str:
        raise NotImplementedError

    async def ask_counts(self, step: Step) -> tuple[float, float]:
        """Quantity ordered and quantity received."""
        raise NotImplementedError

    async def ask_notes(self) -> str:
        raise NotImplementedError

    async def ask_checklist(self, step: Step, items: list[dict], network: dict, previous: dict | None = None) -> dict:
        """The test stand checklist. items are config.test_names.prep_checklist; network is the
        program's check of the QC board ({"ok": bool, "detail": str}). Returns {"ticks": {key: True},
        "voltage": float, "current": float}, or {"recheck": True} to run the network check again."""
        raise NotImplementedError

    async def ask_inspection(self, step: Step, result) -> dict:
        """The orientation check of a board photo (result is utils.inspection.Inspection). Returns
        {"answers": {ref: "correct" | "reversed"}} for the flagged parts, {"retake": True} to take
        the photo again, or {"skip": True} to carry on without the check when it couldn't run."""
        raise NotImplementedError

    async def after_auto(self, step: Step, result: qc_result, value_text: str) -> None:
        """An automatic test has finished. The GUI shows its result and waits for Next test."""

    async def ask_photo(self, step: Step, side: str, optional: bool = False):
        """A photo: "front" or "back" of the board (with a ghost image), or a "closeup" of a defect or
        repair. Returns utils.photos.Photo, or None if optional and the tester has no more photos."""
        raise NotImplementedError

    # --- boards tested before ------------------------------------------------------
    async def ask_retest_choice(self, board: dict) -> str:
        """The scanned serial has runs already (board is BoardHistory.view()). Returns "repair"
        (record a repair, then retest), "retest" (no repair), "repair_only" or "cancel"."""
        raise NotImplementedError

    async def ask_repair(self, form: dict) -> dict:
        """The repair record. form has serial, n, after_run, after_date, repaired_by and failed
        ([{key, title}]). Returns {repaired_by, for_steps: [keys], fault_found, action_taken,
        parts_replaced, notes}."""
        raise NotImplementedError

    async def show_board(self, board: dict) -> str:
        """A board's history for the lookup. Returns "retest", "repair" or "back"."""
        raise NotImplementedError

    async def pick_board(self, query: str, rows: list[dict]) -> str | None:
        """Several boards match a search. Returns the chosen serial, or None to go back."""
        raise NotImplementedError

    def set_run(self, label: str) -> None:
        """This run is a retest, e.g. "Run 2, after repair 1"."""

    async def instruct(self, title: str, text: str) -> None:
        """Tell the tester to do something and wait until they say it's done."""
        raise NotImplementedError

    async def confirm(self, title: str, text: str, yes: str = "Yes", no: str = "No") -> bool:
        raise NotImplementedError

    # --- progress ------------------------------------------------------------
    def running(self, step: Step) -> None:
        """An automatic test has started."""

    def result(self, key: str, result: qc_result, value=None, unit: str | None = None, limits=None) -> None:
        """A result was recorded."""

    def saved(self, key: str, value) -> None:
        """A value was stored that has no pass or fail (e.g. a serial number)."""

    def skipped(self, keys: list[str]) -> None:
        """Steps that won't run this time."""

    def status(self, text: str) -> None:
        """What the program is doing now, e.g. connecting to the PTC."""
