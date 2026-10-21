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
                  "2. Production shipment entry (reception checks, once per delivery)\n"
                  "3. Look up a board\n4. Quit")
            sel = (await self.session.prompt_async("Choose 1, 2, 3 or 4: ")).strip()
            if sel == "1":
                serial = await self.session.prompt_async("PTC Serial Number: ")
                return {"mode": "board", "tester": self.tester_name, "serial": serial}
            if sel == "2":
                po = await self.session.prompt_async("Purchase order number: ")
                # batch is asked by the flow after the duplicate check
                return {"mode": "ship", "tester": self.tester_name, "po": po, "batch": None}
            if sel == "3":
                query = await self.session.prompt_async("Serial to look up (* matches any part): ")
                return {"mode": "lookup", "tester": self.tester_name, "query": query}
            if sel == "4":
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

    async def stopped(self, message: str, title: str | None = None) -> None:
        print(f"\n{title}: {message}" if title else message)

    async def _choose(self, title: str, options: list[tuple[str, str]]) -> str:
        print(f"\n{title}")
        for i, (_, label) in enumerate(options, 1):
            print(f"{i}. {label}")
        while True:
            sel = (await self.session.prompt_async(f"Choose 1 to {len(options)}: ")).strip()
            if sel.isdigit() and 1 <= int(sel) <= len(options):
                return options[int(sel) - 1][0]

    def _print_board(self, b: dict) -> None:
        latest = b["latest"]
        print(f"\n==== {b['serial']} ====  HWDB part: {b['part_id'] or 'none yet'}  ({b['source']})")
        if b.get("warning"):
            print(f"Note: {b['warning']}")
        print(f"SoM {b['som'] or '-'}   EEPROM {b['eeprom'] or '-'}   runs {b['runs']}   repairs {b['repairs']}"
              + (f"   latest: run {latest['n']} {latest['result']}" if latest else ""))
        for it in b["items"]:
            if it["kind"] == "run":
                print(f"  {it['date']}  {it['title']:<26} {it['result']:<6} {it['who']}"
                      + (f"  reason: {it['reason']}" if it.get("reason") else ""))
                for f in it["failed"]:
                    print(f"      failed: {f['title']}  {f['value']}  (accept {f['accept'] or '-'})")
            else:
                print(f"  {it['date']}  {it['title']:<26} {'':<6} {it['who']}")
                print(f"      fault: {it['fault'] or '-'}\n      done: {it['action'] or '-'}"
                      f"\n      parts: {it['parts'] or 'none'}")

    async def ask_retest_choice(self, board: dict) -> str:
        self._print_board(board)
        return await self._choose(f"{board['serial']} has been tested before. This run will be added to it.", [
            ("repair", "Record a repair, then retest"), ("retest", "Retest without a repair"),
            ("repair_only", "Record a repair only"), ("cancel", "Cancel")])

    async def ask_repair(self, form: dict) -> dict:
        print(f"\n--- Repair {form['n']} for {form['serial']} ---")
        for_steps = []
        for f in form["failed"]:
            if await self._yesno(f"Was this repair for '{f['title']}'?"):
                for_steps.append(f["key"])
        ask = self.session.prompt_async
        return {"repaired_by": await ask("Repaired by: ", default=form["repaired_by"]), "for_steps": for_steps,
                "fault_found": await ask("Fault found: "), "action_taken": await ask("What was done: "),
                "parts_replaced": await ask("Parts replaced (reference designators, empty if none): "),
                "notes": await ask("Notes: ")}

    async def show_board(self, board: dict) -> str:
        self._print_board(board)
        return await self._choose("What next?", [("back", "Back to the menu"), ("retest", "Retest this board"),
                                                 ("repair", "Record a repair")])

    async def pick_board(self, query: str, rows: list[dict]) -> str | None:
        if not rows:
            print(f"No boards on this station match {query}.")
            return None
        opts = [(r["serial"], f"{r['serial']:<14} {r['result']:<6} {r['date']}") for r in rows[:30]]
        return await self._choose(f"Boards matching {query}:", opts + [("", "Back")]) or None

    def set_run(self, label: str) -> None:
        print(f"\n{label}")

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

    async def ask_photo(self, step: Step, side: str, optional: bool = False):
        from ptctestsuite.utils.photos import Photo, PhotoError, from_file
        while True:
            path = (await self.session.prompt_async(
                f"{self._msg(step)}\nPath to a .jpg or .png file, or press Enter to use the camera "
                f"(space takes the photo){', or type done' if optional else ''}: ")).strip().strip('"\'')
            if optional and path.lower() == "done":
                return None
            if path:
                try:
                    return from_file(side, path)
                except PhotoError as e:
                    print(e)
                    continue
            from ptctestsuite.utils.image_capture import get_board_image
            try:
                data = await get_board_image()
            except Exception as e:   # camera missing, or the window was closed with Esc
                print(f"The camera didn't give a photo ({e}).")
                data = None
            if data:
                return Photo(side, data, "image/png", "camera")
            print("No photo was taken. Try again.")

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
