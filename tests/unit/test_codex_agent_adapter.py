from adaptive_agent.agents.codex_adapter import CodexAgentConfigAdapter


def test_codex_agent_config_adapter_preserves_unknown_fields(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    config = agents / "luna_worker.toml"
    config.write_text('name="luna_worker"\nmodel="gpt-5.6-luna"\nmodel_reasoning_effort="low"\ncustom=42\n', encoding="utf-8")
    imported = CodexAgentConfigAdapter().discover(tmp_path)[0]
    assert imported.model == "gpt-5.6-luna"
    assert imported.reasoning == "low"
    assert imported.unknown_fields == {"custom": 42}
    assert imported.registry_spec()["external_agent_config"]["read_only"] is True

