"""Benchmark-owned PocketFlow acceptance contract.

This file lives outside provider workspaces. It is the sole quality gate for
paired benchmark validity; provider-authored tests are reported separately.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def _check(name: str, operation) -> dict[str, Any]:
    started = time.monotonic()
    try:
        detail = operation()
        passed = bool(detail if isinstance(detail, bool) else True)
        return {"name": name, "passed": passed, "detail": detail,
                "duration_seconds": time.monotonic() - started}
    except Exception as error:  # The contract must classify, not crash, a candidate.
        return {"name": name, "passed": False,
                "detail": f"{type(error).__name__}: {error}",
                "duration_seconds": time.monotonic() - started}


def _app_module(project: Path):
    candidates = [item for item in project.rglob("*.py")
                  if not any(part.startswith(".") or part in {"tests", "node_modules"}
                             for part in item.relative_to(project).parts)
                  and "FastAPI(" in item.read_text(encoding="utf-8", errors="replace")]
    if not candidates:
        raise AssertionError("FastAPI application not found")
    source = min(candidates, key=lambda item: (len(item.parts), item.as_posix()))
    relative = source.relative_to(project).with_suffix("")
    module_name = ".".join(relative.parts)
    sys.path.insert(0, str(project))
    try:
        return importlib.import_module(module_name)
    finally:
        if sys.path and sys.path[0] == str(project):
            sys.path.pop(0)


@contextmanager
def _client(project: Path) -> Iterator[tuple[Any, str, str]]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = _app_module(project)
    app = next((value for value in vars(module).values() if isinstance(value, FastAPI)), None)
    if app is None:
        raise AssertionError("FastAPI instance not exported")
    collection = next((route.path for route in app.routes
                       if "POST" in getattr(route, "methods", set())
                       and "expense" in route.path.lower() and "{" not in route.path), None)
    item = next((route.path for route in app.routes
                 if "expense" in route.path.lower() and "{" in route.path), None)
    if not collection or not item:
        raise AssertionError("Expense collection/item routes not found")
    with TestClient(app) as client:
        yield client, collection, item


def _item_path(template: str, item_id: Any) -> str:
    start, end = template.find("{"), template.find("}")
    return template[:start] + str(item_id) + template[end + 1:]


def _expense_payload(category: str = "food", date: str = "2026-01-31",
                     amount: float = 12.5) -> dict[str, Any]:
    return {"amount": amount, "category": category, "description": "benchmark expense",
            "date": date}


def _crud_contract(project: Path) -> dict[str, Any]:
    with _client(project) as (client, collection, item_template):
        created = client.post(collection, json=_expense_payload())
        assert created.status_code in {200, 201}, created.text
        body = created.json()
        required = {"id", "amount", "category", "description", "date"}
        assert required <= set(body), body
        item_id = body["id"]
        listed = client.get(collection)
        assert listed.status_code == 200 and any(row.get("id") == item_id for row in listed.json())
        single = client.get(_item_path(item_template, item_id))
        assert single.status_code == 200 and single.json().get("id") == item_id
        update_path = _item_path(item_template, item_id)
        updated = client.put(update_path, json=_expense_payload("travel", amount=15.25))
        if updated.status_code == 405:
            updated = client.patch(update_path, json=_expense_payload("travel", amount=15.25))
        assert updated.status_code == 200 and updated.json().get("category") == "travel"
        invalid = client.post(collection, json={"category": "missing-required-fields"})
        assert invalid.status_code in {400, 422}
    with _client(project) as (client, collection, item_template):
        persisted = client.get(_item_path(item_template, item_id))
        assert persisted.status_code == 200 and persisted.json().get("id") == item_id
        deleted = client.delete(_item_path(item_template, item_id))
        assert deleted.status_code in {200, 204}
    return {"collection": collection, "required_fields": sorted(required),
            "persistence": "new TestClient lifecycle"}


def _frontend_root(project: Path) -> Path:
    for candidate in (project / "frontend", project):
        if (candidate / "package.json").is_file():
            return candidate
    raise AssertionError("React package.json not found")


def _frontend_source(project: Path) -> tuple[Path, str]:
    root = _frontend_root(project)
    files = [item for suffix in ("*.js", "*.jsx", "*.ts", "*.tsx")
             for item in (root / "src").rglob(suffix)] if (root / "src").is_dir() else []
    files = [item for item in files if ".test." not in item.name and ".spec." not in item.name]
    if not files:
        raise AssertionError("React source entry not found")
    return root, "\n".join(item.read_text(encoding="utf-8", errors="replace").lower()
                            for item in files)


def _frontend_contract(project: Path) -> dict[str, Any]:
    root, source = _frontend_source(project)
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    assert "build" in package.get("scripts", {}), "frontend build script missing"
    npm = "npm.cmd" if os.name == "nt" else "npm"
    built = subprocess.run([npm, "run", "build"], cwd=root, capture_output=True,
                           text=True, timeout=180, check=False)
    assert built.returncode == 0, (built.stdout + built.stderr)[-1200:]
    assert ("fetch(" in source or "axios" in source) and "expense" in source
    assert "loading" in source and "error" in source
    assert all(field in source for field in ("amount", "category", "date"))
    return {"root": root.relative_to(project).as_posix() or ".",
            "build": "PASS", "states": ["loading", "error"]}


def _category_contract(project: Path) -> dict[str, Any]:
    with _client(project) as (client, collection, _):
        client.post(collection, json=_expense_payload("food", "2026-02-01", 10))
        client.post(collection, json=_expense_payload("travel", "2026-02-02", 20))
        filtered = client.get(collection, params={"category": "food"})
        assert filtered.status_code == 200
        rows = filtered.json()
        assert rows and all(str(row.get("category", "")).lower() == "food" for row in rows)
        app = client.app
        breakdown = next((route.path for route in app.routes
                          if "GET" in getattr(route, "methods", set())
                          and any(word in route.path.lower() for word in ("breakdown", "categor"))
                          and "{" not in route.path), None)
        assert breakdown, "category breakdown route not found"
        response = client.get(breakdown)
        assert response.status_code == 200
        encoded = json.dumps(response.json()).lower()
        assert "food" in encoded and "travel" in encoded
    _, source = _frontend_source(project)
    assert "category" in source and any(word in source for word in ("breakdown", "spending by"))
    return {"filter": "PASS", "breakdown": breakdown}


def _month_boundary_contract(project: Path) -> dict[str, Any]:
    with _client(project) as (client, collection, _):
        jan = client.post(collection, json=_expense_payload("edge", "2026-01-31", 11)).json()
        feb = client.post(collection, json=_expense_payload("edge", "2026-02-01", 22)).json()
        response = client.get(collection, params={"month": "2026-01"})
        assert response.status_code == 200
        ids = {row.get("id") for row in response.json()}
        assert jan.get("id") in ids and feb.get("id") not in ids
    return {"month": "2026-01", "included": "2026-01-31", "excluded": "2026-02-01"}


def _monthly_report_contract(project: Path) -> dict[str, Any]:
    with _client(project) as (client, collection, _):
        client.post(collection, json=_expense_payload("food", "2026-03-01", 10))
        client.post(collection, json=_expense_payload("travel", "2026-03-15", 20))
        client.post(collection, json=_expense_payload("food", "2026-04-01", 99))
        report = next((route.path for route in client.app.routes
                       if "GET" in getattr(route, "methods", set())
                       and any(word in route.path.lower() for word in ("report", "summary"))
                       and "{" not in route.path), None)
        assert report, "monthly report route not found"
        response = client.get(report, params={"month": "2026-03"})
        assert response.status_code == 200
        body = response.json()
        encoded = json.dumps(body).lower()
        numbers = [value for value in _walk_values(body) if isinstance(value, (int, float))]
        assert any(abs(float(value) - 30.0) < 0.001 for value in numbers), body
        assert "food" in encoded and "travel" in encoded
    _, source = _frontend_source(project)
    assert "month" in source and any(word in source for word in ("report", "summary"))
    return {"month": "2026-03", "total": 30.0, "categories": ["food", "travel"]}


def _walk_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value


def run_acceptance(project: Path, task_number: int) -> dict[str, Any]:
    project = project.resolve()
    checks = [_check("external_backend_crud_persistence", lambda: _crud_contract(project))]
    if task_number >= 2:
        checks.append(_check("external_react_build_and_states", lambda: _frontend_contract(project)))
    if task_number >= 3:
        checks.append(_check("external_category_filter_and_breakdown",
                             lambda: _category_contract(project)))
    if task_number >= 4:
        checks.append(_check("external_month_boundary_regression",
                             lambda: _month_boundary_contract(project)))
    if task_number >= 5:
        checks.append(_check("external_monthly_report", lambda: _monthly_report_contract(project)))
    return {"contract": "pocketflow-v1", "task_number": task_number,
            "passed": all(item["passed"] for item in checks), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--task", type=int, required=True, choices=range(1, 6))
    args = parser.parse_args()
    result = run_acceptance(args.project, args.task)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
