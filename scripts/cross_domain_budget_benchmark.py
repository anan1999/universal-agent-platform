"""Fresh-user, cross-domain real-provider benchmark for a six-tool envelope."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from adaptive_agent.core.models import Task, TaskKind, new_id
from budget_benchmark import _totals
from context_cache_benchmark import source_hash
from direct_benchmark import MeteredCodex


FIXTURES = ROOT / "benchmark-fixtures" / "cross-domain"
ACCEPTANCE = FIXTURES / "acceptance.py"
ARMS = ("fixed_8", "candidate_6")
DOMAINS = (
    "product-strategy",
    "research-synthesis",
    "ui-ux",
    "three-d-design",
    "graphic-design",
    "interior-lighting",
)
CAPS = {"fixed_8": 8, "candidate_6": 6}
MESSAGE_CAP = 12
GOALS = {
    "product-strategy": "Analyze the supplied product evidence and brief, then create the requested product strategy deliverable.",
    "research-synthesis": "Synthesize the supplied source cards to answer the research question and create the requested evidence-grounded deliverable.",
    "ui-ux": "Design and implement the requested accessible UI/UX prototype from the supplied requirements.",
    "three-d-design": "Design and implement the requested text-based 3D asset from the supplied model brief.",
    "graphic-design": "Design and implement the requested vector poster from the supplied poster brief.",
    "interior-lighting": "Calculate and create the requested interior lighting plan from the supplied room data and requirements.",
}


class DomainPacket:
    read_only = False

    def __init__(self, root: Path, domain: str, cap: int):
        self.working_directory = root
        self.text = (
            "Complete the assignment in this fresh project workspace.\n"
            f"Domain: {domain}.\nGoal: {GOALS[domain]}\n"
            "Read the local brief and data files. Create only the requested deliverable files. "
            "Do not start other AI agents, access sibling workspaces, install dependencies, or use the network.\n"
            "BOUNDED EXECUTION:\n"
            f"- Hard envelope: {cap} provider tool calls and {MESSAGE_CAP} assistant messages.\n"
            "- Batch independent inspection; perform one creation pass and at most one targeted verification.\n"
            "- Do not emit progress-only messages or inspect repository status.\n"
            "- Keep the final response under 180 words.\n"
        )

    def render(self) -> str:
        return self.text


def task(root: Path, domain: str, model: str) -> Task:
    return Task(
        new_id("TASK"), new_id("RUN"), GOALS[domain], f"{domain}-designer",
        ["text", "filesystem", "write_access"], reasoning="low",
        metadata={"goal": GOALS[domain], "working_directory": str(root), "model": model,
                  "read_only": False}, kind=TaskKind.AGENT,
    )


def acceptance(root: Path, domain: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ACCEPTANCE), "--project", str(root), "--domain", domain],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = {"passed": False, "domain": domain, "errors": ["invalid acceptance output"]}
    payload["returncode"] = result.returncode
    return payload


def percent(before: float, after: float) -> float | None:
    return round((before - after) / before * 100, 2) if before else None


def summarize(cases: list[dict]) -> dict:
    pooled = {
        arm: {key: sum(_totals(case["results"][arm])[key] for case in cases)
              for key in ("tokens", "uncached_tokens", "tool_calls", "assistant_messages")}
        for arm in ARMS
    }
    for arm in ARMS:
        pooled[arm]["seconds"] = round(sum(
            case["results"][arm]["duration_seconds"] for case in cases), 3)
    domain_wins = {metric: sum(
        _totals(case["results"]["candidate_6"])[metric]
        < _totals(case["results"]["fixed_8"])[metric] for case in cases)
        for metric in ("tokens", "uncached_tokens", "tool_calls", "assistant_messages")}
    quality = {arm: sum(case["results"][arm]["quality"]["passed"] for case in cases)
               for arm in ARMS}
    return {
        "domains": len(cases), "quality": quality, "pooled": pooled, "domain_wins": domain_wins,
        "total_token_reduction_percent": percent(pooled["fixed_8"]["tokens"], pooled["candidate_6"]["tokens"]),
        "uncached_token_reduction_percent": percent(
            pooled["fixed_8"]["uncached_tokens"], pooled["candidate_6"]["uncached_tokens"]),
        "tool_reduction_percent": percent(pooled["fixed_8"]["tool_calls"], pooled["candidate_6"]["tool_calls"]),
        "message_reduction_percent": percent(
            pooled["fixed_8"]["assistant_messages"], pooled["candidate_6"]["assistant_messages"]),
        "time_reduction_percent": percent(pooled["fixed_8"]["seconds"], pooled["candidate_6"]["seconds"]),
    }


def decision(summary: dict) -> str:
    if summary["quality"]["candidate_6"] < summary["quality"]["fixed_8"]:
        return "REJECT_QUALITY"
    if summary["quality"]["candidate_6"] < summary["domains"]:
        return "INCOMPLETE_QUALITY"
    if ((summary["total_token_reduction_percent"] or 0) > 0
            and (summary["uncached_token_reduction_percent"] or 0) > 0):
        return "CROSS_DOMAIN_CANDIDATE"
    return "NO_GENERAL_COST_BENEFIT"


def render(report: dict) -> str:
    lines = [
        "# Fresh-user cross-domain tool-budget benchmark", "",
        "Every arm starts in a new Git project with no `.agent` directory, UAP history, project "
        "index, or learned budget. The experiment therefore tests whether the previously observed "
        "six-tool envelope transfers safely to unseen users and domains; it does not claim that a "
        "new user has already learned a project-specific policy.", "",
        "| Domain | Order | Fixed quality | Candidate quality | Fixed tokens | Candidate tokens | Fixed tools | Candidate tools |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report["cases"]:
        fixed, candidate = (case["results"][arm] for arm in ARMS)
        lines.append(
            f"| {case['domain']} | {' → '.join(case['order'])} | "
            f"{'PASS' if fixed['quality']['passed'] else 'FAIL'} | "
            f"{'PASS' if candidate['quality']['passed'] else 'FAIL'} | "
            f"{_totals(fixed)['tokens']} | {_totals(candidate)['tokens']} | "
            f"{_totals(fixed)['tool_calls']} | {_totals(candidate)['tool_calls']} |"
        )
    item = report["summary"]
    lines.extend([
        "", "## Aggregate", "",
        f"- Quality: fixed {item['quality']['fixed_8']}/{item['domains']}; candidate {item['quality']['candidate_6']}/{item['domains']}",
        f"- Total-token reduction: {item['total_token_reduction_percent']}%",
        f"- Uncached-token reduction: {item['uncached_token_reduction_percent']}%",
        f"- Provider-tool reduction: {item['tool_reduction_percent']}%",
        f"- Assistant-message reduction: {item['message_reduction_percent']}%",
        f"- Time reduction: {item['time_reduction_percent']}%",
        f"- Per-domain token wins: {item['domain_wins']['tokens']}/{item['domains']}",
        "", f"Decision: **{report['decision']}**.", "",
        "Quality means deterministic contract compliance, not subjective aesthetic preference. "
        "Provider tokens do not map directly to subscription quota units. Each domain has one pair, "
        "so this is a breadth check rather than a statistical estimate.",
    ])
    return "\n".join(lines) + "\n"


def reset(root: Path, domain: str, workspace: Path) -> str:
    resolved = root.resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise RuntimeError("Benchmark target leaves its dedicated workspace")
    shutil.copytree(FIXTURES / domain, resolved)
    subprocess.run(["git", "init", "--quiet", str(resolved)], check=True)
    if (resolved / ".agent").exists():
        raise RuntimeError("Fresh-user fixture unexpectedly contains UAP state")
    return source_hash(resolved)


def save(report: dict, args: argparse.Namespace) -> None:
    report["summary"] = summarize(report["cases"])
    report["decision"] = decision(report["summary"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(report), encoding="utf-8")


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; benchmark evidence is never overwritten.")
    workspace.mkdir(parents=True)
    chosen = tuple(args.domains or DOMAINS)
    unknown = set(chosen) - set(DOMAINS)
    if unknown:
        raise SystemExit(f"Unknown domains: {', '.join(sorted(unknown))}")
    report = {
        "experiment": "fresh_user_fixed_8_vs_candidate_6_cross_domain",
        "model": args.model, "reasoning": "low", "caps": CAPS, "message_cap": MESSAGE_CAP,
        "acceptance_sha256": hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest(),
        "implementation_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=True).stdout.strip(),
        "fresh_user_contract": {"new_git_project": True, "agent_state": False,
                                "prior_project_memory": False, "fresh_provider_session": True},
        "cases": [],
    }
    for number, domain in enumerate(chosen, 1):
        domain_root = workspace / domain
        roots = {arm: domain_root / arm for arm in ARMS}
        hashes = {arm: reset(root, domain, workspace) for arm, root in roots.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{domain}: fixture sources differ")
        order = list(ARMS if number % 2 else reversed(ARMS))
        case = {"domain": domain, "order": order, "source_hash": next(iter(hashes.values())),
                "results": {}}
        for arm in order:
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit("Codex is not available")
            current_task = task(roots[arm], domain, args.model)
            current_task.metadata["execution_budget"] = {
                "max_provider_tool_calls": CAPS[arm], "max_provider_messages": MESSAGE_CAP,
            }
            packet = DomainPacket(roots[arm], domain, CAPS[arm])
            started = time.perf_counter()
            receipt = await provider.execute(current_task, packet=packet)
            result = {
                "status": receipt.status, "usage": receipt.token_usage,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "quality": acceptance(roots[arm], domain), "error": receipt.error_code,
                "telemetry": getattr(provider, "telemetry", {}),
                "packet_chars": len(packet.render()),
                "actual_source_changed": source_hash(roots[arm]) != hashes[arm],
            }
            case["results"][arm] = result
            print(f"{domain} {arm}: " + json.dumps(result), flush=True)
            if result["usage"].get("source") != "measured":
                raise SystemExit("Provider usage unavailable; benchmark rejected")
        report["cases"].append(case)
        save(report, args)
    if hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() != report["acceptance_sha256"]:
        raise RuntimeError("Acceptance contract changed during benchmark")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true",
                        help="confirm two real provider calls per selected domain")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--domains", nargs="*", choices=DOMAINS)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=300)
    parsed = parser.parse_args()
    if not parsed.execute:
        raise SystemExit("Pass --execute to authorize two real provider calls per domain.")
    asyncio.run(run(parsed))
