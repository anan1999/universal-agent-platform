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


def test_native_dialog_semantics_and_cancel_event_satisfy_modal_contract(tmp_path):
    root = tmp_path / "ui-native-dialog"
    shutil.copytree(FIXTURES / "ui-ux", root)
    root.joinpath("prototype.html").write_text("""
    <style>
      :root { --primary:#17324D; --accent:#2A9D8F; --surface:#F7F3EC; }
      :focus-visible { outline: 2px solid; }
      @media (max-width: 640px) {}
      @media (prefers-reduced-motion: reduce) {}
    </style>
    <nav aria-label="Care plan navigation"></nav><main>
      <button id="filter">Filter status</button><p role="alert">Conflict</p>
      <p role="status"></p><section id="today"></section>
      <section id="medications"></section><section id="care-team"></section>
      <button>Add medication</button><dialog><label>Name <input></label></dialog>
    </main><script>
      const dialog = document.querySelector('dialog');
      const opener = document.querySelector('button');
      dialog.showModal(); dialog.addEventListener('cancel', () => opener.focus());
    </script>
    """, encoding="utf-8")
    result = evaluate(root, "ui-ux", 3)
    assert result["passed"] is True, result["errors"]
