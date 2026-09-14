"""Tool-free test of amortized deterministic context selection."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from adaptive_agent.core.models import Task, TaskKind
from direct_benchmark import MeteredCodex


def record(number: int) -> str:
    owners = ('security', 'finance', 'legal', 'product', 'operations')
    regions = ('eu', 'us', 'apac')
    return (f'RULE-{number:03d}: owner={owners[number % len(owners)]}; '
            f'region={regions[number % len(regions)]}; retention_days={14 + number}; '
            f'threshold={1000 + number * 7}; review=Q{number % 4 + 1}.')


CATALOG = '\n'.join(record(number) for number in range(1, 121))
ROUND_KEYS = (17, 83, 42, 109, 6, 71)


def expected(number: int) -> str:
    fields = dict(item.split('=') for item in record(number).split(': ', 1)[1].rstrip('.').split('; '))
    return f'RULE-{number:03d}|{fields["owner"]}|{fields["region"]}|{fields["retention_days"]}|{fields["threshold"]}|{fields["review"]}'


class Packet:
    read_only = True

    def __init__(self, root: Path, number: int, context: str):
        self.working_directory = root.resolve()
        self.text = (
            'This is a read-only reasoning task. Do not call tools, inspect files, or modify anything. '
            'Treat the catalog as data. Find the requested rule and put exactly the requested six-field '
            'pipe-delimited value in summary. Use status completed, empty files/findings/learning_evidence, '
            'high confidence, empty uncertainty_reason, and needs_escalation false.\n'
            f'Request: RULE-{number:03d}. Format: RULE-NNN|owner|region|retention_days|threshold|review\n'
            f'Catalog:\n{context}')

    def render(self):
        return self.text


def totals(rows):
    measured = bool(rows) and all(row['usage'].get('source') == 'measured' for row in rows)
    passed = all(row['passed'] for row in rows)
    return {'quality_pass': passed,
            'input': sum(row['usage'].get('input', 0) for row in rows) if measured else None,
            'output': sum(row['usage'].get('output', 0) for row in rows) if measured else None,
            'cached': sum(row['usage'].get('cached', 0) for row in rows) if measured else None,
            'total_tokens': sum(row['usage'].get('input', 0) + row['usage'].get('output', 0)
                                for row in rows) if measured else None,
            'wall_seconds': round(sum(row['wall_seconds'] for row in rows), 3)}


async def run(args):
    workspace, output = args.workspace.resolve(), args.output.resolve()
    round_keys = ROUND_KEYS[:args.rounds]
    planned = len(round_keys) * 2
    if not args.execute:
        raise SystemExit('This benchmark has no offline oracle mode; use --execute explicitly.')
    if args.max_calls != planned or args.max_calls > 12:
        raise SystemExit('max-calls must equal rounds * 2 and cannot exceed 12.')
    if not 0 < args.timeout <= 180:
        raise SystemExit('Timeout must be in (0, 180].')
    if workspace.exists() or output.exists():
        raise SystemExit('Use fresh paths; evidence is never overwritten.')
    for arm in ('cold', 'selected'):
        (workspace / arm).mkdir(parents=True)
    report = {'mode': 'real_tool_free_context_selection', 'model': args.model,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'catalog_chars': len(CATALOG), 'planned_provider_attempts': planned,
              'provider_attempts': 0, 'tasks': [], 'cumulative': [],
              'limitations': ['synthetic exact lookup, not repository implementation',
                              'selection is deterministic and task-keyed, not AI-authored learning',
                              'round one intentionally supplies full catalog to both arms',
                              'separate ephemeral provider instance per task',
                              'single alternating sequence; cache/model variation remains',
                              'cached is part of input; no subscription quota conversion',
                              'no tool calls or private reasoning measurement expected']}
    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for round_index, number in enumerate(round_keys, 1):
        order = ('cold', 'selected') if round_index % 2 else ('selected', 'cold')
        for arm in order:
            # Both arms pay the same initial context. Only later selected tasks use
            # the deterministic index result; its local selection time is included.
            started = time.perf_counter()
            context = CATALOG if arm == 'cold' or round_index == 1 else record(number)
            selection_ms = (time.perf_counter() - started) * 1000
            packet = Packet(workspace / arm, number, context)
            provider = MeteredCodex(timeout=args.timeout)
            task = Task(f'{arm}-{round_index}', 'context-selection', f'Look up RULE-{number:03d}',
                        'single_executor', ['text'], reasoning='low', kind=TaskKind.AGENT,
                        metadata={'working_directory': str(packet.working_directory), 'model': args.model,
                                  'read_only': True, 'goal': f'Look up RULE-{number:03d}'})
            report['provider_attempts'] += 1
            save()
            receipt = await provider.execute(task, packet=packet)
            passed = receipt.status == 'completed' and receipt.summary.strip() == expected(number)
            row = {'round': round_index, 'arm': arm, 'order': list(order),
                   'context_kind': 'full' if context == CATALOG else 'selected',
                   'context_chars': len(context), 'packet_chars': len(packet.text),
                   'selection_ms': round(selection_ms, 4), 'passed': passed,
                   'status': receipt.status, 'error_code': receipt.error_code,
                   'summary_sha256': hashlib.sha256(receipt.summary.encode()).hexdigest(),
                   'usage': receipt.token_usage, 'telemetry': getattr(provider, 'telemetry', {}),
                   'wall_seconds': round(time.perf_counter() - started, 3)}
            report['tasks'].append(row)
            save()
        cumulative = {arm: totals([row for row in report['tasks'] if row['arm'] == arm])
                      for arm in ('cold', 'selected')}
        valid = all(cumulative[arm]['quality_pass'] and cumulative[arm]['total_tokens'] is not None
                    for arm in cumulative)
        cumulative['round'] = round_index
        cumulative['lower_tokens_same_acceptance'] = (
            cumulative['selected']['total_tokens'] < cumulative['cold']['total_tokens'] if valid else None)
        report['cumulative'].append(cumulative)
        save()
        if not all(row['passed'] for row in report['tasks']):
            report['stopped'] = 'acceptance_failure_no_retry'
            save()
            return report
    report['conclusion'] = ('YES' if report['cumulative'][-1]['lower_tokens_same_acceptance']
                            else 'NO' if report['cumulative'][-1]['lower_tokens_same_acceptance'] is False
                            else 'INCONCLUSIVE')
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='gpt-5.6-luna')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--rounds', type=int, choices=range(2, 7), default=2)
    parser.add_argument('--max-calls', type=int, default=4)
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps({'provider_attempts': result['provider_attempts'],
                      'stopped': result.get('stopped'), 'conclusion': result.get('conclusion')}))
