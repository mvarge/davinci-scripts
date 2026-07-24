"""`python3 -m resolve_kit` — print a snapshot of the current Resolve session.

Useful as a connection smoke test and as the first verification step for
agent-driven workflows.
"""

import json
import sys

from . import ResolveConnectionError, connect


def main() -> int:
    try:
        rk = connect(need_project=False)
    except ResolveConnectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        info = rk.summary()
    except ResolveConnectionError:
        info = {"connected": True, "project": None,
                "hint": "Resolve is running but no project is open."}
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
