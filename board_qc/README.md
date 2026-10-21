# PTC board QC test station

Software for testing PTC boards on the QC board and recording the results in the DUNE
hardware database (HWDB), following PTC_QC_Procedures v1.4 (`doc/PTC_QC_Procedures_v1.4.pdf`).
It has two parts:

| Folder | Runs on | What it does |
| --- | --- | --- |
| `ptctestsuite/` | the test station PC | Walks the tester through the procedure, runs the automatic tests and uploads the results |
| `ptctestclient/` | the PTC | Small websocket server (port 8765) that reads the sensors and FPGA registers for the automatic tests |

## Running it

On the test station PC, connected to the PTC and QC board:

    pip install -r ptctestsuite/requirements.txt
    python -m ptctestsuite

This opens the test station GUI in the browser at http://localhost:8080/. It walks the tester
through the procedure one step at a time, shows every step's result as it goes, and uploads the
record to the HWDB at the end. The page works without internet: its fonts are bundled in
`ptctestsuite/ui/static/fonts`. A barcode scanner works in any input box, since it types the
code and presses Enter.

| Option | What it does |
| --- | --- |
| `--terminal` | Use the original terminal prompts instead of the GUI |
| `--disable-hwdb` | Don't upload anything to the HWDB |
| `--debug` | Don't connect to the PTC or QC board; talk to a test client on localhost |
| `--port N` | GUI port (default `gui_port` in `config/parameters.py`) |
| `--no-browser` | Don't open the browser; go to the address printed in the terminal |

The PTC gets its address from DHCP: the test suite logs in over the serial port, reads the
address of `end1`, and uses it for the rest of the run. The QC board address (`qc_ip`,
192.168.20.101) is in `ptctestsuite/config/parameters.py`. The test suite starts the on-board
client over ssh with `python3 -m ptctestclient`, so the QC image on the PTC must include
`ptctestclient/` and its requirements (`ptctestclient/requirements.txt`).

## The two kinds of entry

Each run starts by asking which kind of entry this is: a production board, a production
shipment, or **Look up a board** (see Board history, retests and repairs below).

### Production board entry

One run per PTC board. The tester scans or types the board serial and their name, then the
steps follow the procedure in order. Section numbers in brackets refer to the procedure.

| Section | Steps | How the result is decided |
| --- | --- | --- |
| 4.1.3 | Photos of the front and back of the board | Saved, no pass/fail; see Board photos below |
| 4.3 | With the SoM not installed: 48V current, VP12_LOCAL, RIPPLE_0..5 voltage and switching period, LEDs | Tester enters the reading; checked against the procedure's limits |
| 4.3.2 | SoM serial (scanned from the Enclustra Data Matrix, 10 digits), insertion, boot current, LEDs, serial console, 5 repeat boots | Mixed: readings with limits, yes/no for LEDs |
| 4.5 | EEPROM ID, memory (`fillmem`), PTC and QC board IV sensors, temperature sensors | Automatic, run by the on-board client |
| 4.5.1 | Alerts, and the OVER TEMP LED | Automatic, then a yes/no for the LED |
| 4.4.1 | DC-DC load test at 25/50/75/100% on each converter, plus the RMS ripple on the scope at full load | Automatic current check (1.5/3/4.5/6 A ± 100 mA); ripple entered by the tester |
| 4.5.2 | Crate address DIP switches | Yes/no for each of the 8 switches |
| 4.5.3 | MCU programming and EtherCAT | Yes/no and lost frame count, done from the TwinCAT PC |
| 4.5.4 | Timing endpoint lock on the PTC and on the QC board (channel 0), then LEDs and round trip delay | Automatic lock checks, then tester readings |
| 4.5.5 | Ping and 1000 MB throughput test (needs > 12.5 MB/s), then LEDs | Automatic, then yes/no for the LEDs |

The load test pokes the QC board PWM registers in the v1.4 order: converter 0 is `0x8002004c`
and converter 5 is `0x80020038`. Each converter goes back to 25% right after its ripple
reading, since the procedure says not to leave loads over 50% running for more than a few
minutes.

Every reading is saved with its value and unit, not only PASS or FAIL. The record also holds
the SoM serial, EEPROM ID, room temperature, tester notes and an overall result, and it is
uploaded to the HWDB as a "QC Test" on the board's entry, with the front and back photos.

### Board photos

Every board test starts with a photo of the front and then the back, taken from the USB
camera in the GUI or chosen as image files (JPEG or PNG, up to `photo_max_mb`). Both are
uploaded to the board's HWDB entry as images with the comments "Board photo, front" and
"Board photo, back", and their file names are stored in the QC record. A copy of every photo
is kept in `board_photos/` on the station whatever happens to the upload.

To photograph every board in the same position, the GUI lays a ghost image of each side over
the live camera view, with an opacity slider. There is no ghost the first time: the first
good photo of each side is offered as the ghost (the "Save as the ghost" box is ticked).
After that the box offers to replace it. The tester can also set a ghost from a file or remove
it from the photo step at any time. Ghosts are kept in `ghost_images/` as `front.jpg` and
`back.jpg` (or `.png`).

The camera works when the page is opened at `http://localhost` on the station itself, which
is what `python -m ptctestsuite` does. The browser asks once for permission to use it. If the
PC has more than one camera, pick the right one in the Camera list; the choice is
remembered. Keys: Space takes the photo, Enter uses it.

In `--terminal` mode the tester types the path of an image file, or presses Enter to use the
older OpenCV camera window (Space takes the photo). There is no ghost image there.

### Production shipment entry

One run per delivery, not per board. The tester enters the purchase order and batch number, then
does the 7 reception checks from section 4.1:

- Front panels: count vs purchase order, 10% sample under the microscope with thumb screws present, 10% sample mechanical fit vs drawings
- Bare PCBs: count vs purchase order, vendor quality certificate review
- Assembled PCBs: count vs purchase order, vendor quality certificate review

The shipment goes to the same HWDB as the boards, as its own entry with serial `SHIPMENT-<PO>`
and a "Reception Check" test. It is also saved in `reception_records.jsonl`, and a second entry
for the same PO is refused.

## Board history, retests and repairs

The PTC serial number is how every board is found, and each serial has exactly one HWDB entry.
Every run and every repair of a board is added to that entry; nothing is ever overwritten.

**Scanning a serial that was tested before.** Before testing, the program searches the HWDB
for the serial (and this station's records):

- Not found: a new board. Its HWDB entry is created when the results are uploaded.
- Found once: the tester sees the earlier runs and what failed, and chooses **Record a repair,
  then retest**, **Retest without a repair** (they are asked why), **Record a repair only**, or
  **Cancel**. The run is uploaded to the same HWDB entry as the next run number, with its run
  type, the run it follows and the repair it follows. A retest is always the full test. Photos
  are retaken after a repair (the board changed) and skipped on a retest without one.
- Found more than once: the program stops. Someone with HWDB admin rights has to remove or merge
  the extra entry first. The program never creates a second entry for a serial, and checks again
  just before uploading.

**Repairs** are their own HWDB record (test type `Repair`, set by `repair_test_type`) on the
board's entry: who repaired it, after which run, which failed steps it was for, the fault found,
what was done, the parts replaced, notes, and up to `max_repair_photos` close-up photos. **The
`Repair` test type has to be added to the PTC component type by an HWDB admin.** Until it is,
repairs are kept on the station only and the screen says why.

**Look up a board** shows a board's whole history, newest first: each run with its result,
failed steps (or all steps), photos and notes, and each repair. From there the tester can retest
the board or record a repair. The start screen lists boards **waiting for a retest** (the latest
run failed, or the board was repaired since) and boards **recently tested** on this station.
Search with `*` to match part of a serial.

**One SoM, one EEPROM per board.** If a scanned SoM serial was already recorded on another PTC,
the tester is warned and can keep it (the move is noted as `SoM Moved From`) or scan again. A
repeated EEPROM ID is noted (`EEPROM Also On`) and the tester is asked to tell an engineer.

This station keeps its own record of every board in `board_records/` (one JSON file per serial).
It feeds the lookup lists and the SoM and EEPROM checks, and shows a board's history when the
HWDB can't be reached. The HWDB stays the master copy.

**Checking the dev HWDB.** `python -m ptctestsuite.hwdb_check` creates one throwaway board on
the dev HWDB and checks that the serial search works, that a second QC Test record is kept
alongside the first, whether the `Repair` test type exists, and that photos attach. It refuses
to run against the production HWDB.

## The HWDB

The HWDB address (`dune_hwdb_api_path`, the development database by default), the PTC part type
(`ptc_part_type_id`) and the token file (`bearer_token_path`) are in `config/parameters.py`. The
token comes from `htgettoken`, which the test suite runs when the token needs renewing.

Before each run starts, the test station checks that it can reach the HWDB. If it can't (no
network, an expired token, or the HWDB returns an error), the tester is told why and can stop or
carry on without it. If an upload fails at the end of a run, the screen says so and why, and
the record is kept in `unuploaded_results.jsonl` (boards) or `reception_records.jsonl`
(shipments) so it can be uploaded later.

## Trying it without hardware

In one terminal, start the fake PTC, which answers every automatic test with made-up readings:

    python -m ptctestsuite.fake_ptc                       # everything passes
    python -m ptctestsuite.fake_ptc --fail temperature    # make chosen tests fail

In another:

    python -m ptctestsuite --debug --disable-hwdb

## How it fits together

- `flow.py` is the procedure: the board test and the shipment entry. It never prompts directly;
  it asks a tester interface for each answer.
- `ui/terminal.py` and `ui/gui.py` are the two tester interfaces. The GUI serves
  `ui/static/index.html` and keeps the screen state in Python, so refreshing or reopening the
  page during a test picks up where it was.
- `config/test_names.py` lists every manual step with its procedure section, limits and unit.
  A step with limits asks only for the reading and decides PASS or FAIL itself.
- `utils/hwdb.py` talks to the HWDB, `utils/reception.py` holds the shipment record and
  `utils/qc_board.py` sets the QC board loads.
- Window title and station label are `gui_title` and `gui_station` in `config/parameters.py`.
  Colors and layout are the variables at the top of `ui/static/index.html`, with the same
  names as the PTC QC GUI designer summary.

## Changing the look: the GUI designer

[`ptctestsuite/ui/designer/ptc-gui-designer.html`](ptctestsuite/ui/designer/ptc-gui-designer.html)
is a standalone page for trying out the GUI's look. Open it in any browser by double-clicking it;
it doesn't need the test station running. It shows a working preview of the board and shipment
steps, with presets, color pickers and layout options. Your changes are remembered in that
browser.

When it looks right, press **Copy summary**. Then copy each color and option from the summary
into the matching `--g-…` variable at the top of `ui/static/index.html`. The "Lab dark" preset
matches the GUI as it is now. The preview doesn't include the board photo step, and it loads
its own fonts from Google Fonts, so it needs internet to look exactly right.

## Still to confirm

- Which QC board mux (0x70–0x75) belongs to which converter. The code assumes 0x70 is converter 0. Procedures v1.4 reversed the PWM register order, so the mux order may be reversed too.
- The value that turns a QC board load off (`qc_load_off_value`, 0x0 for now).
- The LTC2945 alert defaults restored after the alert test (max VIN 0xFFF0, alerts disabled).
- The other 4 temperature sensor addresses. Only 0x48–0x4B are known.
- The AUX LED register, so that step is a manual prompt for now.
- The QC board timing lock for channels 1–5. Procedures v1.4 only gives the steps for channel 0.
- Whether shipments should get their own part type in the HWDB instead of the PTC one.
- That the HWDB keeps every QC Test record of a board (`python -m ptctestsuite.hwdb_check`), and
  that an HWDB admin has added the `Repair` test type to the PTC component type.
