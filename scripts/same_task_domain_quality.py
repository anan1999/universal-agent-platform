"""Independent cumulative runtime checks for two coherent 10-turn tasks.

The checks verify executable behavior and animation frames, not subjective
code style or artistic merit. Generated modules run in the benchmark workspace.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import math
import sys
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageChops


PROGRAMMING_GOALS = [
    "Start a small personal expense tracker in tracker.py. Provide ExpenseTracker with add(amount, category, date, note='') returning a stable integer ID, and list() returning ID-ordered dictionaries with id, amount, category, date, note. Store money as two-decimal strings using Decimal.",
    "The form can receive bad data. Reject zero or negative amounts, malformed ISO dates, and blank categories with ValueError; a rejected add must not change the ledger. Keep add/list behavior.",
    "I need to browse one category at a time. Add filter(category), returning matching expense dictionaries in ID order; category matching should ignore case and surrounding spaces.",
    "For the monthly overview, add monthly('YYYY-MM') returning a two-decimal total string. Include exactly that calendar month and keep cents exact.",
    "I want to export my current list. Add to_csv() returning CSV text with header id,amount,category,date,note. Preserve commas, quotes, and Unicode in notes.",
    "Let me import a CSV made by this app. Add from_csv(text) to the existing tracker, returning the number imported. Assign new stable IDs; if any row is invalid, import nothing and raise ValueError.",
    "People make corrections. Add update(id, *, amount=None, category=None, date=None, note=None), returning True for an existing record and False for a missing ID. Use the same validation and preserve its ID.",
    "I also need to remove a mistaken entry. Add delete(id), returning True when deleted and False when missing. Existing IDs must never be reused.",
    "Make the list survive a restart. Add save(path) writing JSON safely, and ExpenseTracker.load(path) restoring the records and next ID. Preserve cents, Unicode, and stable IDs.",
    "For the finished overview, add summary(month) returning exactly month, count, total, by_category. Totals are two-decimal strings, by_category maps names to two-decimal totals, and it includes only the selected month. Keep all previous behavior and tests green.",
]

ANIMATION_GOALS = [
    "Create animation.py for the orbital courier scene. Provide scene_at(t) with 3D planet and satellite coordinates for phase t in [0,1], render_frame(t, size=(320,240)) returning a Pillow image, and render_gif(path, frames=24, size=(320,240)) producing a moving GIF. Use real x/y/z motion and perspective, not a static poster.",
    "The first orbit feels too flat. Tilt it and make it visibly elliptical: the courier should vary in depth and move through a wider horizontal than vertical arc, while the camera still sees the planet clearly.",
    "Add a small moon orbiting the planet in the same 3D scene. Expose its 3D location as scene_at(t)['moon'] and show it in rendered frames without obscuring the courier.",
    "The courier needs a sense of spin. Expose scene_at(t)['satellite_orientation'] as an angle that changes over the loop and make the rendered courier visibly rotate or change highlight direction.",
    "Improve depth cues without changing the story: give the planet, courier, and moon distinct color/lighting treatments so foreground and background remain distinguishable.",
    "Introduce a gentle moving camera. Provide camera_at(t) as a 3D position, vary it through the loop, and keep the main objects safely inside the frame.",
    "Add near and far star layers with subtle parallax relative to the moving camera. Expose scene_at(t)['stars_near'] and ['stars_far'] as 3D point lists, and keep the stars secondary to the subject.",
    "The loop must be seamless. Make scene_at(0) and scene_at(1) agree for the major objects and camera, without a position jump at the wrap.",
    "Add a restrained title to the animation, 'Orbital Courier', without hiding the moving objects. Expose the exact title as TITLE in animation.py and keep it readable at the standard export size.",
    "Finish both preview and presentation exports: render_gif should accept 320x240 and 640x480 sizes and at least 12 frames, preserve animation movement, and write a looping GIF. Keep the earlier 3D motion, camera, stars, and title.",
]

GOALS = {"programming": PROGRAMMING_GOALS, "animation": ANIMATION_GOALS}


def _load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("benchmark_candidate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import artifact")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _probe(checks: dict[str, bool], name: str, action: Callable[[], None]) -> None:
    try:
        action()
    except Exception:
        checks[name] = False
    else:
        checks[name] = True


def evaluate_programming(root: Path, turn: int) -> dict[str, Any]:
    path = root / "tracker.py"
    if not path.is_file():
        return _report(turn, {"tracker_module": False}, "programming")
    try:
        cls = _load(path).ExpenseTracker
    except Exception:
        return _report(turn, {"tracker_import": False}, "programming")
    checks: dict[str, bool] = {}

    def core() -> None:
        ledger = cls()
        a = ledger.add("12.30", "Food", "2026-01-05", "Lunch")
        b = ledger.add("0.20", "Travel", "2026-02-01", "Bus")
        rows = ledger.list()
        assert type(a) is int and b > a
        assert [row["id"] for row in rows] == [a, b]
        assert rows[0]["amount"] == "12.30" and rows[0]["note"] == "Lunch"

    _probe(checks, "add_list_stable_ids_and_decimal", core)
    if turn >= 2:
        def validation() -> None:
            ledger = cls()
            for amount, category, date in (("0", "Food", "2026-01-01"),
                                           ("-1.00", "Food", "2026-01-01"),
                                           ("1.00", " ", "2026-01-01"),
                                           ("1.00", "Food", "2026-02-30")):
                try:
                    ledger.add(amount, category, date)
                except ValueError:
                    pass
                else:
                    raise AssertionError("invalid expense accepted")
            assert ledger.list() == []
        _probe(checks, "invalid_add_is_atomic", validation)
    if turn >= 3:
        def category_filter() -> None:
            ledger = cls()
            a = ledger.add("1.00", "Food", "2026-01-01")
            ledger.add("2.00", "Other", "2026-01-02")
            assert [row["id"] for row in ledger.filter(" food ")] == [a]
        _probe(checks, "category_filter", category_filter)
    if turn >= 4:
        def monthly() -> None:
            ledger = cls()
            ledger.add("0.10", "Food", "2026-01-01")
            ledger.add("0.20", "Food", "2026-01-31")
            ledger.add("99.00", "Food", "2026-02-01")
            assert ledger.monthly("2026-01") == "0.30"
        _probe(checks, "monthly_decimal_boundary", monthly)
    if turn >= 5:
        def csv_export() -> None:
            ledger = cls()
            ledger.add("5.60", "Food", "2026-01-01", '咖啡, "large"')
            rows = list(csv.DictReader(io.StringIO(ledger.to_csv())))
            assert list(rows[0]) == ["id", "amount", "category", "date", "note"]
            assert rows[0]["note"] == '咖啡, "large"'
        _probe(checks, "csv_export_escaping", csv_export)
    if turn >= 6:
        def csv_import() -> None:
            original = cls()
            original.add("1.00", "Food", "2026-01-01", "first")
            target = cls()
            target.add("2.00", "Other", "2026-01-02", "existing")
            assert target.from_csv(original.to_csv()) == 1
            assert len(target.list()) == 2 and target.list()[1]["id"] > target.list()[0]["id"]
            before = target.list()
            bad = "id,amount,category,date,note\n1,3.00,Food,2026-01-01,ok\n2,-1.00,Food,2026-01-02,bad\n"
            try:
                target.from_csv(bad)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid import accepted")
            assert target.list() == before
        _probe(checks, "csv_import_atomic", csv_import)
    if turn >= 7:
        def update() -> None:
            ledger = cls()
            eid = ledger.add("1.00", "Food", "2026-01-01")
            assert ledger.update(eid, amount="2.50", note="fixed") is True
            assert ledger.list()[0]["id"] == eid and ledger.list()[0]["amount"] == "2.50"
            assert ledger.update(999, note="missing") is False
        _probe(checks, "update_preserves_id", update)
    if turn >= 8:
        def deletion() -> None:
            ledger = cls()
            first = ledger.add("1.00", "Food", "2026-01-01")
            assert ledger.delete(first) is True and ledger.delete(first) is False
            second = ledger.add("2.00", "Food", "2026-01-02")
            assert second > first
        _probe(checks, "delete_never_reuses_id", deletion)
    if turn >= 9:
        def persistence() -> None:
            target = root / ".quality-ledger.json"
            ledger = cls()
            first = ledger.add("1.25", "Food", "2026-01-01", "咖啡")
            ledger.save(target)
            restored = cls.load(target)
            assert restored.list() == ledger.list()
            assert restored.add("1.00", "Food", "2026-01-02") > first
        _probe(checks, "json_roundtrip", persistence)
    if turn >= 10:
        def summary() -> None:
            ledger = cls()
            ledger.add("0.10", "Food", "2026-01-01")
            ledger.add("0.20", "Food", "2026-01-31")
            ledger.add("1.00", "Travel", "2026-01-02")
            ledger.add("9.00", "Travel", "2026-02-01")
            result = ledger.summary("2026-01")
            assert set(result) == {"month", "count", "total", "by_category"}
            assert result["month"] == "2026-01" and result["count"] == 3
            assert result["total"] == "1.30"
            assert result["by_category"] == {"Food": "0.30", "Travel": "1.00"}
        _probe(checks, "monthly_category_summary", summary)
    return _report(turn, checks, "programming")


def _xyz(value: Any) -> tuple[float, float, float]:
    if isinstance(value, dict):
        value = value["position"]
    assert len(value) == 3
    result = tuple(float(component) for component in value)
    assert all(math.isfinite(component) for component in result)
    return result  # type: ignore[return-value]


def evaluate_animation(root: Path, turn: int, source: Path | None = None) -> dict[str, Any]:
    path = source or root / "animation.py"
    if not path.is_file():
        return _report(turn, {"animation_module": False}, "animation")
    try:
        module = _load(path)
    except Exception:
        return _report(turn, {"animation_import": False}, "animation")
    checks: dict[str, bool] = {}

    def motion() -> None:
        samples = [module.scene_at(i / 8) for i in range(8)]
        for sample in samples:
            _xyz(sample["planet"])
            _xyz(sample["satellite"])
        coords = [_xyz(sample["satellite"]) for sample in samples]
        assert len({tuple(round(value, 3) for value in row) for row in coords}) >= 6
        assert max(row[2] for row in coords) - min(row[2] for row in coords) > 0.05
    _probe(checks, "true_3d_motion", motion)

    def frames() -> None:
        first = module.render_frame(0, size=(320, 240))
        later = module.render_frame(.25, size=(320, 240))
        assert isinstance(first, Image.Image) and first.size == (320, 240)
        assert isinstance(later, Image.Image) and ImageChops.difference(first.convert("RGB"), later.convert("RGB")).getbbox()
    _probe(checks, "moving_rendered_frames", frames)

    def gif() -> None:
        target = root / ".quality-animation.gif"
        module.render_gif(target, frames=8, size=(320, 240))
        with Image.open(target) as result:
            assert result.size == (320, 240) and result.n_frames >= 7
            assert result.info.get("loop") == 0
    _probe(checks, "looping_gif_export", gif)
    if turn >= 2:
        def orbit() -> None:
            rows = [_xyz(module.scene_at(i / 16)["satellite"]) for i in range(16)]
            spans = [max(row[axis] for row in rows) - min(row[axis] for row in rows) for axis in range(3)]
            assert min(spans) > 0.05 and spans[0] > spans[1] * 1.05
        _probe(checks, "tilted_elliptical_orbit", orbit)
    if turn >= 3:
        def moon() -> None:
            first, later = module.scene_at(0), module.scene_at(.25)
            a, b = _xyz(first["moon"]), _xyz(later["moon"])
            assert a != b and math.dist(a, _xyz(first["planet"])) > 0
        _probe(checks, "moon_3d_motion", moon)
    if turn >= 4:
        def spin() -> None:
            start, later = module.scene_at(0), module.scene_at(.25)
            a = float(start.get("satellite_orientation", start["satellite"].get("orientation")
                          if isinstance(start["satellite"], dict) else None))
            b = float(later.get("satellite_orientation", later["satellite"].get("orientation")
                          if isinstance(later["satellite"], dict) else None))
            assert math.isfinite(a) and math.isfinite(b) and a != b
        _probe(checks, "courier_orientation_changes", spin)
    if turn >= 5:
        def lighting() -> None:
            frame = module.render_frame(.25, size=(320, 240)).convert("RGB")
            assert len(frame.getcolors(maxcolors=1_000_000) or []) >= 8
        _probe(checks, "render_color_depth", lighting)
    if turn >= 6:
        def camera() -> None:
            a, b = _xyz(module.camera_at(0)), _xyz(module.camera_at(.25))
            assert a != b
        _probe(checks, "moving_3d_camera", camera)
    if turn >= 7:
        def stars() -> None:
            scene = module.scene_at(.3)
            near, far = scene["stars_near"], scene["stars_far"]
            assert len(near) >= 2 and len(far) >= 2
            assert all(len(_xyz(point)) == 3 for point in near[:2] + far[:2])
        _probe(checks, "near_far_3d_stars", stars)
    if turn >= 8:
        def seamless() -> None:
            start, end = module.scene_at(0), module.scene_at(1)
            for name in ("planet", "satellite", "moon"):
                assert math.dist(_xyz(start[name]), _xyz(end[name])) < 1e-4
            assert math.dist(_xyz(module.camera_at(0)), _xyz(module.camera_at(1))) < 1e-4
        _probe(checks, "seamless_3d_loop", seamless)
    if turn >= 9:
        _probe(checks, "animation_title", lambda: _assert(module.TITLE == "Orbital Courier"))
    if turn >= 10:
        def presentation_export() -> None:
            target = root / ".quality-animation-large.gif"
            module.render_gif(target, frames=12, size=(640, 480))
            with Image.open(target) as result:
                assert result.size == (640, 480) and result.n_frames >= 11
                assert result.info.get("loop") == 0
        _probe(checks, "presentation_gif_export", presentation_export)
    return _report(turn, checks, "animation")


def _assert(condition: bool) -> None:
    if not condition:
        raise AssertionError


def _report(turn: int, checks: dict[str, bool], domain: str) -> dict[str, Any]:
    return {"domain": domain, "turn": turn, "passed": all(checks.values()),
            "checks": checks, "errors": [key for key, value in checks.items() if not value],
            "scope": "deterministic runtime contract; no human style or visual quality score"}


EVALUATORS = {"programming": evaluate_programming, "animation": evaluate_animation}
