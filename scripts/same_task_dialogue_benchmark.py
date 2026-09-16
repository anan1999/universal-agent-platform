"""Paired, real Codex same-thread dialogue pilot; not a cross-task memory test.

Each arm owns one persistent app-server thread. Every follow-up is a new turn in
that thread. Exact usage is the delta of provider-reported cumulative totals.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Task, new_id
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.providers.codex.provider import CodexProvider, RESULT_SCHEMA
from adaptive_agent.runtime import RESOURCE_ROOT
from design_longitudinal_benchmark import contracts, seed
from design_benchmark_quality import evaluate

MODEL = "gpt-5.6-sol"
DOMAIN = "ui-ux"


def usage_delta(previous: dict[str, int], current: dict[str, int]) -> dict[str, int]:
    fields = ("input_tokens", "cached_input_tokens", "output_tokens")
    if not current or any(key not in current for key in fields):
        raise ValueError("complete provider usage notification unavailable")
    result = {key: current[key] - previous.get(key, 0) for key in fields}
    if any(value < 0 for value in result.values()):
        raise ValueError("provider cumulative usage moved backwards")
    result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    result["uncached_tokens"] = (result["input_tokens"]
                                 - result["cached_input_tokens"]
                                 + result["output_tokens"])
    return result


class Dialogue:
    def __init__(self, root: Path, timeout: float):
        self.root = root
        self.timeout = timeout
        self.process: asyncio.subprocess.Process | None = None
        self.stderr_task: asyncio.Task[bytes] | None = None
        self.sequence = 0
        self.thread_id = ""
        self.cumulative: dict[str, int] = {}

    async def __aenter__(self) -> "Dialogue":
        self.process = await asyncio.create_subprocess_exec(
            "codex", "app-server", "--listen", "stdio://",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(self.root),
            env=CodexProvider.child_environment(), limit=8 * 1024 * 1024)
        self.stderr_task = asyncio.create_task(self.process.stderr.read())
        await self.request("initialize", {
            "clientInfo": {"name": "uap-same-task-benchmark", "title": "UAP benchmark",
                           "version": "1"},
            "capabilities": {"experimentalApi": True, "requestAttestation": False,
                             "optOutNotificationMethods": ["item/agentMessage/delta",
                                                           "item/reasoning/textDelta",
                                                           "command/exec/outputDelta"]}})
        await self.send("initialized", notification=True)
        started = await self.request("thread/start", {
            "cwd": str(self.root), "runtimeWorkspaceRoots": [str(self.root)],
            "model": MODEL, "approvalPolicy": "never", "sandbox": "workspace-write",
            "ephemeral": True, "threadSource": "universal-agent-platform"})
        self.thread_id = started["thread"]["id"]
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self.process is not None
        if self.process.stdin:
            self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5)
        except TimeoutError:
            self.process.terminate()
            await self.process.wait()
        if self.stderr_task:
            await self.stderr_task

    async def send(self, method: str, params: dict | None = None,
                   *, notification: bool = False) -> int | None:
        assert self.process and self.process.stdin
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.sequence += 1
            message["id"] = self.sequence
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()
        return None if notification else self.sequence

    async def read(self) -> dict:
        assert self.process and self.process.stdout
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout=self.timeout)
        if not line:
            raise RuntimeError("Codex app-server closed during dialogue")
        return json.loads(line)

    async def request(self, method: str, params: dict) -> dict:
        request_id = await self.send(method, params)
        while True:
            event = await self.read()
            if event.get("id") == request_id:
                if event.get("error"):
                    raise RuntimeError(str(event["error"]))
                return event.get("result", {})

    async def turn(self, prompt: str) -> dict:
        return await asyncio.wait_for(self._turn(prompt), timeout=self.timeout)

    async def _turn(self, prompt: str) -> dict:
        started = time.monotonic()
        response = await self.request("turn/start", {
            "threadId": self.thread_id,
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
            "model": MODEL, "effort": "low", "outputSchema": RESULT_SCHEMA,
            "approvalPolicy": "never", "sandboxPolicy": {
                "type": "workspaceWrite", "writableRoots": [str(self.root)],
                "networkAccess": False}})
        turn_id = response["turn"]["id"]
        latest: dict[str, int] = {}
        while True:
            event = await self.read()
            candidate = CodexProvider._usage_candidate(event)
            if candidate:
                latest = candidate
            if event.get("method") == "turn/completed":
                turn = event.get("params", {}).get("turn", {})
                if turn.get("id") == turn_id:
                    delta = usage_delta(self.cumulative, latest)
                    self.cumulative = latest
                    return {"turn_id": turn_id, "status": turn.get("status"),
                            "usage": delta, "seconds": round(time.monotonic() - started, 2)}


def prompt_for(arm: str, root: Path, goal: str) -> str:
    if arm == "baseline":
        return (goal + " Work in this project. Preserve previous accepted changes. "
                "Validate the smallest relevant behavior and return the structured receipt.")
    task = Task(new_id("DIALOGUE"), "DIALOGUE", goal, "ui-ux-designer",
                ["design", "filesystem", "write_access", "repository_access"],
                reasoning="low", metadata={"working_directory": str(root), "model": MODEL})
    return ExecutionPacketBuilder().build(task, root, "dialogue-uiux", "design").render()


async def run(args: argparse.Namespace) -> dict:
    args.workspace = args.workspace.resolve()
    if args.workspace.exists():
        raise SystemExit("Choose a new workspace; benchmark evidence is immutable.")
    if args.turns < 2 or args.turns > 3:
        raise SystemExit("This pilot has exactly two or three scripted dialogue turns.")
    if not CodexProvider().probe().ready:
        raise SystemExit("Codex provider is unavailable")
    goals = contracts()[DOMAIN][:args.turns]
    report: dict[str, Any] = {
        "method": "paired_persistent_thread_dialogue_v1", "model": MODEL,
        "domain": DOMAIN, "turns_per_arm": args.turns,
        "interpretation": "UAP execution packet and initialized project vs minimal baseline; not full Orchestrator execution or human usability assessment",
        "arms": {}}
    for arm in ("baseline", "uap"):
        root = args.workspace / arm
        seed(root, DOMAIN)
        if arm == "uap":
            initialize_project(root, RESOURCE_ROOT / "templates", auto=True)
        rows = []
        try:
            async with Dialogue(root, args.timeout) as dialogue:
                for number, spec in enumerate(goals, 1):
                    prompt = prompt_for(arm, root, spec["goal"])
                    result = await dialogue.turn(prompt)
                    result["quality"] = evaluate(root, DOMAIN, number)
                    result["prompt_chars"] = len(prompt)
                    rows.append(result)
                    report["arms"][arm] = {"thread_id": dialogue.thread_id, "turns": rows}
                    args.workspace.joinpath("report.json").write_text(
                        json.dumps(report, indent=2), encoding="utf-8")
                    print(f"{arm} turn {number}: {result['status']}, "
                          f"{result['usage']['total_tokens']} tokens, "
                          f"quality={result['quality']['passed']}", flush=True)
                    if result["status"] != "completed" or not result["quality"]["passed"]:
                        break
        except Exception as error:
            report["arms"][arm] = {"turns": rows, "error": str(error)}
            args.workspace.joinpath("report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8")
            raise
    arms = report["arms"]
    report["comparison_valid"] = all(
        len(arms[arm]["turns"]) == args.turns
        and all(row["quality"]["passed"] and row["status"] == "completed"
                for row in arms[arm]["turns"]) for arm in ("baseline", "uap"))
    report["total_tokens"] = {arm: sum(row["usage"]["total_tokens"]
                                       for row in arms[arm]["turns"])
                              for arm in ("baseline", "uap")}
    report["uncached_tokens"] = {arm: sum(row["usage"]["input_tokens"]
                                          - row["usage"]["cached_input_tokens"]
                                          + row["usage"]["output_tokens"]
                                          for row in arms[arm]["turns"])
                                 for arm in ("baseline", "uap")}
    args.workspace.joinpath("report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="authorize real provider calls")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--turns", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=240)
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Real provider calls require --execute")
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
