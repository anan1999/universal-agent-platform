"""Deterministic support for the AI already executing the user's task."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from adaptive_agent.project.context_index import ProjectContextIndex


def prepare(root: Path, goal: str) -> dict:
    started = time.perf_counter()
    store = ProjectContextIndex(root)
    index = store.initialize()
    # Do not hash every cached file: check only entries in relevant areas.
    routing = {"important_paths": index.get("important_paths", {})}
    text = goal.lower()
    words = {"backend": ("api", "backend", "endpoint", "database"),
             "frontend": ("frontend", "react", "dashboard", "ui"),
             "tests": ("test", "validate", "regression"),
             "docs": ("docs", "readme", "documentation")}
    paths = [path for area, path in routing["important_paths"].items()
             if any(word in text for word in words.get(area, (area,)))]
    paths = list(dict.fromkeys(paths or list(routing["important_paths"].values())[:3]))[:8]
    notes = []
    for path in store.cache._read()["files"]:
        if any(path == scope or path.startswith(scope.rstrip("/") + "/") for scope in paths):
            entry = store.cache.valid(path)
            if entry:
                notes.append({"path": path, "summary": entry["summary"]})
        if len(notes) == 8:
            break
    context = {"architecture": index.get("architecture", {}), "paths": paths,
               "commands_to_verify": index.get("commands", {}), "notes": notes,
               "constraints": index.get("constraints", [])[:8],
               "decisions": index.get("decisions", [])[:8]}
    while len(json.dumps(context, ensure_ascii=False)) > 6000 and notes:
        notes.pop()
    return {"mode": "direct", "context": context, "provider_calls": 0,
            "wall_ms": round((time.perf_counter() - started) * 1000, 3),
            "instruction": "Continue the user's task yourself. Read relevant source on demand; paths are hints, not write restrictions. Batch independent reads. Run relevant deterministic checks; revisit only failures or new evidence. Save a short source-linked note only when useful. Do not delegate or create a team unless the user requests it."}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="agentctl")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("prepare")
    start.add_argument("goal")
    start.add_argument("--json", action="store_true")
    remember = commands.add_parser("remember")
    remember.add_argument("path")
    remember.add_argument("summary", help="short factual note verified against the source")
    check = commands.add_parser("check")
    check.add_argument("tools", nargs="+", choices=("project_test", "project_build", "git_status"))
    args = parser.parse_args(argv)
    root = Path.cwd()
    if args.command == "prepare":
        result = prepare(root, args.goal)
    elif args.command == "remember":
        relative = Path(args.path)
        target = (root / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(root.resolve()):
            parser.error("source must be inside this project")
        if len(args.summary) > 320:
            parser.error("summary must be at most 320 characters")
        entry = ProjectContextIndex(root).cache.remember(args.path, args.summary)
        result = {"saved": entry is not None, "path": args.path}
    else:
        from adaptive_agent.core.tools import ToolExecutor, ToolRegistry

        executor = ToolExecutor(ToolRegistry.default(), root, output_limit=2000)
        checks = [executor.run(tool) for tool in dict.fromkeys(args.tools)]
        result = {"checks": [{"tool": item.tool, "status": item.status,
                              "summary": item.summary,
                              "output": item.output if item.status != "completed" else ""}
                             for item in checks]}
        print(json.dumps(result, ensure_ascii=False))
        return 0 if all(item.status == "completed" for item in checks) else 1
    print(json.dumps(result, ensure_ascii=False))
    return 0
