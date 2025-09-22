
from __future__ import annotations
import sys, subprocess

KNOWN = {
  "add","init","list","remove","open","where",
  "todo","git","ws","run","notes","sync","status","cd","secrets",
  "setup","ignore","help","--help","-h","hooks"
}

def main():
    argv = sys.argv[1:]
    if not argv:
        # no args -> ek-core (will trigger setup if first run)
        sys.exit(subprocess.call(["ek-core"]))
    sub = argv[0]
    rest = argv[1:]
    # if it's an option (starts with dash), pass-through
    if sub.startswith("-"):
        sys.exit(subprocess.call(["ek-core", *argv]))
    # known commands (including help aliases)
    if sub in KNOWN:
        if sub in {"help","--help","-h"}:
            sys.exit(subprocess.call(["ek-core", "--help"]))
        sys.exit(subprocess.call(["ek-core", *argv]))
    # otherwise treat as task name
    sys.exit(subprocess.call(["ek-core", "run", "task", sub, *rest]))
