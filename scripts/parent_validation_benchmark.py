"""Paired real-provider benchmark for scheduler-owned deterministic validation."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from budget_benchmark import _totals
from context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, acceptance, source_hash, task
from direct_benchmark import MeteredCodex, Packet
from adaptive_agent.core.tools import ToolExecutor, ToolRegistry
from adaptive_agent.project.direct import prepare


ARMS = ("agent_owned", "parent_owned")


class OwnershipPacket(Packet):
    """Keep the treatment to one responsibility boundary, not a new workflow."""

    def __init__(self, root: Path, goal: str, context: dict, parent_owned: bool):
        selected = copy.deepcopy(context)
        if parent_owned:
            selected.pop("commands_to_verify", None)
        super().__init__(root, goal, selected)
        validation = (
            "Do not run the project-wide test suite in this task; the scheduler runs "
            "project_test after you return."
            if parent_owned else
            "Run the project-wide test suite once before you return."
        )
        self.text += (
            "\nBOUNDED EXECUTION:\n"
            "- Use at most 8 observable provider tool calls.\n"
            "- Use one targeted inspection pass and one edit pass.\n"
            f"- {validation}\n"
            "- Do not repeat an identical command or emit progress-only messages.\n"
            "- Keep the final response under 250 words.\n"
        )


def _percent(before: float, after: float) -> float | None:
    return round((before - after) / before * 100, 2) if before else None


def measurable(result: dict) -> bool:
    usage = result.get("usage", {})
    return usage.get("source") != "unavailable" and "input" in usage and "output" in usage


def summarize(rounds: list[dict]) -> dict:
    rows = []
    for current in rounds:
        agent = _totals(current["results"]["agent_owned"])
        parent = _totals(current["results"]["parent_owned"])
        rows.append({
            "round": current["round"], "order": current["order"],
            "agent_quality": current["results"]["agent_owned"]["quality"]["passed"],
            "parent_quality": current["results"]["parent_owned"]["quality"]["passed"],
            "token_reduction_percent": _percent(agent["tokens"], parent["tokens"]),
            "uncached_reduction_percent": _percent(
                agent["uncached_tokens"], parent["uncached_tokens"]),
            "provider_tool_delta": agent["tool_calls"] - parent["tool_calls"],
            "agent_owned": agent, "parent_owned": parent,
        })
    pooled = {
        arm: {key: sum(row[arm][key] for row in rows)
              for key in ("tokens", "uncached_tokens", "tool_calls", "assistant_messages",
                          "assistant_message_chars")}
        for arm in ARMS
    }
    for arm in ARMS:
        pooled[arm]["provider_seconds"] = round(sum(
            item["results"][arm]["provider_duration_seconds"] for item in rounds), 3)
        pooled[arm]["end_to_end_seconds"] = round(sum(
            item["results"][arm]["end_to_end_seconds"] for item in rounds), 3)
        pooled[arm]["parent_tool_calls"] = sum(
            item["results"][arm]["parent_validation"]["tool_calls"] for item in rounds)
        pooled[arm]["provider_validation_actions"] = sum(
            "validation" in action.get("labels", [])
            for item in rounds
            for action in item["results"][arm].get("telemetry", {}).get("actions", []))
    return {
        "rounds_completed": len(rows),
        "agent_quality_passes": sum(row["agent_quality"] for row in rows),
        "parent_quality_passes": sum(row["parent_quality"] for row in rows),
        "pooled": pooled,
        "pooled_total_token_reduction_percent": _percent(
            pooled["agent_owned"]["tokens"], pooled["parent_owned"]["tokens"]),
        "pooled_uncached_token_reduction_percent": _percent(
            pooled["agent_owned"]["uncached_tokens"], pooled["parent_owned"]["uncached_tokens"]),
        "pooled_provider_tool_reduction_percent": _percent(
            pooled["agent_owned"]["tool_calls"], pooled["parent_owned"]["tool_calls"]),
        "pooled_end_to_end_time_reduction_percent": _percent(
            pooled["agent_owned"]["end_to_end_seconds"],
            pooled["parent_owned"]["end_to_end_seconds"]),
        "rows": rows,
    }


def render(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Parent-owned deterministic validation benchmark", "",
        "The control asks the AI task to run the project test suite. The treatment removes "
        "that command from AI context and runs the same allowlisted test once in the scheduler "
        "with zero provider tokens.", "",
        "| Round | Order | Agent quality | Parent quality | Token reduction | Uncached reduction | Provider-tool delta |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['round']} | {' → '.join(row['order'])} | "
            f"{'PASS' if row['agent_quality'] else 'FAIL'} | "
            f"{'PASS' if row['parent_quality'] else 'FAIL'} | "
            f"{row['token_reduction_percent']}% | {row['uncached_reduction_percent']}% | "
            f"{row['provider_tool_delta']:+d} |")
    lines.extend([
        "", "## Aggregate", "",
        f"- Agent-owned quality: {summary['agent_quality_passes']}/{summary['rounds_completed']}",
        f"- Parent-owned quality: {summary['parent_quality_passes']}/{summary['rounds_completed']}",
        f"- Pooled total-token reduction: {summary['pooled_total_token_reduction_percent']}%",
        f"- Pooled uncached-token reduction: {summary['pooled_uncached_token_reduction_percent']}%",
        f"- Pooled provider-tool reduction: {summary['pooled_provider_tool_reduction_percent']}%",
        f"- Pooled end-to-end time reduction: {summary['pooled_end_to_end_time_reduction_percent']}%",
        f"- Provider validation actions, agent-owned: {summary['pooled']['agent_owned']['provider_validation_actions']}",
        f"- Provider validation actions, parent-owned: {summary['pooled']['parent_owned']['provider_validation_actions']}",
        f"- Parent deterministic tool calls: {summary['pooled']['parent_owned']['parent_tool_calls']}",
        "", "Quality is decided by the benchmark-owned acceptance contract, not the model's claim.", "",
    ])
    if summary["parent_quality_passes"] < summary["agent_quality_passes"]:
        lines.append("Decision: **REJECT_QUALITY** — ownership transfer reduced accepted quality.")
    elif ((summary["pooled_total_token_reduction_percent"] or 0) > 0
          and (summary["pooled_uncached_token_reduction_percent"] or 0) > 0):
        lines.append("Decision: **CANDIDATE** — quality was preserved and pooled measured token cost fell.")
    elif all((summary[key] or 0) < 0 for key in (
            "pooled_total_token_reduction_percent",
            "pooled_uncached_token_reduction_percent",
            "pooled_provider_tool_reduction_percent")):
        lines.append(
            "Decision: **REJECT_COST** — quality held, but total tokens, uncached tokens, "
            "and provider tool calls all increased.")
    else:
        lines.append("Decision: **INCONCLUSIVE** — quality held, but pooled measured token cost did not improve.")
    return "\n".join(lines) + "\n"


def _configure(root: Path) -> None:
    agent = root / ".agent"
    agent.mkdir()
    commands = {"commands": {"test": {
        "command": [sys.executable, "-m", "pytest", "-q", "--basetemp=.agent/pytest-tmp"],
        "timeout": 90,
    }}}
    (agent / "commands.yaml").write_text(
        yaml.safe_dump(commands, sort_keys=False), encoding="utf-8")


def _save(rounds: list[dict], args: argparse.Namespace) -> dict:
    report = {
        "experiment": "agent_owned_vs_parent_owned_validation",
        "goal": GOAL, "model": args.model, "reasoning": "low",
        "summary": summarize(rounds), "rounds": rounds,
        "limitations": [
            "This screening uses one software task family.",
            "Provider-reported tokens do not map directly to subscription quota units.",
            "The scheduler test suite is not the benchmark-owned feature acceptance contract.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(report), encoding="utf-8")
    return report


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; benchmark evidence is never overwritten.")
    workspace.mkdir(parents=True)
    rounds = []
    contract_hash = hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest()
    for number in range(1, args.rounds + 1):
        order = list(ARMS if number % 2 else reversed(ARMS))
        roots = {arm: workspace / f"round-{number}" / arm for arm in ARMS}
        for root in roots.values():
            shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            _configure(root)
        hashes = {arm: source_hash(root) for arm, root in roots.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError("Application sources differ before execution.")
        contexts = {arm: prepare(root, GOAL, read_sources=True, value_gated=True)["context"]
                    for arm, root in roots.items()}
        current = {"round": number, "order": order, "source_hashes": hashes, "results": {}}
        for arm in order:
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit("Codex is not available")
            work = task(roots[arm], args.model, "low")
            packet = OwnershipPacket(roots[arm], GOAL, contexts[arm], arm == "parent_owned")
            started = time.perf_counter()
            receipt = await provider.execute(work, packet=packet)
            provider_seconds = time.perf_counter() - started
            parent_result = {"tool_calls": 0, "status": "not_run", "duration_seconds": 0.0}
            if arm == "parent_owned" and receipt.status == "completed":
                tool = ToolExecutor(ToolRegistry.default(), roots[arm]).run("project_test")
                parent_result = {"tool_calls": 1, "status": tool.status,
                                 "exit_code": tool.exit_code,
                                 "duration_seconds": round(tool.duration_seconds, 3)}
            quality = acceptance(roots[arm])
            if arm == "parent_owned" and parent_result["status"] != "completed":
                quality = dict(quality)
                quality["passed"] = False
                quality["parent_validation_error"] = parent_result["status"]
            result = {
                "status": receipt.status, "usage": receipt.token_usage,
                "provider_duration_seconds": round(provider_seconds, 3),
                "end_to_end_seconds": round(time.perf_counter() - started, 3),
                "quality": quality, "error": receipt.error_code,
                "telemetry": getattr(provider, "telemetry", {}),
                "packet_chars": len(packet.render()), "parent_validation": parent_result,
                "actual_source_changed": source_hash(roots[arm]) != hashes[arm],
            }
            current["results"][arm] = result
            print(f"round {number} {arm}: " + json.dumps(result), flush=True)
            if not measurable(result):
                failure = workspace / f"round-{number}-infrastructure-failure.json"
                failure.write_text(json.dumps(current, indent=2), encoding="utf-8")
                raise SystemExit(
                    f"Provider evidence is unavailable; pair rejected and recorded at {failure}.")
        rounds.append(current)
        _save(rounds, args)
    if hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() != contract_hash:
        raise RuntimeError("Acceptance contract changed during benchmark.")
    return _save(rounds, args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))
