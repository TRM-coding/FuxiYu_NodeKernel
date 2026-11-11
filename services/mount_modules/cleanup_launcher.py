"""Linux parent-death guarded launcher for host mount cleanup.

This file is executed as a standalone script by ``mount_cleanup`` so it can set
``PR_SET_PDEATHSIG`` before replacing itself with the configured ``rm`` binary.
It deliberately imports only the standard library and performs no cleanup work
itself.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import sys


_PR_SET_PDEATHSIG = 1
_EXIT_PRCTL_FAILED = 120
_EXIT_PARENT_CHANGED = 121
_EXIT_EXEC_FAILED = 122


def _set_parent_death_signal() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
    except Exception:
        return False
    return result == 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--rm-path", required=True)
    parser.add_argument("--path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))

    if not _set_parent_death_signal():
        return _EXIT_PRCTL_FAILED

    # Close the race between spawn and prctl: if the parent died before the
    # signal was installed, getppid no longer matches the expected Node PID and
    # this process must exit before executing rm.
    if os.getppid() != args.parent_pid:
        return _EXIT_PARENT_CHANGED

    try:
        os.execv(args.rm_path, ["rm", "-rf", args.path])
    except OSError:
        return _EXIT_EXEC_FAILED
    return _EXIT_EXEC_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
