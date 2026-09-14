from adaptive_agent.project.context_value import gate_source_excerpts


def excerpt(path="src/app.py", size=1000):
    return {"path": path, "content": "x" * size, "excerpt_sha256": "abc", "truncated": False}


def test_unknown_value_defers_body_and_keeps_pointer():
    selected, pointers, decisions = gate_source_excerpts([excerpt()])
    assert selected == []
    assert pointers == [{"path": "src/app.py", "excerpt_sha256": "abc",
                         "content_available_on_demand": True}]
    assert decisions[0].load_tokens == 250
    assert decisions[0].reason == "insufficient source-linked savings evidence"


def test_verified_large_avoided_discovery_admits_excerpt():
    selected, pointers, decisions = gate_source_excerpts(
        [excerpt()], expected_avoided_chars={"src/app.py": 4000},
        confidence={"src/app.py": 0.9})
    assert len(selected) == 1
    assert pointers == []
    assert decisions[0].selected
    assert decisions[0].net_tokens > 0


def test_margin_rejects_small_or_low_confidence_claim():
    selected, pointers, decisions = gate_source_excerpts(
        [excerpt()], expected_avoided_chars={"src/app.py": 1200},
        confidence={"src/app.py": 1.0})
    assert not selected and pointers
    assert "safety margin" in decisions[0].reason

    selected, pointers, decisions = gate_source_excerpts(
        [excerpt()], expected_avoided_chars={"src/app.py": 10000},
        confidence={"src/app.py": 0.5})
    assert not selected and pointers
