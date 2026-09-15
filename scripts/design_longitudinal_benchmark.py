"""Three-track, real-provider longitudinal design benchmark.

The baseline and UAP arms start each round from the same accepted source. Provider
sessions are fresh; only UAP keeps project intelligence between rounds.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from adaptive_agent import __version__
from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Task, new_id
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.project.discovery import discover
from adaptive_agent.providers.registry import providers
from adaptive_agent.runtime import RESOURCE_ROOT
from adaptive_agent.storage.database import Database
from design_benchmark_quality import evaluate
from pocketflow_longitudinal_benchmark import (
    CompletionProbedProvider,
    changed_paths,
    reset_source,
    source_snapshot,
    summarize_uap_run,
)

FIXTURES = ROOT / "benchmark-fixtures" / "cross-domain"
CONTRACT_PATH = ROOT / "benchmark-fixtures" / "design-longitudinal" / "contracts.json"
DOMAINS = ("ui-ux", "graphic-design", "three-d-design")
PROFILE = {"ui-ux": "uiux", "graphic-design": "design", "three-d-design": "design"}
ROLE = {"ui-ux": "ui-ux-designer", "graphic-design": "graphic-designer",
        "three-d-design": "3d-designer"}


def contracts() -> dict[str, list[dict[str, Any]]]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Three-track longitudinal design benchmark")
    parser.add_argument("--execute", action="store_true",
                        help="authorize real provider calls (domains * rounds * 2)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--provider", default="codex")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--reasoning", default="low", choices=("low", "medium", "high"))
    parser.add_argument("--rounds", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--domains", nargs="*", choices=DOMAINS, default=list(DOMAINS))
    parser.add_argument("--max-provider-calls", type=int, default=18)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def seed(path: Path, domain: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURES / domain, path)
    (path / "README.md").write_text(
        f"# {domain} longitudinal design fixture\n\n"
        "Complete each requested design change in place. Keep previous accepted work intact.\n",
        encoding="utf-8")


def dry_run(args: argparse.Namespace) -> dict[str, Any]:
    selected = tuple(args.domains)
    specs = contracts()
    rows = []
    for domain in selected:
        if len(specs[domain]) < args.rounds:
            raise RuntimeError(f"{domain} does not define {args.rounds} rounds")
        root = args.workspace.resolve() / domain / "dry-run"
        if root.exists():
            shutil.rmtree(root)
        seed(root, domain)
        initial = [evaluate(root, domain, number) for number in range(1, args.rounds + 1)]
        rows.append({"domain": domain, "rounds": args.rounds,
                     "goals": [item["goal"] for item in specs[domain][:args.rounds]],
                     "initial_acceptance_fails": all(not item["passed"] for item in initial),
                     "contracts": initial})
    return {"ready": all(row["initial_acceptance_fails"] for row in rows),
            "provider_calls": 0, "tracks": rows}


def _normalized_receipt(receipt: Any, provider: Any, model: str | None,
                        reasoning: str) -> dict[str, Any]:
    usage = receipt.token_usage
    return {
        "status": receipt.status,
        "provider": receipt.provider or getattr(provider, "id", "unknown"),
        "model": receipt.model or model,
        "reasoning": reasoning,
        "input_tokens": int(usage.get("input", 0)),
        "cached_input": int(usage.get("cached", 0)),
        "output_tokens": int(usage.get("output", 0)),
        "token_source": usage.get("source", "unavailable"),
        "usage_complete": bool(usage.get("complete", False)),
        "ai_invocations": int(usage.get("invocation_count", 1)),
        "provider_tool_calls": int(usage.get("provider_tool_calls", 0)),
        "provider_messages": int(usage.get("provider_messages", 0)),
        "token_attribution": usage.get("attribution", {}),
        "duration_seconds": receipt.duration_seconds,
        "files_modified": receipt.files,
        "error": receipt.error_code,
        "summary": receipt.summary,
    }


async def baseline_run(provider: Any, root: Path, domain: str, round_number: int,
                       goal: str, model: str | None, reasoning: str) -> dict[str, Any]:
    task = Task(new_id("BASE"), "BASELINE", goal, ROLE[domain],
                ["design", "filesystem", "write_access", "repository_access"],
                reasoning=reasoning,
                metadata={"working_directory": str(root), "model": model,
                          "goal": goal, "read_only": False,
                          "execution_budget": {"max_provider_tool_calls": 8,
                                               "max_provider_messages": 12}})
    packet = ExecutionPacketBuilder().build(task, root, f"design-{domain}", "design")
    measured = CompletionProbedProvider(
        provider, lambda: evaluate(root, domain, round_number)["passed"], model)
    receipt = await measured.execute(task, packet=packet)
    return _normalized_receipt(receipt, provider, model, reasoning)


async def uap_run(provider: Any, root: Path, domain: str, round_number: int,
                  goal: str, db: Database, provider_id: str,
                  model: str | None) -> dict[str, Any]:
    info = discover(root)
    project_rows = db.query("SELECT id FROM projects WHERE path=?", (str(root.resolve()),))
    project_id = project_rows[0]["id"] if project_rows else new_id("PRJ")
    if not project_rows:
        db.execute("INSERT INTO projects(id,path,name,type,config_json) VALUES(?,?,?,?,?)",
                   (project_id, str(root.resolve()), info.name, info.type, "{}"))
    measured = CompletionProbedProvider(
        provider, lambda: evaluate(root, domain, round_number)["passed"], model)
    orchestrator = Orchestrator(
        db, measured, EventBus(db), provider_name=provider_id,
        provider_preference=[provider_id], active_profiles=[PROFILE[domain]],
        consumption_mode="economy")
    started = time.monotonic()
    run_id = await orchestrator.run_goal(
        goal, project_id, str(root), project_name=info.name,
        project_type=info.type, project_signals=info.signals)
    return summarize_uap_run(db, run_id, provider_id,
                             duration_seconds=time.monotonic() - started)


def _tokens(result: dict[str, Any]) -> int:
    return int(result.get("input_tokens", 0)) + int(result.get("output_tokens", 0))


def valid_pair(row: dict[str, Any]) -> bool:
    baseline, uap = row["baseline"], row["uap"]
    models = uap.get("model", [])
    models = set(models if isinstance(models, list) else [models])
    return bool(
        baseline.get("status") == uap.get("status") == "completed"
        and baseline.get("source_changed") and uap.get("source_changed")
        and baseline.get("model") in models
        and baseline.get("token_source") == uap.get("token_source") == "measured"
        and baseline.get("usage_complete") and uap.get("usage_complete")
        and row["quality"]["baseline"]["passed"]
        and row["quality"]["uap"]["passed"])


def summarize(tracks: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for track in tracks for row in track["rounds"]]
    valid = [row for row in rows if row.get("comparison_valid")]
    baseline = sum(row["baseline_tokens"] for row in valid)
    uap = sum(row["uap_tokens"] for row in valid)
    per_domain = {}
    for track in tracks:
        accepted = [row for row in track["rounds"] if row.get("comparison_valid")]
        base = sum(row["baseline_tokens"] for row in accepted)
        current = sum(row["uap_tokens"] for row in accepted)
        per_domain[track["domain"]] = {
            "valid_rounds": len(accepted), "rounds": len(track["rounds"]),
            "baseline_tokens": base, "uap_tokens": current,
            "reduction_percent": round((base - current) / base * 100, 2) if base else None,
            "quality_passed": len(accepted) == len(track["rounds"]),
        }
    return {
        "total_rounds": len(rows), "valid_rounds": len(valid),
        "baseline_tokens": baseline, "uap_tokens": uap,
        "reduction_percent": round((baseline - uap) / baseline * 100, 2) if baseline else None,
        "quality_equivalent": len(valid) == len(rows),
        "savings_claimable": len(valid) == len(rows) and uap < baseline,
        "by_domain": per_domain,
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# Three-track longitudinal design benchmark", "",
        "Each domain is an independent three-round project. Baseline and UAP begin every round "
        "from the same accepted checkpoint. Provider sessions are fresh; only UAP retains its "
        "project intelligence. Token claims require exact measured usage and both artifacts to pass "
        "the same cumulative deterministic contract.", "",
        "| Track | Round | Problem | Baseline tokens | UAP tokens | Reduction | Baseline quality | UAP quality | Valid |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for track in payload["tracks"]:
        for row in track["rounds"]:
            base, uap = row["baseline_tokens"], row["uap_tokens"]
            reduction = ((base - uap) / base * 100) if base else 0
            short_goal = row["goal"].replace("|", "/")
            lines.append(
                f"| {track['domain']} | {row['round']} | {short_goal} | {base} | {uap} | "
                f"{reduction:.2f}% | {'PASS' if row['quality']['baseline']['passed'] else 'FAIL'} | "
                f"{'PASS' if row['quality']['uap']['passed'] else 'FAIL'} | {row['comparison_valid']} |")
    summary = payload["summary"]
    lines += ["", "## Aggregate", "",
              f"- Valid paired rounds: {summary['valid_rounds']}/{summary['total_rounds']}",
              f"- Baseline tokens: {summary['baseline_tokens']}",
              f"- UAP tokens: {summary['uap_tokens']}",
              f"- Token reduction: {summary['reduction_percent']}%",
              f"- Quality equivalent: {summary['quality_equivalent']}",
              f"- Savings claimable: {summary['savings_claimable']}", ""]
    for domain, item in summary["by_domain"].items():
        lines += [f"### {domain}", "",
                  f"- Valid rounds: {item['valid_rounds']}/{item['rounds']}",
                  f"- Baseline / UAP: {item['baseline_tokens']} / {item['uap_tokens']} tokens",
                  f"- Reduction: {item['reduction_percent']}%", ""]
    lines += ["## Interpretation limits", "",
              "The quality gate verifies brief compliance, file validity, cumulative feature retention, "
              "accessibility structure, palette/typographic constraints, and 3D geometry integrity. "
              "It does not replace blind human evaluation of aesthetic preference. Provider token counts "
              "also do not map one-to-one to subscription quota units.", ""]
    return "\n".join(lines)


def save(payload: dict[str, Any], args: argparse.Namespace) -> None:
    payload["summary"] = summarize(payload["tracks"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(payload), encoding="utf-8")


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    required_calls = len(args.domains) * args.rounds * 2
    if args.max_provider_calls != required_calls:
        raise SystemExit(f"max-provider-calls must equal the exact paired plan ({required_calls})")
    if args.workspace.exists():
        raise SystemExit("Use a new workspace; benchmark evidence is never overwritten.")
    registry = providers()
    if args.provider == "mock" or args.provider not in registry:
        raise SystemExit("A registered real provider is required; Mock is prohibited.")
    provider = registry.create(args.provider, timeout=args.timeout)
    probe = provider.probe()
    if not probe.ready or not provider.capabilities().supports("filesystem", allow_uncertain=False):
        raise SystemExit(f"Provider is not ready for repository writing: {probe.detail}")
    args.workspace.mkdir(parents=True)
    specs = contracts()
    payload = {
        "experiment": "three_track_longitudinal_design_v1",
        "environment": {"uap": __version__, "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=True).stdout.strip(), "provider": args.provider,
            "model": args.model, "reasoning": args.reasoning,
            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "max_provider_calls": args.max_provider_calls},
        "method": {"canonical_source": "baseline", "fresh_provider_session": True,
                   "uap_memory_retained": True, "quality_contract": "design-longitudinal-v1"},
        "tracks": [], "summary": {},
    }
    for domain in args.domains:
        domain_root = args.workspace / domain
        canonical, baseline, uap = (domain_root / name for name in ("canonical", "baseline", "uap"))
        seed(canonical, domain)
        reset_source(canonical, baseline)
        reset_source(canonical, uap)
        initialize_project(uap, RESOURCE_ROOT / "templates", auto=True)
        db = Database(domain_root / "uap-history.db")
        track = {"domain": domain, "rounds": []}
        payload["tracks"].append(track)
        for number, spec in enumerate(specs[domain][:args.rounds], 1):
            if number > 1:
                reset_source(canonical, baseline)
                reset_source(canonical, uap, preserve_agent=True)
            if evaluate(canonical, domain, number)["passed"]:
                raise RuntimeError(f"{domain} round {number} already passes before execution")
            before = source_snapshot(canonical)
            baseline_result = await baseline_run(
                provider, baseline, domain, number, spec["goal"], args.model, args.reasoning)
            partial = {"domain": domain, "round": number, "goal": spec["goal"],
                       "baseline": baseline_result, "stage": "baseline_complete"}
            (domain_root / "partial.json").write_text(json.dumps(partial, indent=2), encoding="utf-8")
            uap_result = await uap_run(
                provider, uap, domain, number, spec["goal"], db, args.provider, args.model)
            baseline_quality = evaluate(baseline, domain, number)
            uap_quality = evaluate(uap, domain, number)
            baseline_paths = changed_paths(before, source_snapshot(baseline))
            uap_paths = changed_paths(before, source_snapshot(uap))
            baseline_result["source_changed"] = bool(baseline_paths)
            uap_result["source_changed"] = bool(uap_paths)
            baseline_result["changed_paths"] = baseline_paths
            uap_result["changed_paths"] = uap_paths
            row = {"round": number, "goal": spec["goal"],
                   "baseline": baseline_result, "uap": uap_result,
                   "baseline_tokens": _tokens(baseline_result),
                   "uap_tokens": _tokens(uap_result),
                   "quality": {"baseline": baseline_quality, "uap": uap_quality}}
            row["comparison_valid"] = valid_pair(row)
            track["rounds"].append(row)
            evidence = domain_root / "evidence" / f"round-{number}"
            reset_source(baseline, evidence / "baseline")
            reset_source(uap, evidence / "uap")
            save(payload, args)
            print(json.dumps({"domain": domain, "round": number,
                              "baseline_tokens": row["baseline_tokens"],
                              "uap_tokens": row["uap_tokens"],
                              "baseline_quality": baseline_quality["passed"],
                              "uap_quality": uap_quality["passed"],
                              "valid": row["comparison_valid"]}), flush=True)
            if not row["comparison_valid"]:
                raise SystemExit(f"Quality or measurement gate failed: {domain} round {number}")
            reset_source(baseline, canonical)
        (domain_root / "partial.json").unlink(missing_ok=True)
    save(payload, args)
    return payload


def main() -> int:
    args = parse_args()
    if args.dry_run:
        payload = dry_run(args)
    elif args.execute:
        payload = asyncio.run(execute(args))
    else:
        raise SystemExit("Use --dry-run or --execute explicitly.")
    print(json.dumps(payload.get("summary", payload), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
