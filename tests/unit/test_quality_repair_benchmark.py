import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "quality_repair_benchmark", ROOT / "scripts/quality_repair_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_usage_aggregation_preserves_measured_cost():
    result = benchmark._add_usage(
        {"input": 100, "output": 10, "cached": 50, "source": "measured", "invocation_count": 1},
        {"input": 40, "output": 5, "cached": 20, "source": "measured", "invocation_count": 1},
    )
    assert result == {
        "input": 140, "output": 15, "cached": 70,
        "source": "measured", "invocation_count": 2,
    }


def test_usage_aggregation_rejects_unmeasured_repair():
    result = benchmark._add_usage(
        {"input": 100, "source": "measured"}, {"source": "unavailable"})
    assert result["source"] == "unavailable"
