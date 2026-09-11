"""One fresh-session pair; identical executor, model, goal and external contract."""
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
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from context_cache_benchmark import FIXTURE, ACCEPTANCE, GOAL, acceptance, source_hash, task
from adaptive_agent.project.direct import prepare
from adaptive_agent.providers.codex.provider import CodexProvider


class Packet:
    read_only = False

    def __init__(self, root, goal, context=None):
        self.working_directory = root
        self.text = (
            'Complete this implementation in the current workspace.\n' + goal + '\n'
            'Return JSON matching the supplied schema, with a short factual summary. '
            'Report changed files only when actually changed. Do not start other AI agents. '
            'Do not access sibling workspaces. Preserve existing expense CRUD.\n'
            'API response contract: {"month":"YYYY-MM","total":number,"categories":'
            '{"category_name":number}}. Category totals must exclude other months.\n'
        )
        if context is not None:
            self.text += json.dumps(context, ensure_ascii=False) + '\n'

    def render(self):
        return self.text


class MeteredCodex(CodexProvider):
    async def _communicate(self, *args, **kwargs):
        result = await super()._communicate(*args, **kwargs)
        events = []
        for line in result[1].decode('utf-8', errors='replace').splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        completed = [event for event in events if event.get('type') == 'item.completed']
        self.telemetry = {
            'tool_calls': sum(event.get('item', {}).get('type') in
                              {'command_execution', 'mcp_tool_call', 'web_search'} for event in completed),
            'assistant_messages': sum(event.get('item', {}).get('type') == 'agent_message' for event in completed),
            'assistant_message_chars': sum(len(str(event.get('item', {}).get('text', '')))
                                           for event in completed
                                           if event.get('item', {}).get('type') == 'agent_message'),
            'provider_turns': sum(event.get('type') == 'turn.completed' for event in events),
            'internal_reasoning_rounds': None,
        }
        return result


async def run(args):
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit('Use a new workspace; existing experiment evidence is never overwritten.')
    workspace.mkdir(parents=True)
    roots = {name: workspace / name for name in ('baseline', 'uap')}
    for root in roots.values():
        shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
    setup_started = time.perf_counter()
    first_context = prepare(roots['uap'], GOAL)
    setup_ms = (time.perf_counter() - setup_started) * 1000
    warm_context = prepare(roots['uap'], GOAL, read_sources=True)
    hashes = {name: source_hash(root) for name, root in roots.items()}
    assert len(set(hashes.values())) == 1
    contract_hash = hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest()
    report = {'source_hashes': hashes, 'acceptance_sha256': contract_hash,
              'implementation_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                                      capture_output=True, text=True, check=True).stdout.strip(),
              'model': args.model, 'reasoning': 'low', 'goal': GOAL,
              'order': ['baseline', 'uap'], 'initial_index_ms': round(setup_ms, 3),
              'warm_prepare_ms': warm_context['wall_ms'], 'pre_task_ai_calls': 0,
              'context_chars': len(json.dumps(warm_context, ensure_ascii=False)),
              'limitations': ['one ordered pair, no statistical generalization',
                              'index reuse and bounded source batching; prior AI-authored knowledge is tested offline',
                              'tool calls are observable events, not internal reasoning rounds',
                              'subscription quota conversion is unavailable',
                              'frontend acceptance checks integration source, not browser rendering'],
              'results': {}}
    if not args.execute:
        report['dry_run'] = True
    else:
        for name, root in roots.items():
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit('Codex is not available')
            current = task(root, args.model, 'low')
            packet = Packet(root, GOAL, warm_context if name == 'uap' else None)
            started = time.perf_counter()
            receipt = await provider.execute(current, packet=packet)
            provider_seconds = time.perf_counter() - started
            quality = acceptance(root)
            report['results'][name] = {
                'status': receipt.status, 'usage': receipt.token_usage,
                'duration_seconds': round(time.perf_counter() - started, 3),
                'provider_seconds': round(provider_seconds, 3),
                'quality': quality, 'error': receipt.error_code,
                'telemetry': getattr(provider, 'telemetry', {}),
                'packet_chars': len(packet.render()),
                'actual_source_changed': source_hash(root) != hashes[name],
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(name + ': ' + json.dumps(report['results'][name]), flush=True)
        assert hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() == contract_hash
        baseline, uap = (report['results'][name] for name in ('baseline', 'uap'))
        passed = all(item['quality']['passed'] for item in (baseline, uap))
        measured = all(item['usage'].get('source') == 'measured' for item in (baseline, uap))
        totals = [item['usage'].get('input', 0) + item['usage'].get('output', 0)
                  for item in (baseline, uap)]
        report['conclusion'] = ('YES' if passed and measured and totals[1] < totals[0]
                                else 'NO' if passed and measured else 'INCONCLUSIVE')
        report['fewer_tool_calls'] = (
            uap['telemetry'].get('tool_calls', float('inf')) < baseline['telemetry'].get('tool_calls', 0)
        )
        report['fewer_messages'] = (
            uap['telemetry'].get('assistant_messages', float('inf')) < baseline['telemetry'].get('assistant_messages', 0)
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='gpt-5.6-luna')
    parser.add_argument('--timeout', type=float, default=600)
    asyncio.run(run(parser.parse_args()))
