"""`python -m termx` entry point."""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in ("--version", "-V"):
        from termx import APP_NAME, APP_VERSION

        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if argv and argv[0] in ("--help", "-h"):
        from termx.cli import print_help

        print_help()
        return 0
    if argv and argv[0] in ("doctor", "--doctor"):
        from termx.cli import doctor

        return doctor()
    if argv and argv[0] == "run":
        from termx.cli import run_command

        return run_command(argv[1:])

    from termx.ui.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
