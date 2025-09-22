
from __future__ import annotations
import sys, subprocess

def main():
    argv = sys.argv[1:]
    if not argv:
        # no args -> ek-core (will trigger setup if first run)
        sys.exit(subprocess.call(["ek-core"]))
    # pass all args to ek-core
    sys.exit(subprocess.call(["ek-core", *argv]))
