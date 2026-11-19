"""Entry point of the packaged app (beetrack.exe). See src/beetrack/desktop.py."""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    # The app has no console window: give Python somewhere to write, so a stray print (here or in an
    # analysis child process) can't crash it. desktop.main() then sends messages to a log file.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    # Analyses run in child processes started with "spawn": a frozen executable must hand those
    # children over to multiprocessing before doing anything else.
    multiprocessing.freeze_support()
    from beetrack.desktop import main

    main()
