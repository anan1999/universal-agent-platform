"""Deterministic cumulative acceptance for the three design benchmark tracks."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_ACCEPTANCE = ROOT / "benchmark-fixtures" / "cross-domain" / "acceptance.py"


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("cross_domain_acceptance", BASE_ACCEPTANCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cross-domain acceptance could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _svg_checks(path: Path, *, view_box: str, copy: tuple[str, ...]) -> list[str]:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return [path.name]
    errors: list[str] = []
    if root.attrib.get("viewBox") != view_box:
        errors.append(f"{path.name}:viewBox")
    names = [node.tag.rsplit("}", 1)[-1] for node in root.iter()]
    if "title" not in names or "desc" not in names:
        errors.append(f"{path.name}:accessibility")
    text = re.sub(r"\s+", "", "".join("".join(node.itertext()) for node in root.iter())).casefold()
    if not all(re.sub(r"\s+", "", value).casefold() in text for value in copy):
        errors.append(f"{path.name}:copy")
    if re.search(r"<(?:image|script)\b|(?:href|src)\s*=\s*[\"']https?://",
                 path.read_text(encoding="utf-8"), re.I):
        errors.append(f"{path.name}:external_resource")
    return errors


def _obj_summary(root: Path) -> dict[str, Any]:
    lines = (root / "kiosk.obj").read_text(encoding="utf-8").splitlines()
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    groups: set[str] = set()
    materials: set[str] = set()
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            vertices.append(tuple(float(item) for item in parts[1:4]))
        elif parts[0] == "f":
            faces.append([int(item.split("/")[0]) for item in parts[1:]])
        elif parts[0] in {"g", "o"} and len(parts) > 1:
            groups.add(parts[1])
        elif parts[0] == "usemtl" and len(parts) > 1:
            materials.add(parts[1])
    return {"vertices": vertices, "faces": faces, "groups": groups, "materials": materials}


def evaluate(root: Path, domain: str, round_number: int) -> dict[str, Any]:
    if round_number not in {1, 2, 3}:
        raise ValueError("round_number must be 1, 2, or 3")
    errors = list(BASE.VALIDATORS[domain](root, {}))
    checks = ["base_contract"]
    if domain == "ui-ux":
        source = (root / "prototype.html").read_text(encoding="utf-8", errors="replace") if (root / "prototype.html").exists() else ""
        if round_number >= 2:
            checks.append("status_and_conflict_feedback")
            if not re.search(r"<(?:select|button)[^>]*(?:filter|status)|data-filter|id=[\"'][^\"']*filter", source, re.I):
                errors.append("status_filter")
            if not re.search(r"conflict", source, re.I):
                errors.append("conflict_alert")
            if not re.search(r"aria-live\s*=|role\s*=\s*[\"']status", source, re.I):
                errors.append("live_status")
        if round_number >= 3:
            checks.append("accessible_dialog")
            probes = {
                "dialog": r"role\s*=\s*[\"']dialog|<dialog\b",
                "modal": r"aria-modal\s*=\s*[\"']true|<dialog\b",
                "labels": r"<label\b",
                "escape": r"Escape|keyCode\s*===?\s*27|addEventListener\s*\(\s*[\"']cancel",
                "focus_return": r"\.focus\s*\(",
                "reduced_motion": r"prefers-reduced-motion",
            }
            errors.extend(name for name, pattern in probes.items() if not re.search(pattern, source, re.I))
    elif domain == "graphic-design":
        brief = json.loads((root / "poster-brief.json").read_text(encoding="utf-8"))
        poster = (root / "poster.svg").read_text(encoding="utf-8", errors="replace") if (root / "poster.svg").exists() else ""
        if round_number >= 2:
            checks.append("sponsor_extension")
            if "sponsor-strip" not in poster:
                errors.append("sponsor_layer")
            if "SUPPORTED BY HARBOR LAB" not in poster:
                errors.append("sponsor_copy")
        if round_number >= 3:
            checks.append("social_adaptation")
            errors.extend(_svg_checks(root / "social.svg", view_box="0 0 1080 1080",
                                      copy=(brief["event"], brief["date"], brief["venue"])))
            social = (root / "social.svg").read_text(encoding="utf-8", errors="replace") if (root / "social.svg").exists() else ""
            colors = {item.upper() for item in re.findall(r"#[0-9a-fA-F]{6}", social)}
            if colors - {item.upper() for item in brief["palette"]}:
                errors.append("social.svg:palette")
    else:
        try:
            model = _obj_summary(root)
            material_source = (root / "kiosk.mtl").read_text(encoding="utf-8")
        except (OSError, ValueError):
            model, material_source = {"vertices": [], "faces": [], "groups": set(), "materials": set()}, ""
        if round_number >= 2:
            checks.append("keypad_extension")
            if "keypad" not in model["groups"]:
                errors.append("keypad_group")
            if "AccentMetal" not in model["materials"] or "newmtl AccentMetal" not in material_source:
                errors.append("accent_material")
            if len(model["vertices"]) < 20 or len(model["faces"]) < 14:
                errors.append("keypad_geometry")
        if round_number >= 3:
            checks.append("canopy_extension")
            if "canopy" not in model["groups"]:
                errors.append("canopy_group")
            if "Canopy" not in model["materials"] or "newmtl Canopy" not in material_source:
                errors.append("canopy_material")
            if len(model["vertices"]) < 28 or len(model["faces"]) < 20:
                errors.append("canopy_geometry")
    return {"passed": not errors, "domain": domain, "round": round_number,
            "checks": checks, "errors": sorted(set(errors)),
            "contract": "design-longitudinal-v1"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--domain", choices=("ui-ux", "graphic-design", "three-d-design"), required=True)
    parser.add_argument("--round", type=int, choices=(1, 2, 3), required=True)
    args = parser.parse_args()
    result = evaluate(args.project, args.domain, args.round)
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
