# QL Label Designer: help

The label designer makes and prints labels on the **Brother QL-810W** connected to the PartsDB Pi.
Open it at **http://128.91.45.130/labels/** from any computer on the Penn network.
This page is also built in: the **HELP** link at the top right of the designer.

[TOC]

## Quick start: your first label

1. Check the top right of the designer says the roll you expect, e.g. **29 MM CONTINUOUS**, with a green dot.
2. Under **TEMPLATE**, press **NEW**.
3. Under **ADD**, press **TEXT**. A text item appears on the label. Type your text in **DATA** on the right.
4. Add a code: **DATAMATRIX**, **QR** or **CODE 128**, or pick another from the drop-down and press **ADD**.
5. Drag the items where you want them. Lines appear when something is centred or lines up with something else.
6. Set the **LENGTH** knob, or press **FIT LENGTH** to shrink the label to its contents.
7. Give it a name (box under the template list) and press **SAVE**.
8. Under **PRINT**, press **PRINT**.

Before every print the app reads back every barcode and QR from the picture it is about to print.
If one doesn't scan it refuses to print and says which one.

## The design screen

![The design screen](static/help/design.png)

1. **Template:** pick a saved label, start a **NEW** one, name it and **SAVE**. **✕** deletes the selected template.
2. **Roll:** the roll this label is for. **LOADED** switches to whatever roll is in the printer.
3. **Length and end feed** knobs. Drag up/down on a knob (Shift for fine steps), use the mouse wheel, or double-click
   the value under it to type a number.
4. **ADD:** text, graphics, codes, boxes and lines (below the knobs).
5. **ALIGN** bar: line things up (see below).
6. **The label**, drawn exactly as it will print (300 dots per inch). The white band is the tape; hatching shows
   tape the printer can't print on.
7. **ELEMENT:** settings of the selected item.

Further down on the right are **FIELDS** (test values) and **PRINT**.

### Moving things

- **Drag** an item to move it. A line appears and the item snaps into place when:
  - its centre is on the centre of the label (left-right or top-bottom), or
  - its centre or an edge lines up with the centre or an edge of another item.
- Hold **Alt** (Option on a Mac) while dragging to move freely without snapping, or untick **snap**.
- **Arrow keys** move the selected item 1 dot (about 0.08 mm); with **Shift**, 10 dots.
- **Shift+click** selects several items; they then move together.
- **Delete** removes the selection, **Ctrl+D** duplicates.
- **ZOOM**: FIT, or 1× to 4×. **mm grid** shows a 1 mm grid.

### The ALIGN bar

- With **one** item selected, the buttons line it up **on the label**: left edge, centre, right edge, top, middle, bottom.
- With **several** selected (Shift+click), the same buttons line them up **with each other**.
- **CENTRE ON LABEL ↔ / ↕** moves the whole selection to the middle of the label, keeping its layout.

## Items you can add

### Text

Type in **DATA** (Enter for a new line). Choose **FONT**, **SIZE** (in dots: 30 dots ≈ 2.5 mm), **ALIGN** and **ROTATE**.
Put `{name}` in the text to fill it from a field, e.g. `Board {num}`.

### Barcodes and 2D codes

Pick the type in **CODE**. Which one to use:

| Code | Use it for |
|---|---|
| **DataMatrix** | Small labels. The most compact, the standard on electronics parts, any phone or 2D scanner reads it. Our PTC labels use it. |
| **QR** | When people will scan with a phone camera app; a bit bigger than DataMatrix for the same data. |
| **Micro QR / rMQR** | Very small or long, thin labels (rMQR is a wide, short QR). |
| **Code 128** | A normal 1D barcode for text or numbers, read by every scanner. Needs width: about 11 bars per character. |
| **EAN / UPC, ITF, Code 39/93, Codabar, DataBar, PDF417, Aztec** | Only when some other system asks for that exact type. |

- **MODULE** is the size of one square or the narrowest bar, in dots. 4–6 dots (0.35–0.5 mm) scans easily; 2 is the
  practical minimum for 1D barcodes; 1 dot won't scan reliably.
- **HEIGHT** (1D codes only) is the bar height.
- **TEXT**: show readable text **BELOW / ABOVE / RIGHT / LEFT** of the code. **SAYS** changes what it says (it can use
  `{fields}` too); empty means it repeats what's in the code.
- Under the label the app shows **reads back OK** or **does NOT read back** for every code. A code that runs off the
  edge, is too small, or holds too much text won't read back. Make it bigger, move it, or shorten the data.

### Graphics (logos, symbols)

Press **GRAPHIC**, then pick one under **BUILT IN** (arrow, warning, ESD, check, pin 1, ground, high voltage,
do-not-touch, the Penn shield) or **UPLOAD A PICTURE…** (PNG, JPG or SVG).
Set the **HEIGHT** in dots and leave **WIDTH** at 0 to keep its shape (or the other way round).
The printer only prints black or white: **LEVEL** sets how dark a grey must be to print black;
tick **dither** for photos.

### Boxes and lines

**BOX** draws a frame (or a filled block, **filled**); **LINE** a straight line. Set the size and thickness in dots.
**white on black** works on any item.

## Label size and roll

- **Roll picker**: every Brother roll the QL-810W takes. Continuous rolls can be any length; die-cut and round labels
  have a fixed size (the knobs grey out). The app refuses to print if the roll in the printer isn't the one the
  template is for, so a 29 mm design can't end up on 62 mm tape.
- **LENGTH**: label length along the tape, about 2 mm to 1 m. **FIT LENGTH** shrinks it to the contents.
- **TEXT RUNS: ALONG TAPE / ACROSS TAPE**: along is a long label read along the tape; across turns the design so
  you can make short labels, e.g. **29 × 10 mm** (the PTC board labels).
- **use the full width**: on 29 mm tape, 27.9 mm instead of Brother's 25.9 mm. Measured on our printer; the
  item nearest the open edge has about 0.7 mm to spare.
- **END FEED**: the blank tape the printer adds at the **start and end of every piece**. The printer won't go
  below about **3 mm** whatever we ask; that's its firmware. To get labels with **no gap**, print them as a
  **STRIP** (below) and cut them apart.
- **CUT**: cut after **EACH** label, once **AT END**, or **NONE**. **turn 180°** flips the print if it comes out
  upside down for how you use it.

## Fields and the DATA & BATCH table

A **field** is a name in curly brackets, like `{num}` or `{ip}`, inside any text, barcode or QR.
When printing, the app fills it in. **FIELDS** on the design screen holds a test value for each, used for the preview
and for single labels.

To print a run of different labels, use the **DATA & BATCH** tab:

![The data table](static/help/data.png)

Each **column** is a field; each **row** is one label.

1. **+ COLUMN** adds a field (rename it in its header; `{name}` on the label uses that name). **+ ROW** adds a row
   for typed values. **✕** in a header removes that column.
2. **MAIN**: one column is the main one. It decides **how many labels** there are and their **order**; every other
   column follows it row by row (row 3 of the IP column belongs to board 003).
3. **What fills the column**:
   - **Sequence (001, 002…)**: BEFORE + number + AFTER, with START, STEP and DIGITS (zero padding).
     E.g. BEFORE `PTC`, START 11, DIGITS 3 gives PTC011, PTC012…
   - **IP address (counts up)**: FIRST address and STEP, e.g. 10.0.1.11, .12, .13; it rolls over correctly past .255.
   - **Same on every label**: one VALUE for all.
   - **Typed / from CSV**: type a value in each row.
4. **HOW MANY** labels (when the main column is a sequence or IP). If the main column is typed, it's one label per
   filled row. **carry on numbering after printing**: after a batch prints, every sequence (and IP) starts where it
   left off, and the template remembers it.
5. Typed cells. **Paste from a spreadsheet**: copy a block of cells in Excel or Google Sheets, click a typed cell and
   paste; it fills down and to the right. Empty typed cells are underlined in red.
6. **THE BATCH** shows how many labels, and warnings: empty cells, or codes that won't scan (the first and last three
   labels are scan-checked here; every label is checked again when you print). **FIRST** and **LAST** show the labels.
7. **PRINT BATCH** prints it (or choose **BATCH** under PRINT on the design screen).

More:

- **IMPORT CSV…** reads a spreadsheet saved as CSV (first row = column names). Columns with the same names are filled;
  new names become new columns. Check which column is **MAIN** afterwards.
- **EXPORT CSV** saves the whole batch as it will print, all fields filled in.
- **SAVE AS TABLE…** / **LOAD**: keep a table under a name and load it into another template.

## Printing

Under **PRINT** on the design screen:

- **ONE LABEL** prints the label as shown, with the test values in FIELDS. **BATCH** prints the data table.
- **COPIES**: how many of each label.
- **PIECES: ONE PER LABEL**: each label is fed and cut on its own (about 3 mm blank at both ends of each).
- **PIECES: STRIP**: the labels are printed end to end at exactly their length on one piece, with no gap, and the
  printer cuts once at the end. You cut them apart by hand on the marks.
  - **LABELS PER STRIP**: 0 = the whole batch on one strip (up to 1 m).
  - **MARKS**: **EDGE TICKS** (small ticks at the tape edges, the label face stays clean), **DASHED** line across,
    or **NONE**.
  - **also mark the start and end**: marks before the first and after the last label, to trim the printer's 3 mm
    end feed off exactly.

Every label is scanned in software before printing; if any code doesn't read back, nothing prints and the message
says which label and code.

## Templates

- Pick one from the list to open it; edit; **SAVE** keeps it under the name in the box.
- To **copy** a template: open it, type a new name, **SAVE**.
- **ptc-board-10mm** is the PTC board label (29 × 10 mm, Penn shield, `UPENN/DUNE PTC Production Board {num}`,
  DataMatrix `PTC{num}`). The **PTC QC station** (http://128.91.45.130/ptc-qc/) uses it for its
  **Print labels for new boards** button, which picks serials not yet in the HWDB, not tested and not printed
  before. Keep the field name `{num}` if you edit this template.
- Templates are files in `~/ql-labels-data/templates/` on the Pi.

## Printer and calibration tabs

- **PRINTER**: what the printer reports (roll, errors), and **FULL-WIDTH BLEED**: how many extra dots each roll may use
  past Brother's window (29 mm is measured: 6 + 18). Only change these after measuring with a test print.
- **CALIBRATE**: prints test labels with a frame, the length written inside and a 1 mm scale, to check what the
  printer really does with a length and end feed.

## Colours

**COLOURS** (top right) opens the colour designer: change the 8 interface colours, pick a preset, **USE IN THE
DESIGNER** (saved in your browser), or **COPY SUMMARY** to ask for a new default.

## Troubleshooting

| Problem | What to do |
|---|---|
| **PRINTER OFFLINE** / "No Brother printer on USB" | Is the printer on and its USB cable in the Pi? If the green **Editor Lite** light is on, hold that button until it goes off (Editor Lite makes it look like a USB stick, not a printer). |
| "The printer has … loaded; this label is for …" | The roll in the printer doesn't match the template. Load the right roll, or press **LOADED** and check the design still fits. |
| "Printer reports: Cover open / No media / End of media" | Close the cover, load or replace the roll. |
| "Not printing: … did not read back" | A code won't scan: it runs off the label, is too small (MODULE), or holds too much text. Fix it on the design screen; the checks under the label turn green. |
| Labels are longer than set, blank tape at the ends | Normal: the printer always adds about 3 mm at each end of a piece. Use **STRIP** for gap-free labels. |
| Text upside down for your use | Tick **turn 180°**. |
| Labels come out blank | Check the roll is seated in its guides and the cover is closed, then print a **CALIBRATE** strip. If that is blank too, tell whoever looks after the Pi. |
| A label fell on the floor | The cutter drops pieces in front of the printer; keep the printer back from the table edge. |
| The page doesn't load | The app runs on the Pi as a service: on the Pi run `systemctl --user restart ql-labels`; its log: `journalctl --user -u ql-labels -n 50`. All the Pi apps: `~/apps/status.sh`. |

## Command line (on the Pi)

    ~/apps/ql-labels.sh print NAME --set num=001              one label, fields filled in
    ~/apps/ql-labels.sh print NAME --batch                    the template's data table
    ~/apps/ql-labels.sh print NAME --batch --start 200 --count 50
    ~/apps/ql-labels.sh print NAME --csv boards.csv           one label per CSV row (columns by name)
    ~/apps/ql-labels.sh print NAME --strip 0 --marks edge     as one strip with cut marks
    ~/apps/ql-labels.sh calibrate 10 6 4 --margin 35          test labels
    ~/apps/ql-labels.sh status                                what the printer reports
    ~/apps/ql-labels.sh --dry-run print NAME --batch          make the print job without printing

Add `--copies N`, `--cut each|end|none`, `--no-strip`, `--no-end-marks` as needed.
