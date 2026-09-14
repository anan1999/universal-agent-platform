"""Benchmark-owned acceptance for the context-cache pair."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


SUITE = json.loads((Path(__file__).parent / "suite.json").read_text(encoding="utf-8"))
TASKS = {item["id"]: item for item in SUITE["tasks"]}


def _seed(client: TestClient) -> None:
    for payload in (
        {"amount": 10, "category": "food", "description": "lunch", "date": "2026-01-03"},
        {"amount": 5.5, "category": "travel", "description": "bus", "date": "2026-01-31"},
        {"amount": 99, "category": "other", "description": "next month", "date": "2026-02-01"},
    ):
        assert client.post("/expenses", json=payload).status_code in {200, 201}


def _monthly(client: TestClient) -> None:
    response = client.get("/reports/monthly/2026-01")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["month"] == "2026-01"
    assert body["total"] == 15.5
    categories = body.get("categories", body.get("by_category"))
    assert categories == {"food": 10.0, "travel": 5.5}


def evaluate(project: Path, task_id: str = "large") -> dict:
    task = TASKS[task_id]
    sys.path.insert(0, str(project))
    try:
        module = importlib.import_module("app.main")
        database = getattr(module, "DATABASE", project / "expenses.sqlite3")
        Path(database).unlink(missing_ok=True)
        with TestClient(module.app) as client:
            _seed(client)
            if task_id == "small":
                response = client.get("/reports/summary")
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["expense_count"] == 3
                assert body["total"] == 114.5
            else:
                _monthly(client)
        if task_id == "large":
            source = (project / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
            lowered = source.lower()
            assert "/reports/monthly" in source
            assert "total" in lowered and "categor" in lowered
        return {"passed": True, "contract": task["acceptance_contract"], "error": None}
    except Exception as error:  # benchmark process reports the exact external failure
        return {"passed": False, "contract": task["acceptance_contract"],
                "error": f"{type(error).__name__}: {error}"}
    finally:
        sys.path.pop(0)
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                sys.modules.pop(name, None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--task", choices=tuple(TASKS), default="large")
    args = parser.parse_args()
    result = evaluate(args.project.resolve(), args.task)
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
