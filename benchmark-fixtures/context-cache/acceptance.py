"""Benchmark-owned acceptance for the context-cache pair."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def evaluate(project: Path) -> dict:
    sys.path.insert(0, str(project))
    try:
        module = importlib.import_module("app.main")
        database = getattr(module, "DATABASE", project / "expenses.sqlite3")
        Path(database).unlink(missing_ok=True)
        with TestClient(module.app) as client:
            for payload in (
                {"amount": 10, "category": "food", "description": "lunch", "date": "2026-01-03"},
                {"amount": 5.5, "category": "travel", "description": "bus", "date": "2026-01-31"},
                {"amount": 99, "category": "other", "description": "next month", "date": "2026-02-01"},
            ):
                assert client.post("/expenses", json=payload).status_code in {200, 201}
            response = client.get("/reports/monthly/2026-01")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["month"] == "2026-01"
            assert body["total"] == 15.5
            # The task specifies totals by category, not a wire-key spelling.
            # Accept the two conventional shapes while keeping values strict.
            categories = body.get("categories", body.get("by_category"))
            assert categories == {"food": 10.0, "travel": 5.5}
        source = (project / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        lowered = source.lower()
        assert "/reports/monthly" in source
        assert "total" in lowered and "categor" in lowered
        return {"passed": True, "contract": "context-cache-monthly-v1", "error": None}
    except Exception as error:  # benchmark process reports the exact external failure
        return {"passed": False, "contract": "context-cache-monthly-v1",
                "error": f"{type(error).__name__}: {error}"}
    finally:
        sys.path.pop(0)
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                sys.modules.pop(name, None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.project.resolve())
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
