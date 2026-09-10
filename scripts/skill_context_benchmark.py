"""Deterministic, quota-free benchmark for progressive Skill loading."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from adaptive_agent.skills.manifest import SkillTrust
from adaptive_agent.skills.registry import SkillRegistry


def create_fixture(root: Path) -> Path:
    package = root / "responsive-dashboard"
    (package / "references").mkdir(parents=True)
    (package / "examples").mkdir()
    (package / "SKILL.md").write_text(
        "# Responsive dashboard\n\nUse a bounded layout and accessibility procedure.\n",
        encoding="utf-8",
    )
    references = {}
    for index in range(5):
        relative = f"references/ref-{index}.md"
        references[f"ref-{index}"] = relative
        (package / relative).write_text((f"reference-{index} guidance " * 120) + "\n", encoding="utf-8")
    for index in range(3):
        (package / "examples" / f"example-{index}.md").write_text(
            (f"example-{index} evidence " * 120) + "\n", encoding="utf-8")
    manifest = {
        "id": "responsive-dashboard", "version": "1.0.0",
        "description": "Responsive UI procedure",
        "capabilities": ["responsive_layout", "accessibility"],
        "references": references, "trust": "project_local", "status": "active",
    }
    (package / "skill.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return package


def measure(root: Path) -> dict[str, int | float]:
    package = create_fixture(root)
    registry = SkillRegistry()
    registry.discover_directory(root, SkillTrust.PROJECT_LOCAL)
    manifest = registry.manifest("responsive-dashboard")
    loaded = registry.load_selected(manifest.id, ["ref-2"])
    eager_chars = len(json.dumps(manifest.to_dict(include_path=False))) + sum(
        len(path.read_text(encoding="utf-8")) for path in package.rglob("*.md")
    )
    progressive_chars = len(json.dumps(manifest.to_dict(include_path=False))) + loaded.context_chars
    saved = eager_chars - progressive_chars
    return {
        "eager_chars": eager_chars,
        "progressive_chars": progressive_chars,
        "saved_chars": saved,
        "reduction_percent": round(saved / eager_chars * 100, 2),
        "eager_estimated_tokens": (eager_chars + 3) // 4,
        "progressive_estimated_tokens": (progressive_chars + 3) // 4,
        "ai_invocations": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="uap-skill-benchmark-") as temporary:
        result = measure(Path(temporary))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
