import shutil
from pathlib import Path

from scripts.design_benchmark_quality import evaluate


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "benchmark-fixtures" / "cross-domain"


def test_each_design_track_starts_failing(tmp_path):
    for domain in ("ui-ux", "graphic-design", "three-d-design"):
        root = tmp_path / domain
        shutil.copytree(FIXTURES / domain, root)
        assert evaluate(root, domain, 1)["passed"] is False


def test_later_round_requires_prior_contract(tmp_path):
    root = tmp_path / "ui"
    shutil.copytree(FIXTURES / "ui-ux", root)
    result = evaluate(root, "ui-ux", 3)
    assert result["passed"] is False
    assert "base_contract" in result["checks"]
    assert "accessible_dialog" in result["checks"]
