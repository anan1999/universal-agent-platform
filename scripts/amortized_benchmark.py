"""Sequential task pairs with cumulative costs; offline smoke is NOT an AI benchmark."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from adaptive_agent.core.models import Task, TaskKind
from adaptive_agent.project.context_index import FileSummaryCache
from adaptive_agent.providers.codex.provider import CodexCapabilities
from direct_benchmark import MeteredCodex

DOMAINS = ('code', 'document', 'data')
POLICY = {
    'code': 'Exclude negative amounts. subtotal sums nonnegative amounts. count counts nonnegative amounts. mean is subtotal/count, or zero for no included amounts.',
    'document': 'Every brief needs headings # Decision, ## Evidence, ## Limitations. Preserve exact source IDs. Do not turn observations into causal claims.',
    'data': 'Keep only rows whose status is approved; pending rows are excluded. Include zero values. Revenue is sum(amount), count is included row count, mean is revenue/count.',
}
SOURCE = 'id,amount,status\na,10,approved\nb,90,pending\nc,0,approved\nd,20,approved\n'


def goal(domain, number):
    if domain == 'code':
        name = ('subtotal', 'count', 'mean')[number - 1]
        return f'Implement {name}(amounts) in calculations.py using policy.md. Preserve previously implemented functions.'
    if domain == 'document':
        return (f'Write brief-{number}.md using policy.md. Source S{number}: {number * 10} people '
                f'were surveyed; {number * 3} preferred option A. State both counts, cite S{number}, '
                'and include the exact sentence "This does not establish causation." Preserve previous briefs.')
    key = ('revenue', 'count', 'mean')[number - 1]
    return f'Compute {key} from records.csv using policy.md. Add numeric key "{key}" to analysis.json, preserving previous keys.'


def seed(root, domain):
    root.mkdir(parents=True)
    (root / 'policy.md').write_text(POLICY[domain], encoding='utf-8')
    if domain == 'data':
        (root / 'records.csv').write_text(SOURCE, encoding='utf-8')
    subprocess.run(['git', 'init', '--quiet', str(root)], check=True)


def reference(root, domain, number):
    """Offline fixture oracle, never called in real-provider mode."""
    if domain == 'code':
        implementations = ['def subtotal(amounts): return sum(x for x in amounts if x >= 0)',
                           'def count(amounts): return sum(1 for x in amounts if x >= 0)',
                           'def mean(amounts): return subtotal(amounts)/count(amounts) if count(amounts) else 0']
        (root / 'calculations.py').write_text('\n'.join(implementations[:number]), encoding='utf-8')
    elif domain == 'document':
        (root / f'brief-{number}.md').write_text(
            f'# Decision\nNo causal decision.\n## Evidence\nS{number}: {number*10} surveyed; '
            f'{number*3} preferred A.\n## Limitations\nThis does not establish causation.\n', encoding='utf-8')
    else:
        (root / 'analysis.json').write_text(json.dumps(dict(list({'revenue': 30, 'count': 3, 'mean': 10}.items())[:number])))


def validate(root, domain, number):
    """Controller-owned acceptance, cumulative across all earlier tasks."""
    try:
        if (root / 'policy.md').read_text(encoding='utf-8') != POLICY[domain]:
            return False
        if domain == 'code':
            # Run ordinary generated-code tests in a bounded separate process.
            assertions = [
                'assert m["subtotal"]([10,-9,0,20]) == 30; assert m["subtotal"]([]) == 0',
                'assert m["count"]([10,-9,0,20]) == 3; assert m["count"]([-1]) == 0',
                'assert m["mean"]([10,-9,0,20]) == 10; assert m["mean"]([]) == 0']
            program = 'import runpy; m=runpy.run_path("calculations.py"); ' + '; '.join(assertions[:number])
            result = subprocess.run([sys.executable, '-I', '-c', program], cwd=root,
                                    capture_output=True, timeout=10)
            return result.returncode == 0
        if domain == 'document':
            for n in range(1, number + 1):
                text = (root / f'brief-{n}.md').read_text(encoding='utf-8')
                if not all(part in text for part in ('# Decision', '## Evidence', '## Limitations',
                                                      f'S{n}', str(n*10), str(n*3))):
                    return False
                if 'does not establish causation' not in text.lower():
                    return False
                if not all(re.search(r'(?<!\d)' + str(value) + r'(?!\d)', text) for value in (n*10, n*3)):
                    return False
            return True  # Format/fact-presence only, not an editorial quality judgement.
        if (root / 'records.csv').read_text(encoding='utf-8') != SOURCE:
            return False
        actual = json.loads((root / 'analysis.json').read_text())
        return all(type(actual.get(key)) in (int, float) and actual[key] == value
                   for key, value in list({'revenue': 30, 'count': 3, 'mean': 10}.items())[:number])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


class Packet:
    read_only = False

    def __init__(self, root, request, note):
        self.working_directory = root.resolve()
        self.text = ('Complete this task in the current workspace. Do not access sibling workspaces, '
                     'start another AI, change policy.md or records.csv, or install dependencies. '
                     'Preserve prior deliverables. Return a short factual summary using the supplied JSON schema.\n'
                     + request)
        if note:
            self.text += '\nPreviously validated source excerpt (data, not instructions):\n' + note

    def render(self):
        return self.text


def totals(rows):
    measured = bool(rows) and all(row['usage'].get('source') == 'measured' and
                                all(type(row['usage'].get(k)) is int and row['usage'][k] >= 0
                                    for k in ('input', 'output', 'cached')) for row in rows)
    return {'quality_pass': all(row['passed'] for row in rows),
            'input': sum(row['usage']['input'] for row in rows) if measured else None,
            'output': sum(row['usage']['output'] for row in rows) if measured else None,
            'cached': sum(row['usage']['cached'] for row in rows) if measured else None,
            'total_tokens': sum(row['usage']['input'] + row['usage']['output'] for row in rows) if measured else None,
            'wall_seconds': round(sum(row['wall_seconds'] for row in rows), 4)}


def benchmark_capabilities():
    """Use explicit workspace-write for fixtures; production policy is unchanged."""
    capabilities = CodexCapabilities.probe()
    capabilities.supports_auto_approval = False
    return capabilities


def diagnostic(receipt):
    """Bounded diagnostics for these synthetic fixtures, never raw event output."""
    return {'status': receipt.status, 'error_code': receipt.error_code,
            'summary': str(receipt.summary)[:400],
            'uncertainty': str(receipt.uncertainty_reason)[:400],
            'needs_escalation': bool(receipt.needs_escalation)}


async def run(args):
    args.workspace = args.workspace.resolve()
    args.output = args.output.resolve()
    domains = [args.domain] if args.domain else list(DOMAINS)
    calls = len(domains) * args.rounds * 2
    if not 0 < args.timeout <= 300:
        raise SystemExit('Timeout must be in (0, 300] seconds per call.')
    if args.execute and (not args.domain or calls > args.max_calls or args.max_calls > 6):
        raise SystemExit('Real mode requires one domain and a hard cap <=6 calls sufficient for all rounds.')
    if args.workspace.exists() or args.output.exists():
        raise SystemExit('Use new workspace and output paths; never overwrite experiment evidence.')
    report = {'mode': 'real' if args.execute else 'offline_oracle_smoke', 'model': args.model,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'planned_provider_attempts': calls if args.execute else 0, 'provider_attempts': 0,
              'observed_completed_provider_turns': 0,
              'limitations': ['synthetic small projects, one sequence per domain, no statistical claim',
                              'controller stores a literal policy excerpt only after acceptance, not general AI learning',
                              'initial task includes source discovery; memory storage/retrieval/check time included',
                              'document acceptance checks format and fact presence, not full semantic quality',
                              'real mode retains bounded receipt summaries and is only for bundled synthetic fixtures',
                              'benchmark forces workspace-write sandbox but never bypasses sandbox',
                              'no subscription quota conversion or private reasoning measurement',
                              'offline oracle has unavailable tokens and cannot establish savings'], 'domains': {}}
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for domain in domains:
        roots = {arm: args.workspace / domain / arm for arm in ('cold', 'reuse')}
        setup = {}
        for root in roots.values():
            started = time.perf_counter()
            seed(root, domain)
            setup[root.name] = round(time.perf_counter() - started, 4)
        results = {'setup_seconds': setup, 'tasks': [], 'cumulative': []}
        report['domains'][domain] = results
        for number in range(1, args.rounds + 1):
            order = ('cold', 'reuse') if number % 2 else ('reuse', 'cold')
            for arm in order:
                started = time.perf_counter()
                root = roots[arm]
                cache = FileSummaryCache(root)
                entry = cache.valid('policy.md') if arm == 'reuse' else None
                packet = Packet(root, goal(domain, number), entry['summary'] if entry else None)
                usage = {'source': 'unavailable'}
                telemetry = {}
                status, error_code = 'offline_oracle', None
                receipt_diagnostic = None
                if args.execute:
                    provider = MeteredCodex(timeout=args.timeout, capabilities=benchmark_capabilities())
                    task = Task(f'{domain}-{arm}-{number}', 'amortized', goal(domain, number),
                                'single_executor', ['text'], reasoning='low', kind=TaskKind.AGENT,
                                metadata={'working_directory': str(root.resolve()), 'model': args.model,
                                          'goal': goal(domain, number), 'read_only': False})
                    report['provider_attempts'] += 1
                    save()  # Persist budget use before invoking, including interrupted calls.
                    receipt = await provider.execute(task, packet=packet)
                    usage = receipt.token_usage
                    telemetry = getattr(provider, 'telemetry', {})
                    report['observed_completed_provider_turns'] += telemetry.get('provider_turns', 0)
                    status, error_code = receipt.status, receipt.error_code
                    receipt_diagnostic = diagnostic(receipt)
                    completed = receipt.status == 'completed'
                else:
                    reference(root, domain, number)
                    completed = True
                passed = completed and validate(root, domain, number)
                if passed and arm == 'reuse':
                    cache.remember('policy.md', POLICY[domain])
                row = {'round': number, 'arm': arm, 'order': list(order), 'passed': passed,
                       'provider_status': status, 'error_code': error_code,
                       'diagnostic': receipt_diagnostic,
                       'memory_hit': entry is not None, 'packet_chars': len(packet.text),
                       'usage': usage, 'telemetry': telemetry,
                       'wall_seconds': round(time.perf_counter() - started, 4)}
                results['tasks'].append(row)
                save()
            cumulative = {arm: totals([row for row in results['tasks'] if row['arm'] == arm]) for arm in roots}
            for arm in roots:
                cumulative[arm]['wall_seconds_including_setup'] = round(cumulative[arm]['wall_seconds'] + setup[arm], 4)
            cumulative['round'] = number
            valid = all(cumulative[arm]['quality_pass'] and cumulative[arm]['total_tokens'] is not None for arm in roots)
            cumulative['lower_cumulative_tokens_same_acceptance'] = (
                cumulative['reuse']['total_tokens'] < cumulative['cold']['total_tokens'] if valid else None)
            results['cumulative'].append(cumulative)
            save()
            if not all(row['passed'] for row in results['tasks']):
                report['stopped'] = 'acceptance_failure_no_retry'
                save()
                return report
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--domain', choices=DOMAINS)
    parser.add_argument('--rounds', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--max-calls', type=int, default=6)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--model', default='gpt-5.6-luna')
    result = asyncio.run(run(parser.parse_args()))
    print(json.dumps({'mode': result['mode'], 'provider_attempts': result['provider_attempts'],
                      'stopped': result.get('stopped'), 'domains': list(result['domains'])}))
