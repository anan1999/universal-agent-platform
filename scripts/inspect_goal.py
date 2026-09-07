"""Print the capability analysis for one goal. Offline; no AI quota."""

from __future__ import annotations

import json
import sys

from adaptive_agent.cli import _dry_run


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python scripts/inspect_goal.py \"<goal>\"", file=sys.stderr)
        return 2
    plan = _dry_run(" ".join(argv), "mock")
    print(json.dumps({"analysis": plan["analysis"], "team": plan["team"]["rationale"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
