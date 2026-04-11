from litestar.testing import TestClient

from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


def test_health_endpoint_returns_ok():
    app = create_app(AiAccountsConfig(env="development"))
    with TestClient(app=app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "version" in body
