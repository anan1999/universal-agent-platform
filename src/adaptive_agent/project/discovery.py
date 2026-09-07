"""Project discovery.

Detects *signals*, not a single project "type". A repository can be a Python
service, an ML pipeline, and a documentation site at once; the profile registry
turns the signals into profile recommendations, so adding a new domain means
editing a profile YAML rather than this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


#: Marker -> (language, build command, test command). Purely advisory.
LANGUAGE_MARKERS: tuple[tuple[str, str, str | None, str | None], ...] = (
    ("pyproject.toml", "python", None, "pytest"),
    ("requirements.txt", "python", None, "pytest"),
    ("setup.py", "python", None, "pytest"),
    ("package.json", "javascript", "npm run build", "npm test"),
    ("tsconfig.json", "typescript", "npm run build", "npm test"),
    ("go.mod", "go", "go build ./...", "go test ./..."),
    ("Cargo.toml", "rust", "cargo build", "cargo test"),
    ("pom.xml", "java", "mvn package", "mvn test"),
    ("CMakeLists.txt", "cpp", "cmake --build build", None),
    ("Gemfile", "ruby", None, "bundle exec rspec"),
)

#: Markers that describe the *kind* of work rather than the language.
CONTEXT_MARKERS: tuple[str, ...] = (
    "settings.gradle", "settings.gradle.kts", "gradlew", "gradlew.bat", "build.gradle",
    "build.gradle.kts", "AndroidManifest.xml", "Dockerfile", "docker-compose.yml",
    ".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", "main.tf", "terraform.tf",
    "kubernetes", "helm", "ansible.cfg", ".circleci", "dvc.yaml", "params.yaml",
    "environment.yml", "mkdocs.yml", "docusaurus.config.js", "docs", "README.md",
    "CONTRIBUTING.md", "ROADMAP.md", "PRD.md", "references.bib", "dbt_project.yml",
    ".storybook", "design-tokens.json", "figma.json", "brand.json", ".git",
)

#: Extensions worth reporting when they appear anywhere in the tree.
CONTENT_MARKERS: tuple[tuple[str, str], ...] = (
    ("*.ipynb", "*.ipynb"), ("*.csv", "*.csv"), ("*.parquet", "*.parquet"),
    ("*.onnx", "model.onnx"), ("*.kt", "kotlin"), ("*.java", "java"), ("*.cpp", "cpp"),
)


@dataclass(slots=True)
class ProjectInfo:
    name: str
    type: str
    languages: list[str]
    build_command: str | None
    test_command: str | None
    #: Every file marker found. Fed straight into profile suggestion.
    signals: list[str] = field(default_factory=list)
    #: Profile ids recommended by the profile registry, best first.
    recommended_profiles: list[str] = field(default_factory=list)
    #: Why each profile was recommended.
    evidence: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "languages": list(self.languages),
                "build_command": self.build_command, "test_command": self.test_command,
                "signals": list(self.signals), "recommended_profiles": list(self.recommended_profiles),
                "evidence": {key: list(value) for key, value in self.evidence.items()}}


def signals(path: Path) -> list[str]:
    """File markers present in the project, without walking the whole tree twice."""
    path = Path(path).resolve()
    found = [marker for marker, *_ in LANGUAGE_MARKERS if (path / marker).exists()]
    found += [marker for marker in CONTEXT_MARKERS if (path / marker).exists()]
    for pattern, label in CONTENT_MARKERS:
        if next(path.rglob(pattern), None) is not None:
            found.append(label)
    return sorted(set(found))


def discover(path: Path, profiles: Any | None = None) -> ProjectInfo:
    """Inspect a project. Never writes anything and never fails on an unknown layout."""
    path = Path(path).resolve()
    try:
        found = signals(path)
    except OSError:  # pragma: no cover - unreadable tree
        found = []

    languages, build, test = _language(path, found)
    kind = _kind(found, languages)

    recommended: list[str] = []
    evidence: dict[str, list[str]] = {}
    registry = profiles
    if registry is None:
        from adaptive_agent.profiles.registry import profile_registry

        registry = profile_registry()
    for profile_id, why in registry.suggest(found):
        recommended.append(profile_id)
        evidence[profile_id] = why
    if not recommended:
        recommended = [registry.fallback().id]
        evidence[recommended[0]] = ["no domain markers found; general profile applies"]

    return ProjectInfo(path.name, kind, languages, build, test, found, recommended, evidence)


def _language(path: Path, found: list[str]) -> tuple[list[str], str | None, str | None]:
    if any(marker in found for marker in ("settings.gradle", "settings.gradle.kts", "gradlew", "gradlew.bat")):
        languages = [item for item in ("kotlin", "java", "cpp") if item in found]
        wrapper = ".\\gradlew.bat" if (path / "gradlew.bat").exists() else "./gradlew"
        return languages or ["unknown"], f"{wrapper} assembleDebug", f"{wrapper} test"
    languages, build, test = [], None, None
    for marker, language, build_command, test_command in LANGUAGE_MARKERS:
        if marker in found:
            if language not in languages:
                languages.append(language)
            build = build or build_command
            test = test or test_command
    return languages or ["unknown"], build, test


def _kind(found: list[str], languages: list[str]) -> str:
    """A coarse project label used for display and discovery evidence."""
    if "AndroidManifest.xml" in found or "settings.gradle" in found or "gradlew" in found:
        return "android"
    return languages[0] if languages and languages[0] != "unknown" else "unknown"
