# PTC board QC test station

Run on the host machine connected to the PTC and QC board:

    pip install -r ptctestsuite/requirements.txt
    python -m ptctestsuite

This opens the test station GUI in the browser at http://localhost:8080/. It walks the tester
through the QC procedure one step at a time, shows every step's result as it goes, and uploads
the record to the HWDB at the end. A barcode scanner works in any input box, since it types the
code and presses Enter.

| Option | What it does |
| --- | --- |
| `--terminal` | Use the original terminal prompts instead of the GUI |
| `--disable-hwdb` | Don't upload anything to the HWDB |
| `--debug` | Don't connect to the PTC or QC board; talk to a test client on localhost |
| `--port N` | GUI port (default `gui_port` in `config/parameters.py`) |
| `--no-browser` | Don't open the browser; go to the address printed in the terminal |

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
- Window title and station label are `gui_title` and `gui_station` in `config/parameters.py`.
  Colors and layout are the variables at the top of `ui/static/index.html`, with the same
  names as the PTC QC GUI designer summary.
- If the HWDB upload fails, the record is kept in `unuploaded_results.jsonl`.
