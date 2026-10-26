"""Start-up banner for the command-line entry points (indoor.py, metro.py).

Four lines on stderr, only when stderr is an interactive terminal; silent when piped, logged or
imported as a library. PTG_QUIET=1 turns it off.
"""
import os
import sys

ART = (r"  ___ _____ ___ ",
       r" | _ \_   _/ __|",
       r" |  _/ | || (_ |",
       r" |_|   |_| \___|")


def splash(what, details=""):
    """Print the banner with a one-line summary of what is being generated."""
    if os.environ.get("PTG_QUIET") or not sys.stderr.isatty():
        return
    from version import SNAPSHOT
    text = (f"Procedural Terrain Generator  {SNAPSHOT}", what, details, "")
    sys.stderr.write("".join(f"{a}   {t}\n" for a, t in zip(ART, text)) + "\n")
