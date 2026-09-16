"""Deterministic stress checks of completed programming and animation artifacts.

These checks are separate from the per-turn acceptance and never modify the
provider source files. They probe robustness beyond the scripted examples.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from decimal import Decimal
from pathlib import Path

from PIL import Image

try:
    from scripts.same_task_domain_quality import _load, _xyz
except ModuleNotFoundError:
    from same_task_domain_quality import _load, _xyz


def programming(root: Path) -> dict:
    tracker = _load(root / "tracker.py").ExpenseTracker()
    rng = random.Random(73119)
    expected: dict[int, dict] = {}
    months = ("2026-01", "2026-02", "2026-03")
    categories = ("Food", "Travel", "Books")
    attempts = 180
    errors: list[str] = []
    for step in range(attempts):
        choice = rng.random()
        if choice < .62 or not expected:
            cents = rng.randint(1, 250_000)
            amount = f"{Decimal(cents) / 100:.2f}"
            category = rng.choice(categories)
            date = rng.choice(months) + f"-{rng.randint(1,28):02d}"
            note = f"expense {step}, 咖啡"
            eid = tracker.add(amount, category, date, note)
            expected[eid] = {"id": eid, "amount": amount, "category": category,
                             "date": date, "note": note}
        elif choice < .82:
            eid = rng.choice(list(expected))
            cents = rng.randint(1, 250_000)
            amount = f"{Decimal(cents) / 100:.2f}"
            assert tracker.update(eid, amount=amount) is True
            expected[eid]["amount"] = amount
        else:
            eid = rng.choice(list(expected))
            assert tracker.delete(eid) is True
            del expected[eid]
        if tracker.list() != list(expected.values()):
            errors.append(f"record_mismatch_after_step_{step}")
            break
        for month in months:
            total = sum((Decimal(row["amount"]) for row in expected.values()
                         if row["date"].startswith(month)), Decimal("0.00"))
            if tracker.monthly(month) != f"{total:.2f}":
                errors.append(f"monthly_mismatch_after_step_{step}:{month}")
                break
        if errors:
            break
    for category in categories:
        expected_ids = [row["id"] for row in expected.values() if row["category"] == category]
        actual_ids = [row["id"] for row in tracker.filter(" " + category.swapcase() + " ")]
        if actual_ids != expected_ids:
            errors.append("category_filter_mismatch:" + category)
    saved = root / ".stress-ledger.json"
    tracker.save(saved)
    loaded = type(tracker).load(saved)
    if loaded.list() != tracker.list():
        errors.append("persistence_roundtrip_mismatch")
    restored = type(tracker)()
    restored.from_csv(tracker.to_csv())
    without_id = lambda rows: [{k: v for k, v in row.items() if k != "id"} for row in rows]
    if without_id(restored.list()) != without_id(tracker.list()):
        errors.append("csv_roundtrip_mismatch")
    return {"passed": not errors, "operations": attempts, "remaining_records": len(expected),
            "errors": errors}


def animation(root: Path) -> dict:
    module = _load(root / "animation.py")
    errors: list[str] = []
    samples = [i / 32 for i in range(32)]
    paths = {name: [_xyz(module.scene_at(t)[name]) for t in samples]
             for name in ("planet", "satellite", "moon")}
    for name, points in paths.items():
        if any(not all(math.isfinite(value) for value in point) for point in points):
            errors.append(name + "_nonfinite")
        if name != "planet" and len({tuple(round(value, 3) for value in point)
                                     for point in points}) < 20:
            errors.append(name + "_insufficient_motion")
        if math.dist(_xyz(module.scene_at(0)[name]),
                     _xyz(module.scene_at(1)[name])) > 1e-4:
            errors.append(name + "_loop_gap")
    hashes = []
    for t in (i / 12 for i in range(12)):
        frame = module.render_frame(t, size=(320, 240)).convert("RGB")
        if frame.size != (320, 240):
            errors.append("frame_size")
        hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
    if len(set(hashes)) < 9:
        errors.append("insufficient_distinct_frames")
    exports = []
    for size in ((320, 240), (640, 480)):
        target = root / f".stress-{size[0]}x{size[1]}.gif"
        module.render_gif(target, frames=16, size=size)
        with Image.open(target) as gif:
            count = gif.n_frames
            loop = gif.info.get("loop")
            if gif.size != size or count < 12 or loop != 0:
                errors.append(f"gif_export_{size[0]}x{size[1]}")
            exports.append({"size": size, "frames": count, "bytes": target.stat().st_size})
    return {"passed": not errors, "scene_samples": len(samples), "frame_samples": len(hashes),
            "distinct_frame_hashes": len(set(hashes)), "exports": exports, "errors": errors}


def run(programming_workspace: Path, animation_workspace: Path) -> dict:
    results = {"method": "deterministic_final_artifact_stress_v1", "domains": {}}
    for domain, workspace, checker in (
            ("programming", programming_workspace, programming),
            ("animation", animation_workspace, animation)):
        results["domains"][domain] = {
            arm: checker(workspace.resolve() / arm) for arm in ("baseline", "uap")}
    results["all_passed"] = all(
        item["passed"] for domain in results["domains"].values() for item in domain.values())
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--programming-workspace", type=Path, required=True)
    parser.add_argument("--animation-workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.programming_workspace, args.animation_workspace)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
