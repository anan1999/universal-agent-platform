from __future__ import annotations

import os
from pathlib import Path

from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.storage.database import Database


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def platform_home() -> Path:
    configured = os.getenv("UNIVERSAL_AGENT_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".universal-agent-platform")


def database() -> Database:
    return Database(platform_home() / "data" / "platform.db")


def event_bus(db: Database) -> EventBus:
    return EventBus(db, platform_home() / "logs" / "events.jsonl")
