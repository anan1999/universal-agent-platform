"""One fresh-session pair; identical executor, model, goal and external contract."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
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


def action_trace(events):
    """Persist bounded derived metadata, never raw commands, output or messages.

    Labels are overlapping lexical hints, not proof an action was necessary.
    Repetition means identical command text, not redundant work.
    """
    seen = set()
    trace = []
    rules = {
        'inspection': r'get-content|read_text|\bcat\b|\brg\b|select-string|\bsed\b',
        'validation': r'pytest|compileall|npm\s+(?:test|run\s+build)|acceptance',
        'editing': r'apply_patch|write_text|set-content|add-content',
        'environment': r'pip\s+install|venv|where\.exe|get-command|python\s+--version',
        'repository_status': r'git\s+(?:status|diff)',
    }
    for event in events:
        item = event.get('item', {})
        if event.get('type') != 'item.completed' or item.get('type') not in {
            'command_execution', 'mcp_tool_call', 'web_search', 'file_change'
        }:
            continue
        command = str(item.get('command', ''))
        output = str(item.get('aggregated_output', ''))
        digest = hashlib.sha256(command.encode()).hexdigest() if command else None
        labels = [label for label, pattern in rules.items() if re.search(pattern, command, re.I)]
        if item.get('type') == 'file_change':
            labels.append('editing')
        trace.append({
            'sequence': len(trace) + 1, 'type': item.get('type'),
            'labels': labels or ['unclassified'],
            'command_sha256': digest, 'repeated_exact_command': bool(digest and digest in seen),
            'fixture_paths_mentioned': [path for path in
                ('app/main.py', 'frontend/src/App.jsx', 'tests/test_expenses.py', 'package.json', 'pyproject.toml')
                if path in command.replace('\\', '/')],
            'output_chars': len(output),
            'exit_code': item.get('exit_code') if isinstance(item.get('exit_code'), int) else None,
            'failure_hints': [hint for hint, pattern in {
                'permission': r'PermissionError|access.+denied',
                'missing_dependency': r'ModuleNotFoundError|not recognized|command not found',
                'test_failure': r'FAILED|AssertionError',
            }.items() if re.search(pattern, output, re.I)],
        })
        if digest:
            seen.add(digest)
    return trace


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
            'actions': action_trace(events),
        }
        return result


def prepare_reuse_pair(roots):
    """Same source/context/config; only the warm side retains operation evidence."""
    import yaml
    from adaptive_agent.core.tools import ToolExecutor, ToolRegistry
    from adaptive_agent.project.experience import OperationExperience

    command = {'commands': {'test': {'command': [sys.executable, '-m', 'pytest', '-q'], 'timeout': 60}}}
    measurements = {}
    for name, root in roots.items():
        (root / '.agent').mkdir(exist_ok=True)
        (root / '.agent/commands.yaml').write_text(yaml.safe_dump(command), encoding='utf-8')
        store = OperationExperience(root)
        before = store.fingerprint()
        started = time.perf_counter()
        result = ToolExecutor(ToolRegistry.default(), root).run('project_test')
        if result.status != 'completed' or result.exit_code != 0:
            raise RuntimeError(f'{name}: fixture prerequisite failed: {result.summary}')
        saved = store.record(result, before) if name == 'uap' else False
        measurements[name] = {'seconds': round(time.perf_counter() - started, 3),
                              'exit_code': result.exit_code, 'evidence_saved': saved, 'ai_calls': 0}
    contexts = {name: prepare(root, GOAL, read_sources=True, use_experience=name == 'uap')
                for name, root in roots.items()}
    assert not contexts['baseline']['validation_memory']['applied']
    assert contexts['uap']['validation_memory']['applied']
    assert contexts['baseline']['context']['source_excerpts'] == contexts['uap']['context']['source_excerpts']
    return contexts, measurements


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
    reuse = getattr(args, 'procedure_reuse', False)
    if not reuse:
        prepare(roots['uap'], GOAL)
    setup_ms = (time.perf_counter() - setup_started) * 1000
    warm_context = prepare(roots['uap'], GOAL, read_sources=True) if not reuse else {}
    contexts = {'baseline': None, 'uap': warm_context}
    training = None
    if reuse:
        # Both child sessions resolve the current checkout instead of an older
        # globally installed editable agentctl. No global installation is changed.
        os.environ['PYTHONPATH'] = str(ROOT / 'src')
        contexts, training = prepare_reuse_pair(roots)
        warm_context = contexts['uap']
    hashes = {name: source_hash(root) for name, root in roots.items()}
    assert len(set(hashes.values())) == 1
    contract_hash = hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest()
    report = {'source_hashes': hashes, 'acceptance_sha256': contract_hash,
              'benchmark_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'implementation_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                                      capture_output=True, text=True, check=True).stdout.strip(),
              'model': args.model, 'reasoning': 'low', 'goal': GOAL,
              'order': ['baseline', 'uap'], 'initial_index_ms': round(setup_ms, 3),
              'warm_prepare_ms': warm_context['wall_ms'], 'pre_task_ai_calls': 0,
              'context_chars': len(json.dumps(warm_context, ensure_ascii=False)),
              'limitations': ['one ordered pair, no statistical generalization',
                              'action labels are lexical hints; raw commands/output are not retained; durations per action unavailable',
                              'index reuse and bounded source batching; prior AI-authored knowledge is tested offline',
                              'tool calls are observable events, not internal reasoning rounds',
                              'subscription quota conversion is unavailable',
                              'frontend acceptance checks integration source, not browser rendering'],
              'results': {}}
    report['experiment'] = 'cold_vs_verified_procedure' if reuse else 'baseline_vs_source_context'
    report['prerequisite_checks'] = training
    if reuse:
        report['limitations'].append('both fixtures prechecked for identical side effects; only warm evidence retained; no AI discovery cost measured')
    if not args.execute:
        report['dry_run'] = True
    else:
        for name, root in roots.items():
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit('Codex is not available')
            current = task(root, args.model, 'low')
            packet = Packet(root, GOAL, contexts[name]["context"])
            if reuse:
                packet.text += ('For this isolated experiment, invoke UAP with python -m adaptive_agent.cli '
                                'in place of agentctl; PYTHONPATH points to the implementation under test. '
                                'Use project-root cwd. Do not install or change the global platform.\n')
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
    parser.add_argument('--procedure-reuse', action='store_true')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='gpt-5.6-luna')
    parser.add_argument('--timeout', type=float, default=600)
    asyncio.run(run(parser.parse_args()))
