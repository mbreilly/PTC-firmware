# Part-DB label station

A page for putting parts into [Part-DB](https://github.com/Part-DB/Part-DB-server) by showing it the label:
scan the barcode with a USB scanner, or hold the label up to a webcam, or drop in a photo. The station reads the
code, fills in the part, looks the rest up through Part-DB's own supplier lookups (info providers), and saves it:
a new part, or more stock for a part that's already there.

    ~/apps/partdb-station.sh            # http://localhost:8095

Same hardware-panel look as the AOI Parts Mapper (`static/app.css` is a copy of its stylesheet).

## Labels it reads

* ECIA / EIGP 114 DataMatrix (DigiKey, Mouser, Newark/element14 and most distributors): part numbers, quantity, PO,
  sales order, lot, date code, country of origin
* LCSC QR codes, TME QR codes
* Part-DB's own labels (opens that part to add stock)
* distributor product links, EAN/UPC numbers, or a typed part number

## Setup

1. In Part-DB: your user name (top right) → User settings → API tokens → add one with access level **Edit**.
2. In the station: SETTINGS → paste the token → SAVE AND TEST. It is kept in `~/.config/partdb-station/config.json` (mode 600).
3. For descriptions, categories, footprints, datasheets and prices, switch on info providers in Part-DB
   (Tools → Info providers). LCSC needs no key; DigiKey and Mouser need API keys there.

## Scanners and cameras

A USB scanner set up as a keyboard types into the scan box. The DataMatrix codes on DigiKey/Mouser labels contain
invisible separators; the page turns Ctrl+] / Ctrl+^ / Ctrl+D into them and also accepts `<GS>`, `{GS}` and `␝`.
If a scan lands in one of the part's boxes by mistake, the page notices the burst of fast keys and reads it as a label.

The webcam only works on the page opened on the Pi itself (http://localhost), because browsers allow cameras only
there or over https. From other computers, use the scanner or upload a photo (a phone's camera works through the
photo box). Photos are decoded on the Pi with zxing-cpp.

## Files

* `partdb_station/labels.py`: reads label codes
* `partdb_station/decode.py`: finds barcodes in photos
* `partdb_station/partdb.py`: Part-DB REST API client
* `partdb_station/station.py`: scan → look up → save
* `partdb_station/server.py`, `static/`: the page
* saves are logged to `~/partdb-station-data/saved.jsonl` (the RECENT tab)

Tests (`python -m unittest discover -t . -s tests`) run against a small stand-in for Part-DB's API, `tests/fake_partdb.py`.

Python packages: `zxing-cpp`, `pillow`, `numpy` (in `.venv`).
