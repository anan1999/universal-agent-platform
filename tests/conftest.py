import os

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "platform"
    monkeypatch.setenv("UNIVERSAL_AGENT_HOME", str(home))
    return home
