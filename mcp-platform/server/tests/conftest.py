import pytest


@pytest.fixture(autouse=True)
def audit_log_in_tmp(tmp_path, monkeypatch):
    for server in ("K8S", "PROMETHEUS"):
        monkeypatch.setenv(f"MCP_{server}_SERVER__AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    return tmp_path / "audit.jsonl"


@pytest.fixture
def anyio_backend():
    return "asyncio"
