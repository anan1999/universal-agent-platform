from adaptive_agent.observability.token_tracker import ContextBudget


def test_context_health_and_efficiency_warning():
    budget = ContextBudget(assignments=3)
    assert budget.health == "fatigued"
    assert len(budget.warnings("strong", "file_discovery")) == 2
