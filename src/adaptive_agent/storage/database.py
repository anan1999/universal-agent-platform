from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 8

#: Additive columns introduced after a schema was first created. Every entry is
#: `(table, column, definition)` and is applied only when the column is missing.
ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # measured usage and orchestration ownership
    ("token_usage", "cached_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("token_usage", "token_source", "TEXT NOT NULL DEFAULT 'estimated'"),
    ("runs", "orchestration_owner", "TEXT NOT NULL DEFAULT 'universal-agent-platform'"),
    ("runs", "entry_source", "TEXT NOT NULL DEFAULT 'cli'"),
    # v5 — universal platform
    ("runs", "work_profiles", "TEXT NOT NULL DEFAULT ''"),
    ("runs", "composition_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("token_usage", "provider", "TEXT NOT NULL DEFAULT ''"),
    ("token_usage", "invocation_count", "INTEGER NOT NULL DEFAULT 1"),
    ("token_usage", "provider_tool_calls", "INTEGER NOT NULL DEFAULT 0"),
    ("token_usage", "provider_messages", "INTEGER NOT NULL DEFAULT 0"),
    ("token_usage", "attribution_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("agent_performance", "provider", "TEXT NOT NULL DEFAULT ''"),
    ("agent_performance", "capability_signature", "TEXT NOT NULL DEFAULT ''"),
    ("agent_performance", "work_profile", "TEXT NOT NULL DEFAULT ''"),
    ("agent_performance", "complexity", "TEXT NOT NULL DEFAULT ''"),
    ("agent_performance", "evaluation_result", "TEXT NOT NULL DEFAULT ''"),
    ("artifacts", "artifact_type", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("tasks", "kind", "TEXT NOT NULL DEFAULT 'agent'"),
)

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL, type TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, project_id TEXT, goal TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT, FOREIGN KEY(project_id) REFERENCES projects(id));
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, title TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL, data_json TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(id));
            CREATE TABLE IF NOT EXISTS agents(name TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL, data_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS agent_instances(id TEXT PRIMARY KEY, name TEXT NOT NULL, run_id TEXT, context_health TEXT NOT NULL, data_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY, enabled INTEGER NOT NULL, data_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, run_id TEXT, timestamp TEXT NOT NULL, event TEXT NOT NULL, agent TEXT, task_id TEXT, metadata_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, sender TEXT NOT NULL, recipient TEXT NOT NULL, status TEXT NOT NULL, data_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, agent TEXT NOT NULL, status TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS token_usage(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, task_id TEXT, agent TEXT, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, estimated INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS agent_performance(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_role TEXT NOT NULL, model TEXT, task_type TEXT NOT NULL, capability TEXT, success INTEGER NOT NULL, duration REAL NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, token_source TEXT NOT NULL, escalated INTEGER NOT NULL DEFAULT 0, retry_count INTEGER NOT NULL DEFAULT 0, timestamp TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, path TEXT NOT NULL, kind TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS agent_skills(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, skill_id TEXT NOT NULL, source TEXT NOT NULL, configured INTEGER NOT NULL DEFAULT 0, loaded INTEGER NOT NULL DEFAULT 0, loaded_at TEXT DEFAULT CURRENT_TIMESTAMP, run_id TEXT, task_id TEXT);
            CREATE TABLE IF NOT EXISTS skill_versions(skill_id TEXT NOT NULL, version TEXT NOT NULL, trust TEXT NOT NULL, status TEXT NOT NULL, manifest_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(skill_id,version));
            CREATE TABLE IF NOT EXISTS skill_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, skill_id TEXT NOT NULL, version TEXT NOT NULL, run_id TEXT, task_id TEXT, success INTEGER NOT NULL, artifact_quality REAL, invocations INTEGER NOT NULL DEFAULT 0, tokens INTEGER, token_source TEXT NOT NULL DEFAULT 'unavailable', context_tokens INTEGER, provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', safety_failure INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS run_skills(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, task_id TEXT NOT NULL, skill_id TEXT NOT NULL, version TEXT NOT NULL, loaded_references_json TEXT NOT NULL DEFAULT '[]', context_tokens INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS artifact_evaluations(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, task_id TEXT NOT NULL, evaluator TEXT NOT NULL, passed INTEGER NOT NULL, quality_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS project_intelligence_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE, temperature TEXT NOT NULL, reason TEXT NOT NULL, reuse_hits INTEGER NOT NULL DEFAULT 0, rediscovery_count INTEGER NOT NULL DEFAULT 0, context_chars INTEGER NOT NULL DEFAULT 0, estimated_tokens INTEGER NOT NULL DEFAULT 0, data_json TEXT NOT NULL DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            """)
            existing: dict[str, set[str]] = {}
            for table, column, definition in ADDITIVE_COLUMNS:
                if table not in existing:
                    existing[table] = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if column not in existing[table]:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    existing[table].add(column)
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_skill_task ON agent_skills(agent_id,skill_id,run_id,task_id)")
            db.execute("CREATE INDEX IF NOT EXISTS ix_performance_signature ON agent_performance(capability_signature)")
            db.execute("CREATE INDEX IF NOT EXISTS ix_skill_runs_identity ON skill_runs(skill_id,version)")
            db.execute("CREATE INDEX IF NOT EXISTS ix_run_skills_run ON run_skills(run_id,task_id)")
            db.execute("CREATE INDEX IF NOT EXISTS ix_intelligence_temperature ON project_intelligence_runs(temperature)")
            db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        with self.connect() as db:
            db.execute(sql, parameters)

    def query(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, parameters).fetchall()]

    @staticmethod
    def json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def loads(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            decoded = json.loads(value or "{}")
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
