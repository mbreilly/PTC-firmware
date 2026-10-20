"""PTC QC test station.

    python -m ptctestsuite                 GUI in the browser (default)
    python -m ptctestsuite --terminal      the original terminal prompts
    --debug           no PTC or QC board connection; talks to a test client on localhost
    --disable-hwdb    don't upload anything to the HWDB
    --port N          GUI port (default from config.parameters.gui_port)
    --no-browser      don't open the browser automatically
"""

import asyncio
from argparse import ArgumentParser

from loguru import logger as lg

from ptctestsuite.config import parameters
from ptctestsuite.flow import main_loop

parser = ArgumentParser(prog="python -m ptctestsuite", description="PTC QC test station")
parser.add_argument('--debug', action='store_true', help="no hardware connection, test client on localhost")
parser.add_argument('--disable-hwdb', action='store_true', help="don't upload to the HWDB")
parser.add_argument('--terminal', action='store_true', help="use the terminal prompts instead of the GUI")
parser.add_argument('--port', type=int, default=parameters.gui_port, help="GUI port")
parser.add_argument('--no-browser', action='store_true', help="don't open the browser")
args = parser.parse_args()

lg.remove()
lg.add("ptctests.log", rotation='500MB', level="INFO")


async def run_gui():
    from ptctestsuite.ui.gui import GuiUI
    hwdb_label = "HWDB upload off" if args.disable_hwdb else \
        ("HWDB dev" if "cdbdev" in parameters.dune_hwdb_api_path else "HWDB")
    ui = GuiUI(port=args.port, title=parameters.gui_title, station=parameters.gui_station,
               hwdb_on=not args.disable_hwdb, hwdb_label=hwdb_label, open_browser=not args.no_browser)
    await ui.serve()
    await main_loop(ui, debug=args.debug, disable_hwdb=args.disable_hwdb)


async def run_terminal():
    from ptctestsuite.ui.terminal import TerminalUI
    await main_loop(TerminalUI(), debug=args.debug, disable_hwdb=args.disable_hwdb)


if __name__ == "__main__":
    try:
        asyncio.run(run_terminal() if args.terminal else run_gui())
    except KeyboardInterrupt:
        print("\nStopped.")
