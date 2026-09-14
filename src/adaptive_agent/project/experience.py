"""Small, local evidence of successful procedures, never cached test results."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

TOOLS = {"project_test", "project_build"}
TTL = 7 * 86400
MAX_INPUT = 1024 * 1024


class OperationExperience:
    """No provider calls, raw commands, logs, secrets or unbounded history."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / '.agent/cache/operations.sqlite3'

    def fingerprint(self) -> str | None:
        # Conservative invalidation: root-level manifests/config and declared command
        # configuration. This is an environment hint, not a dependency lock guarantee.
        paths = [self.root / '.agent/commands.yaml']
        try:
            for number, path in enumerate(self.root.iterdir()):
                if number >= 256:
                    return None
                if path.is_file() and (path.suffix in {'.json', '.toml', '.yaml', '.yml', '.lock', '.ini'}
                                      or path.name.startswith('requirements')):
                    paths.append(path)
            evidence = [str(self.root), sys.executable, sys.version, platform.platform(),
                        {key: os.environ.get(key, '') for key in
                         ('PATH', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'PYTHONPATH')}]
            total = 0
            for path in sorted(set(paths)):
                if not path.resolve().is_relative_to(self.root) or not path.is_file():
                    return None
                with path.open('rb') as stream:
                    content = stream.read(MAX_INPUT + 1)
                if len(content) > MAX_INPUT:
                    return None
                total += len(content)
                if total > 4 * MAX_INPUT:
                    return None
                evidence.append((path.name, hashlib.sha256(content).hexdigest()))
            return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        except OSError:
            return None

    def _connect(self):
        if not self.path.resolve().is_relative_to(self.root):
            raise OSError('Experience path leaves project')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=2)
        connection.execute('CREATE TABLE IF NOT EXISTS operations '
                           '(tool TEXT PRIMARY KEY, fingerprint TEXT, verified REAL, successes INTEGER)')
        return connection

    def record(self, result, before: str | None) -> bool:
        if result.tool not in TOOLS:
            return False
        try:
            with closing(self._connect()) as db, db:
                if (result.status != 'completed' or result.exit_code != 0
                        or before is None or before != self.fingerprint()):
                    db.execute('DELETE FROM operations WHERE tool = ?', (result.tool,))
                    return False
                db.execute('INSERT INTO operations VALUES (?, ?, ?, 1) '
                           'ON CONFLICT(tool) DO UPDATE SET fingerprint=excluded.fingerprint, '
                           'verified=excluded.verified, successes=CASE WHEN '
                           'operations.fingerprint=excluded.fingerprint THEN operations.successes+1 ELSE 1 END',
                           (result.tool, before, time.time()))
                return True
        except (OSError, sqlite3.Error):
            return False  # Memory must never turn a completed check into a failure.

    def reusable(self) -> list[dict]:
        if not self.path.exists():
            return []
        fingerprint = self.fingerprint()
        if fingerprint is None:
            return []
        try:
            with closing(self._connect()) as db, db:
                rows = db.execute('SELECT tool, successes FROM operations '
                                  'WHERE fingerprint=? AND verified>=? AND verified<=? ORDER BY tool LIMIT 2',
                                  (fingerprint, time.time() - TTL, time.time())).fetchall()
            return [{'tool': tool, 'invoke': f'agentctl check {tool} --experience',
                     'successful_runs': count, 'cwd': 'project_root',
                     'scope': 'procedure_only_rerun_for_current_changes'}
                    for tool, count in rows if tool in TOOLS]
        except (OSError, sqlite3.Error):
            return []
