"""What both MCP servers share (base_server.py): /health and transport security."""

from starlette.testclient import TestClient

from base_server import build_transport_security
from config import Settings
from prometheus.server import build_prometheus_server


def fake_settings(**overrides) -> Settings:
    return Settings(_env_file=None, backend="fake", **overrides)


def test_health_route():
    with TestClient(build_prometheus_server(fake_settings()).streamable_http_app()) as http:
        assert http.get("/health").json() == {"status": "ok"}


def test_transport_security_uses_sdk_default_without_allowed_hosts():
    assert build_transport_security(fake_settings()) is None


def test_transport_security_enforces_allowed_hosts():
    security = build_transport_security(fake_settings(allowed_hosts=["mcp-server:*"]))
    assert security.enable_dns_rebinding_protection
    assert security.allowed_hosts == ["mcp-server:*"]


def test_foreign_host_header_rejected():
    server = build_prometheus_server(fake_settings())
    app = server.streamable_http_app(transport_security=build_transport_security(fake_settings(allowed_hosts=["mcp-server:*"])))
    with TestClient(app) as http:
        response = http.post("/mcp", headers={"Host": "evil.example:9000"}, json={})
    assert response.status_code == 421
