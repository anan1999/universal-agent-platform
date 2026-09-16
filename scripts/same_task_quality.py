"""Independent, cumulative contract checks for a coherent 10-turn UI/UX task.

Static acceptance catches missing features and syntax regressions, not visual
quality or real-browser accessibility. Prompts never reveal checker patterns.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    from scripts.design_benchmark_quality import evaluate as design_evaluate
except ModuleNotFoundError:
    from design_benchmark_quality import evaluate as design_evaluate


GOALS = [
    "Create the responsive and accessible medication-planner prototype described by the local brief and requirements.",
    "The daily schedule is useful. Please add a medication status filter, a visible schedule-conflict alert, and a screen-reader status announcement. Keep the same layout and colors.",
    "I also need to add a medication without leaving the page. Make that a labelled, keyboard-accessible dialog; Escape should close it and focus should return to the Add medication button. Respect reduced-motion settings.",
    "When I submit the Add medication form with missing details, show a clear inline error, mark the invalid field for assistive technology, and keep my entered data so I can correct it.",
    "If I accidentally enter the same medication at the same time twice, warn me before adding a duplicate. Explain the problem in the dialog instead of silently ignoring it.",
    "The medication list is getting longer. Add a labelled search field that filters medications by name as I type, without changing the daily schedule or the status filter.",
    "When search has no matches, show a useful empty result message; when I clear search, bring the medications back. Announce the changed result count to a screen reader.",
    "I'd like my changes to survive a page refresh on this device. Save the medication list and taken status locally, restore them safely, and explain that this prototype stores data on this device only.",
    "I sometimes bring a paper list to appointments. Add a print-friendly view of the medication schedule that hides navigation, forms, dialogs, and buttons while keeping the important names, doses, and times readable.",
    "One last polish: make the safety note clear that this prototype does not check drug interactions and that schedule changes should be confirmed with a care professional. Keep keyboard focus visible and the earlier filters, search, dialog, and saved state working.",
]


def _has(source: str, pattern: str) -> bool:
    return re.search(pattern, source, re.I | re.S) is not None


def _scripts(source: str) -> str:
    return "\n".join(re.findall(r"<script(?:\s[^>]*)?>(.*?)</script\s*>", source,
                                re.I | re.S))


def evaluate(root: Path, turn: int) -> dict[str, Any]:
    """Recheck all prior milestones on every turn, including JS syntax."""
    if turn < 1 or turn > len(GOALS):
        raise ValueError("turn must be within the scripted dialogue")
    base = design_evaluate(root, "ui-ux", min(turn, 3))
    source = (root / "prototype.html").read_text(encoding="utf-8", errors="replace") \
        if (root / "prototype.html").is_file() else ""
    checks: dict[str, bool] = {name: True for name in base["checks"]}
    checks.update({"base:" + error: False for error in base["errors"]})
    if turn >= 4:
        checks["form_validation_feedback"] = (
            _has(source, r"aria-invalid|setCustomValidity|reportValidity")
            and _has(source, r"(?:error|invalid)[^<]{0,120}|role\s*=\s*['\"]alert")
            and _has(source, r"(?:form|input|field)[\s\S]{0,200}focus|\.focus\s*\("))
    if turn >= 5:
        checks["duplicate_warning"] = (_has(source, r"duplicat|already exists|already added")
                                       and _has(source, r"(?:med-name|\.name|name\.value)")
                                       and _has(source, r"(?:med-time|\.time|time\.value)"))
    if turn >= 6:
        checks["labelled_live_search"] = (
            _has(source, r"<label\b[^>]*>[^<]*search|aria-label\s*=\s*['\"][^'\"]*search")
            and _has(source, r"<input\b[^>]*(?:type\s*=\s*['\"]search|id\s*=\s*['\"][^'\"]*search)")
            and _has(source, r"(?:addEventListener\s*\(\s*['\"]input|oninput\s*=)"))
    if turn >= 7:
        checks["search_empty_and_restore"] = (_has(source, r"no (?:matching|medications|results)|nothing (?:found|matches)")
                                               and _has(source, r"(?:\.hidden|display\s*=|classList\.toggle)")
                                               and _has(source, r"aria-live\s*=|role\s*=\s*['\"]status"))
    if turn >= 8:
        checks["local_persistence_and_disclosure"] = (
            _has(source, r"localStorage\.getItem") and _has(source, r"localStorage\.setItem")
            and _has(source, r"\btry\s*\{") and _has(source, r"\bcatch\s*(?:\(|\{)")
            and _has(source, r"(?:this|your) device|stored locally"))
    if turn >= 9:
        print_rules = re.search(r"@media\s+print\s*\{([\s\S]*?)\}", source, re.I)
        checks["print_view"] = (bool(print_rules)
                                and _has(source, r"(?:nav|sidebar)[^{}]*\{[^{}]*display\s*:\s*none")
                                and _has(source, r"(?:button|dialog|form)[^{}]*\{[^{}]*display\s*:\s*none"))
    if turn >= 10:
        checks["medical_safety_and_focus"] = (
            _has(source, r"(?:does not|not|cannot)[^<.]{0,80}(?:check|detect)[^<.]{0,50}interaction")
            and _has(source, r"(?:confirm|consult)[^<.]{0,80}(?:care|professional|clinician|doctor)")
            and _has(source, r":focus-visible|:focus\s*\{"))
    scripts = _scripts(source)
    if scripts and shutil.which("node"):
        try:
            result = subprocess.run(["node", "--check", "-"], input=scripts,
                                    text=True, encoding="utf-8", capture_output=True,
                                    timeout=10, check=False)
            checks["inline_javascript_syntax"] = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            checks["inline_javascript_syntax"] = False
    else:
        checks["inline_javascript_syntax"] = False
    return {"passed": all(checks.values()), "turn": turn, "checks": checks,
            "errors": [name for name, passed in checks.items() if not passed],
            "scope": "deterministic cumulative contract + inline JS syntax; no browser or human visual review"}
