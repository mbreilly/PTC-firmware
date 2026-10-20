"""The original prompt_toolkit terminal interface, behind the TesterUI interface."""

import prompt_toolkit as ptk
from prompt_toolkit.shortcuts import input_dialog

from ptctestsuite.ui.base import TesterUI, Step, format_value
from ptctestsuite.utils.qc_result import qc_result


class TerminalUI(TesterUI):
    def __init__(self):
        self.session = ptk.PromptSession()
        self.tester_name: str | None = None

    def _msg(self, step: Step) -> str:
        return f"[{step.section}] {step.prompt}" if step.section else step.prompt

    async def _yesno(self, message: str) -> bool:
        ans = await self.session.prompt_async(message + " (y/n): ")
        return ans.strip().lower() in ("y", "yes")

    async def _float(self, message: str) -> float:
        while True:
            ans = await self.session.prompt_async(message)
            try:
                return float(ans.strip())
            except ValueError:
                print("Please enter a number.")

    async def start(self) -> dict:
        if self.tester_name is None:
            self.tester_name = await self.session.prompt_async("Tester Name: ")
        while True:
            print("\n1. Production board entry (test a PTC)\n"
                  "2. Production shipment entry (reception checks, once per delivery)\n3. Quit")
            sel = (await self.session.prompt_async("Choose 1, 2 or 3: ")).strip()
            if sel == "1":
                serial = await self.session.prompt_async("PTC Serial Number: ")
                return {"mode": "board", "tester": self.tester_name, "serial": serial}
            if sel == "2":
                po = await self.session.prompt_async("Purchase order number: ")
                # batch is asked by the flow after the duplicate check
                return {"mode": "ship", "tester": self.tester_name, "po": po, "batch": None}
            if sel == "3":
                return {"mode": "quit"}

    def summary(self, record) -> None:
        print(f"\n==== {record.serial_number} summary ====")
        for name, t in record.test_status.items():
            value = format_value(t["value"])
            print(f"{t['result'].name:6} {name}" + (f": {value}" if value else ""))
        print(f"Overall: {record.overall_result.name}\n")

    async def finish(self, record, upload_message: str, upload_ok: bool | None) -> None:
        if upload_message:
            print(upload_message)

    async def stopped(self, message: str) -> None:
        print(message)

    async def ask_number(self, step: Step) -> float:
        if step.limits is None:
            unit = f" ({step.unit})" if step.unit else ""
            return await self._float(f"{self._msg(step)}{unit}: ")
        lo, hi = step.limits
        unit = f" {step.unit}" if step.unit else ""
        rng = f"> {lo}" if hi is None else f"{lo}-{hi}"
        return await self._float(f"{self._msg(step)} [{rng}{unit}]: ")

    async def ask_yesno(self, step: Step) -> bool:
        return await self._yesno(self._msg(step))

    async def ask_judged(self, step: Step) -> tuple[bool, str]:
        ok = await self._yesno(self._msg(step))
        unit = f" ({step.unit})" if step.unit else ""
        value = await self.session.prompt_async(f"What was the value of the tested parameter{unit}? ")
        return ok, value

    async def ask_text(self, step: Step, default: str = "") -> str:
        return await self.session.prompt_async(f"{self._msg(step)}: ", default=default)

    async def ask_counts(self, step: Step) -> tuple[float, float]:
        print(f"\n--- {step.title} ---")
        ordered = await self._float(f"{step.title}: quantity on the purchase order: ")
        received = await self._float(f"{step.title}: quantity received: ")
        return ordered, received

    async def ask_notes(self) -> str:
        if not await self._yesno("Do you want to add notes?"):
            return ""
        text = await input_dialog(title="Notes", text="Enter tester notes here:").run_async()
        return text or ""

    async def instruct(self, title: str, text: str) -> None:
        await self.session.prompt_async(f"{text} Press Enter when ready.")

    async def confirm(self, title: str, text: str, yes: str = "Yes", no: str = "No") -> bool:
        return await self._yesno(text)

    def running(self, step: Step) -> None:
        print(f"Running {step.key}")

    def result(self, key, result, value=None, unit=None, limits=None) -> None:
        print(f"  -> {result.name}")

    def status(self, text: str) -> None:
        print(text)
