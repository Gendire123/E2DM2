import pytest


@pytest.fixture(autouse=True)
def isolate_application_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("E2DM2_HOME", str(tmp_path / "application-home"))
