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

Each run starts by asking which kind of entry this is.

### Production board entry

One run per PTC board. The tester scans or types the board serial and their name, then the
steps follow the procedure in order. Section numbers in brackets refer to the procedure.

| Section | Steps | How the result is decided |
| --- | --- | --- |
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
uploaded to the HWDB as a "QC Test" on the board's entry, with a photo of the board.

### Production shipment entry

One run per delivery, not per board. The tester enters the purchase order and batch number, then
does the 7 reception checks from section 4.1:

- Front panels: count vs purchase order, 10% sample under the microscope with thumb screws present, 10% sample mechanical fit vs drawings
- Bare PCBs: count vs purchase order, vendor quality certificate review
- Assembled PCBs: count vs purchase order, vendor quality certificate review

The shipment goes to the same HWDB as the boards, as its own entry with serial `SHIPMENT-<PO>`
and a "Reception Check" test. It is also saved in `reception_records.jsonl`, and a second entry
for the same PO is refused.

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

## Still to confirm

- Which QC board mux (0x70–0x75) belongs to which converter. The code assumes 0x70 is converter 0. Procedures v1.4 reversed the PWM register order, so the mux order may be reversed too.
- The value that turns a QC board load off (`qc_load_off_value`, 0x0 for now).
- The LTC2945 alert defaults restored after the alert test (max VIN 0xFFF0, alerts disabled).
- The other 4 temperature sensor addresses. Only 0x48–0x4B are known.
- The AUX LED register, so that step is a manual prompt for now.
- The QC board timing lock for channels 1–5. Procedures v1.4 only gives the steps for channel 0.
- Whether shipments should get their own part type in the HWDB instead of the PTC one.
