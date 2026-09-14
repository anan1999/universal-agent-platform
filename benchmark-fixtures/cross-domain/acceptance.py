"""Deterministic, model-independent acceptance for cross-domain benchmark fixtures."""
from __future__ import annotations

import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


def load(root: Path) -> tuple[dict, list[str]]:
    try:
        return json.loads((root / "deliverable.json").read_text(encoding="utf-8")), []
    except (OSError, ValueError) as error:
        return {}, [f"deliverable: {type(error).__name__}"]


def product(root: Path, value: dict) -> list[str]:
    errors = []
    if value.get("selected_problem") != "P2": errors.append("selected_problem")
    if value.get("roadmap") != ["F2", "F3"]: errors.append("roadmap")
    if value.get("success_metric") != "weekly_task_completion_rate": errors.append("success_metric")
    if len(value.get("risks", [])) < 2 or not all(value.get("risks", [])): errors.append("risks")
    return errors


def research(root: Path, value: dict) -> list[str]:
    errors = []
    if value.get("recommendation") != "Intervention B": errors.append("recommendation")
    citations = set(value.get("citations", []))
    if not {"S2", "S3"}.issubset(citations) or not citations.issubset({"S1", "S2", "S3", "S4"}):
        errors.append("citations")
    if "14" not in str(value.get("benefit_claim", "")): errors.append("benefit_claim")
    if "3" not in str(value.get("risk_claim", "")): errors.append("risk_claim")
    if value.get("next_trial", {}).get("minimum_sample_size") != 500: errors.append("next_trial")
    return errors


def brand(root: Path, value: dict) -> list[str]:
    brief = json.loads((root / "brand-brief.json").read_text(encoding="utf-8"))
    errors = []
    if value.get("archetype") != "Guide": errors.append("archetype")
    palette = value.get("palette", {})
    if not palette or set(palette.values()) - set(brief["approved_palette"].values()): errors.append("palette")
    if len(set(value.get("voice_traits", []))) != 3: errors.append("voice_traits")
    if set(value.get("channels", [])) != set(brief["required_channels"]): errors.append("channels")
    if set(value.get("avoid", [])) != set(brief["avoid"]): errors.append("avoid")
    rationale = str(value.get("rationale", "")).lower()
    if "caregiver" not in rationale or "calm" not in rationale: errors.append("rationale")
    return errors


def lighting(root: Path, value: dict) -> list[str]:
    source = json.loads((root / "rooms.json").read_text(encoding="utf-8"))
    expected = {}
    for room in source["rooms"]:
        count = math.ceil(room["area_m2"] * room["target_lux"] / source["fixture_lumens"])
        expected[room["id"]] = (count, count * source["fixture_watts"])
    actual = {item.get("id"): (item.get("fixture_count"), item.get("watts"))
              for item in value.get("rooms", [])}
    total = sum(watts for _, watts in expected.values())
    errors = []
    if actual != expected: errors.append("rooms")
    if value.get("total_watts") != total: errors.append("total_watts")
    if value.get("minimum_circuits") != math.ceil(total / source["max_watts_per_circuit"]):
        errors.append("minimum_circuits")
    if len(value.get("design_notes", [])) < 2: errors.append("design_notes")
    return errors


class PrototypeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {key: value or "" for key, value in attrs}))

    def handle_data(self, data: str) -> None:
        self.text += data


def ui_ux(root: Path, _value: dict) -> list[str]:
    requirements = json.loads((root / "requirements.json").read_text(encoding="utf-8"))
    try:
        source = (root / "prototype.html").read_text(encoding="utf-8")
    except OSError:
        return ["prototype.html"]
    parser = PrototypeParser()
    parser.feed(source)
    tags = [tag for tag, _ in parser.tags]
    ids = {attrs.get("id") for _, attrs in parser.tags}
    errors = []
    if "nav" not in tags or "main" not in tags: errors.append("semantic_structure")
    nav_labels = {attrs.get("aria-label") for tag, attrs in parser.tags if tag == "nav"}
    if requirements["navigation_label"] not in nav_labels: errors.append("navigation_label")
    if not set(requirements["required_sections"]).issubset(ids): errors.append("sections")
    if requirements["primary_action"] not in parser.text: errors.append("primary_action")
    if not all(color.lower() in source.lower() for color in requirements["tokens"].values()):
        errors.append("tokens")
    if not re.search(rf"@media[^{{]*\(max-width:\s*{requirements['breakpoint_px']}px\)", source, re.I):
        errors.append("breakpoint")
    if ":focus" not in source: errors.append("focus_style")
    return errors


def graphic(root: Path, _value: dict) -> list[str]:
    brief = json.loads((root / "poster-brief.json").read_text(encoding="utf-8"))
    try:
        source = (root / "poster.svg").read_text(encoding="utf-8")
        tree = ET.fromstring(source)
    except (OSError, ET.ParseError):
        return ["poster.svg"]
    errors = []
    if tree.attrib.get("viewBox") != brief["view_box"]: errors.append("viewBox")
    ids = {node.attrib.get("id") for node in tree.iter()}
    if not set(brief["required_layers"]).issubset(ids): errors.append("layers")
    local_names = [node.tag.rsplit("}", 1)[-1] for node in tree.iter()]
    if "title" not in local_names or "desc" not in local_names: errors.append("accessibility")
    visible_copy = "".join("".join(node.itertext()) for node in tree.iter()
                           if node.tag.rsplit("}", 1)[-1] in {"title", "text"})
    normalized_copy = re.sub(r"\s+", "", visible_copy).casefold()
    if not all(re.sub(r"\s+", "", str(brief[key])).casefold() in normalized_copy
               for key in ("event", "date", "venue")):
        errors.append("copy")
    colors = {match.upper() for match in re.findall(r"#[0-9a-fA-F]{6}", source)}
    if colors - {item.upper() for item in brief["palette"]}: errors.append("palette")
    def text_size(node) -> float:
        match = re.search(r"font-size\s*:\s*([0-9.]+)|^([0-9.]+)$", node.attrib.get("font-size", ""))
        style = re.search(r"font-size\s*:\s*([0-9.]+)", node.attrib.get("style", ""))
        return float((match.group(1) or match.group(2)) if match else style.group(1)) if match or style else 0

    event_words = set(re.findall(r"\w+", brief["event"].casefold()))
    covered_words, event_sizes, metadata_sizes = set(), [], []
    expected_metadata = {
        re.sub(r"\s+", "", str(brief[key])).casefold() for key in ("date", "venue")}
    for node in tree.iter():
        if node.tag.rsplit("}", 1)[-1] != "text":
            continue
        node_text = "".join(node.itertext()).strip()
        node_words = set(re.findall(r"\w+", node_text.casefold()))
        compact = re.sub(r"\s+", "", node_text).casefold()
        if node_words and node_words.issubset(event_words):
            covered_words.update(node_words)
            event_sizes.append(text_size(node))
        if compact in expected_metadata:
            metadata_sizes.append(text_size(node))
    if (covered_words != event_words or not event_sizes or not metadata_sizes
            or min(event_sizes) <= max(metadata_sizes)):
        errors.append("hierarchy")
    if re.search(r"<(?:image|script)\b|(?:href|src)\s*=\s*[\"']https?://", source, re.I):
        errors.append("external_resource")
    return errors


def three_d(root: Path, _value: dict) -> list[str]:
    brief = json.loads((root / "model-brief.json").read_text(encoding="utf-8"))
    try:
        lines = (root / "kiosk.obj").read_text(encoding="utf-8").splitlines()
        material_source = (root / "kiosk.mtl").read_text(encoding="utf-8")
    except OSError:
        return ["3d_files"]
    vertices, faces, groups, materials = [], [], set(), set()
    has_mtllib = False
    for line in lines:
        parts = line.split()
        if not parts: continue
        if parts[0] == "v" and len(parts) >= 4:
            try: vertices.append(tuple(float(item) for item in parts[1:4]))
            except ValueError: pass
        elif parts[0] == "f": faces.append(parts[1:])
        elif parts[0] in {"g", "o"} and len(parts) > 1: groups.add(parts[1])
        elif parts[0] == "usemtl" and len(parts) > 1: materials.add(parts[1])
        elif parts[0] == "mtllib" and "kiosk.mtl" in parts[1:]: has_mtllib = True
    errors = []
    if len(vertices) < brief["minimum_vertices"]: errors.append("vertices")
    if len(faces) < brief["minimum_faces"]: errors.append("faces")
    if not set(brief["required_groups"]).issubset(groups): errors.append("groups")
    if not set(brief["materials"]).issubset(materials): errors.append("material_usage")
    if not has_mtllib or not all(f"newmtl {name}" in material_source for name in brief["materials"]):
        errors.append("materials")
    if vertices:
        actual = {axis: [min(row[index] for row in vertices), max(row[index] for row in vertices)]
                  for index, axis in enumerate(("x", "y", "z"))}
        if actual != brief["bounds"]: errors.append("bounds")
    for face in faces:
        try:
            indices = [int(item.split("/")[0]) for item in face]
        except ValueError:
            errors.append("face_indices")
            break
        if len(indices) < 3 or any(index == 0 or abs(index) > len(vertices) for index in indices):
            errors.append("face_indices")
            break
    return errors


VALIDATORS = {
    "product-strategy": product,
    "research-synthesis": research,
    "brand-direction": brand,
    "interior-lighting": lighting,
    "ui-ux": ui_ux,
    "graphic-design": graphic,
    "three-d-design": three_d,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--domain", choices=tuple(VALIDATORS), required=True)
    args = parser.parse_args()
    artifact_domains = {"ui-ux", "graphic-design", "three-d-design"}
    value, errors = ({}, []) if args.domain in artifact_domains else load(args.project)
    if not errors:
        errors = VALIDATORS[args.domain](args.project, value)
    payload = {"passed": not errors, "domain": args.domain, "errors": errors,
               "contract": "cross-domain-deliverable-v3"}
    print(json.dumps(payload))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
