from adaptive_agent.core.cross_provider_demo import cross_provider_demo


def test_cross_provider_demo_is_offline_and_capability_driven():
    result = cross_provider_demo()
    assert result["offline"] is True
    assert result["quota_consumed"] is False
    assert result["routes"]["product_planner"]["provider"] == "mock_api"
    assert result["routes"]["ui_reviewer"]["provider"] == "mock_api"
    developer = result["routes"]["developer"]
    assert developer["provider"] == "mock_agentic"
    assert any(item["provider"] == "mock_api" and item["disqualified"]
               for item in developer["candidates"])
