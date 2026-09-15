"""Provider-independent quality scoring for paired implementation benchmarks."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def assess_implementation_quality(
        checks: Sequence[Mapping[str, Any]], changed_paths: Sequence[str],
        *, required_checks: Sequence[str], expected_prefixes: Sequence[str],
        require_test_change: bool = False) -> dict[str, Any]:
    """Score externally observed quality without reading a provider's self-report.

    The rubric deliberately uses only deterministic acceptance results and the
    source delta. It is suitable for comparing providers because token usage,
    prose summaries, and model confidence never affect the score.
    """
    observed = {str(item.get("name")): bool(item.get("passed")) for item in checks}
    required = list(dict.fromkeys(str(name) for name in required_checks))
    required_passes = sum(observed.get(name, False) for name in required)
    functional_ratio = required_passes / len(required) if required else 1.0
    regression_passed = observed.get("pytest", False)

    normalized_paths = sorted({str(path).replace("\\", "/").lstrip("./")
                               for path in changed_paths if str(path).strip()})
    prefixes = tuple(str(prefix).replace("\\", "/").lstrip("./")
                     for prefix in expected_prefixes)
    focused = [path for path in normalized_paths
               if any(path == prefix.rstrip("/") or path.startswith(prefix)
                      for prefix in prefixes)]
    focus_ratio = len(focused) / len(normalized_paths) if normalized_paths else 0.0
    test_paths = [path for path in normalized_paths
                  if path.startswith("tests/") or "/tests/" in path
                  or ".test." in path.lower() or ".spec." in path.lower()]
    test_evidence_passed = bool(test_paths) if require_test_change else regression_passed
    implementation_present = bool(normalized_paths)

    dimensions = {
        "functional_contract": {"weight": 50, "score": round(50 * functional_ratio, 2),
                                "passed": functional_ratio == 1.0,
                                "evidence": f"{required_passes}/{len(required)} required checks passed"},
        "regression_safety": {"weight": 20, "score": 20 if regression_passed else 0,
                              "passed": regression_passed,
                              "evidence": "project test command passed" if regression_passed
                              else "project test command failed"},
        "test_evidence": {"weight": 15, "score": 15 if test_evidence_passed else 0,
                          "passed": test_evidence_passed,
                          "evidence": (f"{len(test_paths)} changed test file(s)" if require_test_change
                                       else "new test file not required; regression suite passed")},
        "change_focus": {"weight": 10, "score": round(10 * focus_ratio, 2),
                         "passed": focus_ratio >= 0.8,
                         "evidence": f"{len(focused)}/{len(normalized_paths)} changed paths in expected scope"},
        "implementation_evidence": {"weight": 5, "score": 5 if implementation_present else 0,
                                    "passed": implementation_present,
                                    "evidence": f"{len(normalized_paths)} source path(s) changed"},
    }
    score = round(sum(float(item["score"]) for item in dimensions.values()), 2)
    passed = bool(
        dimensions["functional_contract"]["passed"]
        and dimensions["regression_safety"]["passed"]
        and dimensions["test_evidence"]["passed"]
        and dimensions["implementation_evidence"]["passed"]
        and score >= 85)
    return {
        "method": "deterministic_external_quality_v1",
        "provider_self_report_used": False,
        "score": score,
        "passed": passed,
        "dimensions": dimensions,
        "changed_paths": normalized_paths,
        "unexpected_paths": sorted(set(normalized_paths) - set(focused)),
    }
