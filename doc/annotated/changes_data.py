"""Single list of changes used for both annotated outputs.

Each change has:
  id     -- C1, C2, ... (same id in the marked-up original PDF and in the LaTeX version)
  cat    -- NEW, CHANGED, MOVED, OPEN, EDIT or INFO
  page   -- page of PTC_QC_Procedures_v1.4.pdf where the anchor is (1-based)
  anchor -- short text on that page that the note points at (one line, no underscores)
  title  -- short label for the LaTeX margin tag
  text   -- full note, plain text (escaped for LaTeX by gen_notes_tex.py)

Source of the changes: reports/PTC-production-changes-report.pdf (31 Oct 2026), the
board_qc test station in this repository, and the station work on the lab Pi.
"""

CATEGORIES = {
    # name: (label, RGB 0..1)
    "NEW": ("New", (0.05, 0.50, 0.20)),
    "CHANGED": ("Changed", (0.45, 0.10, 0.65)),
    "MOVED": ("Moved", (0.85, 0.45, 0.00)),
    "OPEN": ("Open item", (0.80, 0.00, 0.35)),
    "EDIT": ("Editorial", (0.45, 0.35, 0.20)),
    "INFO": ("Note", (0.35, 0.40, 0.45)),
}

CHANGES = [
    dict(id="C1", cat="INFO", page=1, anchor="Integrated procedure for automated tests",
         title="About these annotations",
         text="This copy marks how the procedure is now carried out by the Penn PTC production "
              "test station (work of 19-30 Oct 2026). Green = new step or record, purple = changed, "
              "orange = moved, red = open item to confirm, brown = editorial issue found in v1.4, "
              "grey = note. Status: the station has been tested against simulated hardware only; "
              "the first run on a real PTC, QC board and the HWDB is still to come."),
    dict(id="C2", cat="CHANGED", page=3, anchor="The procedure includes three main stages",
         title="Two flows: shipment and board",
         text="The station splits the work into two flows: a Production shipment entry, once per "
              "delivery (counts, certificates, samples), and a Production board run, once per PTC "
              "(serial, photos, orientation check, stand checklist, manual and automatic tests, "
              "overall result)."),
    dict(id="C3", cat="CHANGED", page=4, anchor="Digital camera capable of 12MP",
         title="Camera driven by the station",
         text="Board photos are now taken from the station: a Canon EOS Rebel T7 (24 MP) over USB "
              "with gphoto2, a webcam, or a file. A faint 'ghost' of a reference board helps line "
              "every shot up the same way. Camera ordered 26 Oct 2026, not yet in use."),
    dict(id="C4", cat="CHANGED", page=4, anchor="Code Scanner",
         title="Scanner reads the new labels",
         text="The scanner also reads the printed PTC### DataMatrix serial labels and the Enclustra "
              "SoM Data Matrix. It works in any input box of the station GUI (it types the code and "
              "presses Enter)."),
    dict(id="C5", cat="NEW", page=4, anchor="List of visual inspection components",
         title="Label printer, reference board",
         text="New equipment: Brother QL-810W label printer (29 mm continuous tape) for 10 mm "
              "DataMatrix PTC serial labels, and a known-good reference board whose photos are the "
              "baseline for the automated orientation (AOI) check."),
    dict(id="C6", cat="CHANGED", page=6, anchor="For test scripts, timing server, HWDB",
         title="Linux PC runs the station GUI",
         text="The Linux machine runs the PTC QC Test Station: 'python -m ptctestsuite' opens the "
              "GUI in a browser at localhost:8080. The page works without internet."),
    dict(id="C7", cat="NEW", page=6, anchor="Microcontroller programming pod",
         title="Lab Raspberry Pi server",
         text="New: the lab Raspberry Pi server ('PartsDB') hosts the start page, label printing, "
              "the AOI Parts Mapper and the Part-DB label scan station, served by Apache on the lab "
              "network."),
    dict(id="C8", cat="MOVED", page=8, anchor="The overall operation procedure consists of 4 phases",
         title="New order of the steps",
         text="Order in the station: serial scan first; photos and orientation check at the start "
              "of each board run (off the stand, no SoM, before heatsinks); room temperature entered "
              "before the automatic tests; EEPROM, memory and sensor tests before the DC-DC load "
              "test; MCU and EtherCAT last (done from the Windows PC)."),
    dict(id="C9", cat="CHANGED", page=8, anchor="For all visual inspections",
         title="Reception once per delivery",
         text="4.1.1-4.1.3 are recorded once per delivery, not per board, in a Production shipment "
              "entry: tester, purchase order and batch, then the product (front panels, bare PCBs or "
              "assembled PCBs); only that product's checks are shown. It is its own HWDB entry in "
              "the same database as the boards, and a second entry for the same PO is refused."),
    dict(id="C10", cat="NEW", page=8, anchor="Verify that the correct number of panels",
         title="Counts and front panel photo",
         text="The station records quantity ordered and quantity received. New: a front panel "
              "photo with the ghost overlay, taken after the count."),
    dict(id="C11", cat="CHANGED", page=8, anchor="The front panels are not tracked in the DUNE HWDB",
         title="Front panel deliveries in HWDB",
         text="Front panels are still not serialized, but each delivery is now in the HWDB as a "
              "shipment entry with its count, sample results, photo and notes."),
    dict(id="C12", cat="NEW", page=10, anchor="Verify that the correct number of PCBs has been",
         title="Bare PCB photos",
         text="New: front and back photos of the bare PCB delivery, taken in the shipment entry."),
    dict(id="C13", cat="CHANGED", page=10, anchor="Make a copy of QC certificates",
         title="Certificates uploaded by station",
         text="Certificate files (PDF, Excel, PNG or JPEG) are uploaded through the shipment entry, "
              "before the review result is recorded, instead of being uploaded to the HWDB by hand."),
    dict(id="C14", cat="INFO", page=10, anchor="Inspect the Sample Boards under the microscope",
         title="Sample checklist stays on paper",
         text="Unchanged: the bare PCB sample microscope checklist and the sticker stay on the "
              "GoogleDoc form and paper; they are not in the station."),
    dict(id="C15", cat="MOVED", page=11, anchor="Take a high resolution photograph",
         title="Board photos at start of run",
         text="Moved to the start of each board run: front photo, then the front orientation "
              "check; back photo, then the back check (skipped on a retest, the first photos stand). "
              "Photos go to the board's own HWDB entry, replacing the old single webcam snapshot."),
    dict(id="C16", cat="NEW", page=11, anchor="Incorrect orientation of ICs and polarized",
         title="Automated orientation check",
         text="New automated orientation check (AOI): after each photo, every polarised part "
              "(tantalum and polymer capacitors, diodes, LEDs, ICs), placed from the board's ODB++ "
              "design and BOM, is compared with the reference board. The tester confirms any part "
              "that is flagged. Each check is kept by the AOI Parts Mapper (MariaDB 'aoimap')."),
    dict(id="C17", cat="MOVED", page=12, anchor="All boards, whether pass or fail",
         title="Serial scan moved to the run",
         text="The serial scan moved to the first step of each board run, from a printed PTC### "
              "DataMatrix label."),
    dict(id="C18", cat="EDIT", page=12, anchor="Any bare PCBs rejected from the visual inspection",
         title="Says 'bare' in 4.1.3",
         text="Editorial: this paragraph closes 4.1.3 (assembled PCBs) but says 'bare PCBs' and "
              "'Rejected bare PCBs'. Probably meant assembled PCBs / 'Rejected Assembled PCBs'."),
    dict(id="C19", cat="NEW", page=14, anchor="Preparing a DUT for Testing",
         title="Labels and start of the run",
         text="New before testing: PTC### labels printed in batches from the start page ('Print "
              "labels for new boards' proposes the next serials not in the HWDB, not on the station "
              "and not printed before; 10 mm DataMatrix on the QL-810W; logged). New first step of a "
              "run: tester name and serial scan, HWDB connection check, board lookup (new board, "
              "retest with a reason, or repair record). OPEN: PTC001-style serial format not "
              "formally confirmed."),
    dict(id="C20", cat="CHANGED", page=14, anchor="make sure all cables are plugged in",
         title="Stand checklist recorded",
         text="4.2.3 is now a checklist of 8 rows saved one by one: cables, PTC seated, QC board "
              "powered (24 V supply voltage and current read off the display), QC board on the "
              "network (checked by the program over SSH), fans, SD card, jumpers JT9-JT11, DIP "
              "switch film."),
    dict(id="C21", cat="OPEN", page=14, anchor="about 400mA",
         title="QC board supply limits",
         text="The procedure says 'about'. The station uses 23.5-24.5 V and 350-450 mA for the QC "
              "board supply. To be confirmed or replaced with agreed limits."),
    dict(id="C22", cat="EDIT", page=15, anchor="It should come up as 192.168.200.10",
         title="Two sets of IP addresses",
         text="Editorial: here the QC board is 192.168.200.10 and in 4.5.5 the DUT is "
              "192.168.200.12, but 4.5 and the station (parameters.py) use PTC 192.168.20.100 and "
              "QC board 192.168.20.101. One set should be chosen."),
    dict(id="C23", cat="MOVED", page=15, anchor="Finally, scan the DUT serial number",
         title="Serial scan is now step 1",
         text="Moved to the very first step of the board run, so every later step (photos "
              "included) is filed under the serial and the station can tell a new board from a "
              "retest or repair before work starts. One HWDB entry per serial."),
    dict(id="C24", cat="CHANGED", page=16, anchor="The PTC without SoM installed should consume",
         title="4.3.1 readings saved",
         text="The 4.3.1 readings are typed into the station, all on one page. Each is checked "
              "against the limits and saved with value, unit and limits (previously not recorded). "
              "'Next test' unlocks only when the page is complete."),
    dict(id="C25", cat="CHANGED", page=16, anchor="Repeat with each of the other 5 DC-DC",
         title="18 converter values saved",
         text="All 18 values (RIPPLE_n voltage, switching period and WIB_n LED for six converters) "
              "are saved in the HWDB."),
    dict(id="C26", cat="CHANGED", page=16, anchor="Scan the Enclustra module QR code",
         title="SoM serial validated",
         text="The Enclustra code is a Data Matrix holding only the 10-digit serial (e.g. "
              "2503804780). The station checks for 10 digits and asks for confirmation otherwise, so "
              "a PTC label scanned by mistake is caught. Saved in the record header."),
    dict(id="C27", cat="NEW", page=17, anchor="Initially, PTC will consume about 100-200mA",
         title="Boot current, room temperature",
         text="Boot current is now recorded (no limit set; left to the tester, OPEN). New on this "
              "page: the room (ambient) temperature, entered here and used as the reference for the "
              "+/-5 C temperature check in 4.5.1. The procedure never said where it comes from."),
    dict(id="C28", cat="CHANGED", page=18, anchor="Repeat the bootup procedure 5 times",
         title="Good boots out of 5",
         text="The number of good boots out of 5 is recorded."),
    dict(id="C29", cat="MOVED", page=19, anchor="DC-DC Converter Load Test",
         title="Load test automatic, after sensors",
         text="Now automatic and run after the sensor and EEPROM tests: converter by converter the "
              "station sets 25/50/75/100% load and checks 1.5/3/4.5/6 A +/-100 mA, the tester "
              "enters the RMS ripple at full load, then that converter's load is turned back down "
              "(in line with the warning about loads over 50%). 30 values saved."),
    dict(id="C30", cat="OPEN", page=19, anchor="correspond to converters 1 through 5",
         title="QC board mux and load-off value",
         text="The station follows v1.4's reversed registers (converter 0 = 0x8002004c). To "
              "confirm: which QC board sensor mux (0x70-0x75) belongs to which converter, whether it "
              "is reversed too, and the value that turns a load off (0x0 assumed)."),
    dict(id="C31", cat="CHANGED", page=19, anchor="Automated Test Setup",
         title="Guided GUI for the whole run",
         text="The station walks the tester through the whole procedure in a browser GUI: "
              "'python -m ptctestsuite' opens localhost:8080 ('--terminal' gives the old prompts, "
              "'--disable-hwdb' skips uploads, '--debug' talks to the fake PTC). Every step has "
              "'How to run this test' instructions."),
    dict(id="C32", cat="NEW", page=20, anchor="Authenticate to the HWDB",
         title="HWDB connection check",
         text="Before each run the station checks it can reach the HWDB and says why if not (no "
              "network, expired token, HWDB error); the tester can stop or carry on. It points at the "
              "development HWDB (cdbdev) by default. OPEN: htgettoken needs a Fermilab account the "
              "team does not have yet."),
    dict(id="C33", cat="CHANGED", page=20, anchor="IV sensors on PTC, IV sensors on QC board",
         title="Automatic test list",
         text="Automatic tests now: EEPROM, memory, PTC and QC board V/I sensors (QC board at 25% "
              "load), temperatures, sensor alerts (ported from alert_assert.py), timing lock, DC-DC "
              "load on all six converters, GbE ping and throughput. Each sends its readings back "
              "with its result."),
    dict(id="C34", cat="CHANGED", page=20, anchor="Manual tests include ethercat, GbE",
         title="Manual steps defined",
         text="The manual steps ('TBD') are now defined: 4.2.3 checklist, 4.3.1 and 4.3.2 readings, "
              "ripple, OVER TEMP LED, 8 crate-address switches, MCU and EtherCAT, timing LEDs and "
              "round trip, Ethernet LEDs. A step with limits asks only for the number and decides "
              "PASS/FAIL itself."),
    dict(id="C35", cat="CHANGED", page=20, anchor="Confirm upload",
         title="Upload: photos, overall result",
         text="The upload carries front and back photos instead of one webcam snapshot, and an "
              "overall result (PASS only if every row passed). Failed uploads are kept in "
              "unuploaded_results.jsonl and the screen no longer claims success. Each run carries "
              "tester, date and run number; retests and repairs stay under the same serial."),
    dict(id="C36", cat="CHANGED", page=20, anchor="(to be written)",
         title="No separate parser needed",
         text="No separate parser is needed: the on-board test client reads every sensor and sends "
              "the readings back; each is checked against these limits and saved in the HWDB."),
    dict(id="C37", cat="OPEN", page=21, anchor="All 8 temperature sensors should read close",
         title="Only 4 of 8 temp sensors",
         text="The station reads the 4 sensors with known addresses (0x48-0x4B); the other 4 "
              "addresses are still to be found. 'Ambient' is the room temperature entered on the SoM "
              "page."),
    dict(id="C38", cat="CHANGED", page=21, anchor="program a threshold such that the ALERT pin",
         title="Alert test automatic",
         text="The alert test is now one of the automatic tests. Bug fixed on the way: "
              "alert_assert.py read register 0x80020104 instead of 0x80020108. OPEN: confirm the "
              "defaults restored after the test (max VIN 0xFFF0, alerts disabled)."),
    dict(id="C39", cat="CHANGED", page=22, anchor="For each of the 8 DIP switches",
         title="8 switches saved",
         text="Each of the 8 crate address switches is a yes/no saved in the HWDB."),
    dict(id="C40", cat="MOVED", page=22, anchor="This will read the globally unique serial ID",
         title="EEPROM automatic, moved up",
         text="The EEPROM read is automatic and moved up with the other automatic tests. The serial "
              "ID (previously read and then discarded) is saved in the record header."),
    dict(id="C41", cat="MOVED", page=22, anchor="Microcontroller Tests",
         title="MCU/EtherCAT moved to the end",
         text="Moved to the end of the board run: these steps are done from the Windows PC (DAVE, "
              "TwinCAT), so they are grouped instead of breaking up the station steps. Programming, "
              "LINK/RUN LEDs and lost frames are recorded."),
    dict(id="C42", cat="CHANGED", page=23, anchor="Timing lock on PTC",
         title="Timing lock automatic",
         text="The PTC timing lock is checked automatically; the QC board lock (new in v1.4) is its "
              "own step. LINK/RX/TX LEDs and the round trip are entered by the tester."),
    dict(id="C43", cat="OPEN", page=23, anchor="add steps for ch1-5",
         title="Timing ch1-5 steps",
         text="Still open: QC board timing lock steps for channels 1 to 5."),
    dict(id="C44", cat="EDIT", page=23, anchor="The RTT in milliseconds should be displayed",
         title="RTT: ticks or ms?",
         text="Editorial: the command comment says ~100 clock ticks, the text says milliseconds. "
              "The station records ticks, with no limit (left to the tester, OPEN)."),
    dict(id="C45", cat="CHANGED", page=24, anchor="Using iPerf3, run the command",
         title="Ping and throughput automatic",
         text="Now automatic: ping (loss and latency) and a 1000 MB transfer to the PTC, PASS if "
              "> 12.5 MB/s. The LINK and AUX LEDs are yes/no steps."),
    dict(id="C46", cat="OPEN", page=24, anchor="Illuminate the LED by writing the register",
         title="AUX LED register TBD",
         text="The AUX LED register is still TBD, so the station asks the tester (manual yes/no)."),
    dict(id="C47", cat="INFO", page=25, anchor="Heatsink Install",
         title="Not in the station flow",
         text="Not in the station's flow: heatsinks, front panel, light pipes and packing are done "
              "as written. Board photos are now taken before heatsinks are fitted, so ICs and "
              "polarised parts can be seen."),
    dict(id="C48", cat="CHANGED", page=27, anchor="Ensure that the overall test result",
         title="Overall result by the station",
         text="The overall result is computed and uploaded by the station at the end of the board "
              "run, with the tester notes and both photos."),
    dict(id="C49", cat="INFO", page=28, anchor="A subsample of fully tested",
         title="WEIC test unchanged",
         text="Unchanged. The WEIC sample test at BNL is not part of the station."),
    dict(id="C50", cat="CHANGED", page=29, anchor="End of Shift Checklist",
         title="Shift sheet not the only record",
         text="Each run in the HWDB carries tester, date and run number, so this sheet is no "
              "longer the only record. The start page has a Board history search (* wildcard) and "
              "a list of boards waiting for a retest."),
]
