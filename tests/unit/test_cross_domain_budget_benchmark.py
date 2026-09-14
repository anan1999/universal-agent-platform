import importlib.util
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "cross_domain_budget_benchmark", ROOT / "scripts/cross_domain_budget_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def result(tokens=1000, cached=200, tools=4, passed=True):
    return {
        "usage": {"input": tokens - 100, "output": 100, "cached": cached, "source": "measured"},
        "quality": {"passed": passed}, "duration_seconds": 10,
        "telemetry": {"tool_calls": tools, "assistant_messages": 3},
    }


def cases():
    return [
        {"domain": domain, "order": list(benchmark.ARMS), "results": {
            "fixed_8": result(), "candidate_6": result(tokens=800, cached=150, tools=3),
        }}
        for domain in ("ui-ux", "three-d-design", "graphic-design")
    ]


def test_summary_reports_pooled_and_per_domain_results():
    summary = benchmark.summarize(cases())
    assert summary["domains"] == 3
    assert summary["quality"] == {"fixed_8": 3, "candidate_6": 3}
    assert summary["total_token_reduction_percent"] == 20.0
    assert summary["tool_reduction_percent"] == 25.0
    assert summary["domain_wins"]["tokens"] == 3
    assert benchmark.decision(summary) == "CROSS_DOMAIN_CANDIDATE"


def test_quality_regression_rejects_candidate():
    values = cases()
    values[1]["results"]["candidate_6"]["quality"]["passed"] = False
    assert benchmark.decision(benchmark.summarize(values)) == "REJECT_QUALITY"


def test_reset_creates_fresh_project_without_agent_state(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = workspace / "ui"
    digest = benchmark.reset(root, "ui-ux", workspace)
    assert digest
    assert (root / ".git").is_dir()
    assert not (root / ".agent").exists()
    assert not (root / "deliverable.json").exists()


def test_design_acceptance_validates_real_artifact_formats(tmp_path):
    ui = tmp_path / "ui"
    shutil.copytree(benchmark.FIXTURES / "ui-ux", ui)
    ui.joinpath("prototype.html").write_text(
        """<style>:root{--p:#17324D;--a:#2A9D8F;--s:#F7F3EC}button:focus{outline:2px solid}@media (max-width: 640px){main{display:block}}</style>
        <nav aria-label="Care plan navigation"></nav><main><section id="today"></section><section id="medications"></section><section id="care-team"></section><button>Add medication</button></main>""",
        encoding="utf-8")
    assert benchmark.acceptance(ui, "ui-ux")["passed"]

    graphic = tmp_path / "graphic"
    shutil.copytree(benchmark.FIXTURES / "graphic-design", graphic)
    graphic.joinpath("poster.svg").write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350"><title>Night Harbor Design Week</title><desc>Event poster</desc><g id="background"><rect width="1080" height="1350" fill="#102A43"/></g><g id="hero"><circle cx="10" cy="10" r="5" fill="#2A9D8F"/></g><g id="information"><text font-size="80" fill="#F4EBD0">NIGHT HARBOR</text><text font-size="80" fill="#F4EBD0">DESIGN WEEK</text><text font-size="30" fill="#2A9D8F">18 OCT 2026</text><text font-size="30" fill="#F4EBD0">PIER 7</text></g></svg>""",
        encoding="utf-8")
    assert benchmark.acceptance(graphic, "graphic-design")["passed"]

    model = tmp_path / "model"
    shutil.copytree(benchmark.FIXTURES / "three-d-design", model)
    model.joinpath("kiosk.obj").write_text(
        """mtllib kiosk.mtl
o base
usemtl KioskBody
v -1 0 -0.5
v 1 0 -0.5
v 1 0 0.5
v -1 0 0.5
v -0.8 0.2 -0.4
v 0.8 0.2 -0.4
v 0.8 0.2 0.4
v -0.8 0.2 0.4
g body
v -0.6 3 -0.3
v 0.6 3 -0.3
v 0.6 3 0.3
v -0.6 3 0.3
f 1 2 3 4
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
g screen
usemtl ScreenGlass
f 9 10 11 12
f 5 6 10 9
""", encoding="utf-8")
    model.joinpath("kiosk.mtl").write_text(
        "newmtl KioskBody\nKd 0.2 0.2 0.2\nnewmtl ScreenGlass\nKd 0.1 0.5 0.6\n",
        encoding="utf-8")
    assert benchmark.acceptance(model, "three-d-design")["passed"]


def test_non_design_acceptance_uses_external_contract(tmp_path):
    root = tmp_path / "product"
    shutil.copytree(benchmark.FIXTURES / "product-strategy", root)
    root.joinpath("deliverable.json").write_text(json.dumps({
        "selected_problem": "P2", "roadmap": ["F2", "F3"],
        "success_metric": "weekly_task_completion_rate", "risks": ["adoption", "scope"],
    }), encoding="utf-8")
    assert benchmark.acceptance(root, "product-strategy")["passed"]
