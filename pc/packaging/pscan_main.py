"""Entry point for the packaged PScan.exe (PyInstaller freezes this).

Running the frozen exe is equivalent to ``python -m pscan_server`` with the tray icon.
"""

import multiprocessing
import sys

from pscan_server.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # harmless, and guards against any child-process reruns
    sys.exit(main())
