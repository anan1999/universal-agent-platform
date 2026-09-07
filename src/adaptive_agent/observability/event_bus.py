from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from adaptive_agent.core.models import Event
from adaptive_agent.storage.database import Database


class EventBus:
    def __init__(self, database: Database, jsonl_path: Path | None = None):
        self.database = database
        self.jsonl_path = jsonl_path
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def emit(self, event: Event) -> Event:
        data = event.to_dict()
        self.database.execute(
            "INSERT INTO events(id,run_id,timestamp,event,agent,task_id,metadata_json) VALUES(?,?,?,?,?,?,?)",
            (event.id, event.run_id, event.timestamp, event.event, event.agent, event.task_id, self.database.json(event.metadata)),
        )
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as stream:
                stream.write(self.database.json(data) + "\n")
        for queue in tuple(self._subscribers):
            queue.put_nowait(event)
        return event

    async def subscribe(self) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

