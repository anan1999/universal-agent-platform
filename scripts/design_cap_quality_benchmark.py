"""Reuse the original UI/UX, graphic, and 3D fixtures for paired SOL cap trials."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

try:
    from scripts import cross_domain_budget_benchmark as legacy
    from scripts.quality_completion_benchmark import Ledger, MODEL, converge
except ModuleNotFoundError:
    import cross_domain_budget_benchmark as legacy
    from quality_completion_benchmark import Ledger, MODEL, converge

from adaptive_agent.providers.registry import providers

DOMAINS = ("ui-ux", "graphic-design", "three-d-design")
CAPS = {"cap8_plain": 8, "cap6_plain": 6}


class PlainPacket:
    read_only = False

    def __init__(self, root: Path, domain: str, cap: int):
        self.working_directory = root
        self.text = (
            "Complete the assignment in this fresh project workspace.\n"
            f"Domain: {domain}.\nGoal: {legacy.GOALS[domain]}\n"
            "Read the local brief and data files. Create only the requested deliverable files. "
            "Do not start other AI agents, access sibling workspaces, install dependencies, "
            "or use the network.\n"
            f"Hard envelope: {cap} provider tool calls and 12 assistant messages.\n"
            "Do not repeat successful checks or inspect repository status.\n"
            "Keep the final response under 180 words.\n"
        )

    def render(self) -> str:
        return self.text


async def execute(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; existing evidence is immutable.")
    workspace.mkdir(parents=True)
    ledger = Ledger(workspace / "attempts.sqlite3")
    report = {
        "experiment": "legacy_design_cap8_vs_cap6_plain_cost_to_quality_v1",
        "model": MODEL, "reasoning": "low", "domains": list(args.domains),
        "acceptance_sha256": hashlib.sha256(legacy.ACCEPTANCE.read_bytes()).hexdigest(),
        "cases": [],
        "limits": {"tokens_per_arm": args.token_ceiling,
                   "seconds_per_arm": args.seconds_ceiling},
    }
    for number, domain in enumerate(args.domains, 1):
        roots = {arm: workspace / domain / arm for arm in CAPS}
        hashes = {arm: legacy.reset(root, domain, workspace)
                  for arm, root in roots.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError("Fixture sources differ")
        order = list(CAPS if number % 2 else reversed(tuple(CAPS)))
        case = {"domain": domain, "order": order, "arms": {}}
        for arm in order:
            root, cap = roots[arm], CAPS[arm]

            async def invoke(prompt: str, root=root, cap=cap, domain=domain) -> dict:
                provider = providers().create("codex", timeout=min(600, args.seconds_ceiling))
                if not provider.probe().ready:
                    return {"status": "failed", "model": MODEL,
                            "token_source": "unavailable", "usage_complete": False,
                            "error": "codex_unavailable"}
                current = legacy.task(root, domain, MODEL)
                current.title = prompt
                current.metadata["goal"] = prompt
                current.metadata["codex_live_usage"] = True
                current.metadata["execution_budget"] = {
                    "max_provider_tool_calls": cap,
                    "max_provider_messages": 12,
                    "completion_probe_passes": 2,
                    "completion_probe_grace_seconds": 1.0,
                    "completion_steer_grace_seconds": 20.0,
                    "completion_interrupt_grace_seconds": 15.0,
                }
                packet = PlainPacket(root, domain, cap)
                if prompt != legacy.GOALS[domain]:
                    packet.text += "\n" + prompt + "\n"
                started = time.monotonic()
                receipt = await provider.execute(
                    current, packet=packet,
                    completion_probe=lambda: legacy.acceptance(root, domain)["passed"])
                usage = receipt.token_usage
                return {
                    "status": receipt.status, "model": receipt.model or MODEL,
                    "input_tokens": int(usage.get("input", 0)),
                    "cached_input": int(usage.get("cached", 0)),
                    "output_tokens": int(usage.get("output", 0)),
                    "token_source": usage.get("source", "unavailable"),
                    "usage_complete": bool(usage.get("complete", False)),
                    "provider_tool_calls": int(usage.get("provider_tool_calls", 0)),
                    "provider_messages": int(usage.get("provider_messages", 0)),
                    "duration_seconds": time.monotonic() - started,
                    "error": receipt.error_code,
                }

            case["arms"][arm] = await converge(
                ledger, domain, number, arm, legacy.GOALS[domain], invoke,
                lambda root=root, domain=domain: legacy.acceptance(root, domain),
                token_ceiling=args.token_ceiling,
                seconds_ceiling=args.seconds_ceiling)
            case["arms"][arm]["cap"] = cap
        report["cases"].append(case)
        (workspace / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(case), flush=True)
        if any(value["outcome"] != "contract_passed"
               for value in case["arms"].values()):
            break
    if hashlib.sha256(legacy.ACCEPTANCE.read_bytes()).hexdigest() != report["acceptance_sha256"]:
        raise RuntimeError("Acceptance changed during experiment")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--domains", nargs="+", choices=DOMAINS, default=list(DOMAINS))
    parser.add_argument("--token-ceiling", type=int, default=300000)
    parser.add_argument("--seconds-ceiling", type=float, default=900)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for real quota use")
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
