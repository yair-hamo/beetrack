"""Entry point of the packaged app (beetrack.exe). See src/beetrack/desktop.py."""

import multiprocessing

if __name__ == "__main__":
    # Analyses run in child processes started with "spawn": a frozen executable must hand those
    # children over to multiprocessing before doing anything else.
    multiprocessing.freeze_support()
    from beetrack.desktop import main

    main()
