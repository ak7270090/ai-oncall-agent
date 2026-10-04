import pytest


@pytest.fixture(autouse=True)
def audit_log_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    return tmp_path / "audit.jsonl"


@pytest.fixture
def anyio_backend():
    return "asyncio"
