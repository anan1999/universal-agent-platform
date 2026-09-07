"""Print the cross-domain composition matrix using the mock provider only.

Run with `python scripts/domain_matrix.py` from any directory. Consumes zero AI
quota; it plans without executing.
"""

from __future__ import annotations

import sys

from adaptive_agent.cli import _dry_run


GOALS = [
    ("Software Engineering", "Fix a Python bug in the configuration loader"),
    ("AI Engineering", "Benchmark INT8 model latency on the edge device"),
    ("UI / UX", "Redesign the settings page for better usability"),
    ("Product", "Create feature requirements for a billing dashboard"),
    ("Research", "Compare vector database options and cite the evidence"),
    ("Technical Writing", "Document the public API in the readme"),
    ("DevOps", "Deploy the service to the production cluster"),
    ("Unknown domain", "Plan an interior lighting redesign for a small studio apartment"),
    ("Trivial", "Fix typo in the footer label"),
    ("Read-only", "Locate the function responsible for configuration loading. Do not modify anything."),
]


def main() -> int:
    for label, goal in GOALS:
        plan = _dry_run(goal, "mock")
        analysis, team = plan["analysis"], plan["team"]
        print("=" * 96)
        print(f"{label}: {goal}")
        print(f"  profiles   : {', '.join(analysis['profiles'])}")
        print(f"  capability : {', '.join(analysis['capabilities'][:8]) or '(none matched)'}")
        print(f"  complexity : {analysis['complexity']}   risk: {analysis['risk']}   "
              f"read_only: {analysis['read_only']}   inferred: {analysis['inferred']}")
        for task in plan["tasks"]:
            print(f"    [{task['kind']:8}] {task['agent']:24} {str(task['model'] or '-'):15} "
                  f"{task['title'][:48]}")
        if team["omitted"]:
            print("  omitted    : " + "; ".join(f"{item['role']} ({item['reason']})"
                                                for item in team["omitted"][:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
