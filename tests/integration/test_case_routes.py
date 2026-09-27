"""Browser case demonstrations must stay behind the signed local identity."""

import secrets
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from aspire_brain.config import Settings
from aspire_brain.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def client_for(settings):
    return TestClient(create_app(settings), base_url="http://localhost",
                      client=("127.0.0.1", 50000))


def headers(client):
    session = client.get("/api/session").json()
    return {"X-CSRF-Token": session["csrf_token"], "Origin": "http://localhost"}


def test_case_execution_requires_session_post_and_caller_identity(tmp_path):
    settings = Settings(db_path=tmp_path / "case.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=True)
    with client_for(settings) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        with closing(client.app.state.db.connect()) as connection:
            before = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        assert client.get("/api/cases/case_1").status_code == 405
        with closing(client.app.state.db.connect()) as connection:
            assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before
        assert client.post("/api/cases/case_1", headers=headers(client)).status_code == 401
        assert client.post("/api/demo/session", json={"user_id": "auditor"},
                           headers=headers(client)).status_code == 200
        result = client.post("/api/cases/case_1", headers=headers(client))
        assert result.status_code == 200
        assert result.json()["principal"] == "auditor"
        assert result.json()["packet"]["citations"] == []


def test_case_execution_disabled_without_demo_identity(tmp_path):
    settings = Settings(db_path=tmp_path / "case.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=False)
    with client_for(settings) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        assert client.post("/api/cases/case_1", headers=headers(client)).status_code == 401
    with client_for(replace(settings, demo_mode=True)) as client:
        assert client.post("/api/cases/case_1", headers=headers(client)).status_code == 401


def test_revocation_case_is_repeatable_across_requests(tmp_path):
    settings = Settings(db_path=tmp_path / "case.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=True)
    with client_for(settings) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        assert client.post("/api/demo/session", json={"user_id": "employee"},
                           headers=headers(client)).status_code == 200
        for _ in range(2):
            response = client.post("/api/cases/case_4", headers=headers(client))
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["packet"]["query_status"] == "answered"
            assert result["after_packet"] == "denied"
            assert result["after_query"]["query_status"] == "abstained"


def test_grounding_case_is_browser_visible_and_labelled_simulated(tmp_path):
    settings = Settings(db_path=tmp_path / "case.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=True)
    with client_for(settings) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        assert client.post("/api/demo/session", json={"user_id": "employee"},
                           headers=headers(client)).status_code == 200
        response = client.post("/api/cases/case_7", headers=headers(client))
        assert response.status_code == 200, response.text
        result = response.json()
        assert "state" not in result and "upstream" not in result
        assert result["provider_runtime"]["mode"] == "simulated"
        assert result["provider_runtime"]["live_request_made"] is False
        assert result["provider_runtime"]["outcome"] == "not_run"
        support = result["claim_support"]
        assert support["mode"] == "simulated"
        assert support["provider_mode"] == "fake_grounded"
        assert support["denominator"] >= 1
        assert support["all_supported"] is True
        assert result["default_packet"]["provider_mode"] == "offline_extractive"
        abstention = result["abstention"]["packet"]
        assert abstention["query_status"] == "abstained"
        assert abstention["claim_support"]["abstained"] is True
        assert abstention["claim_support"]["denominator"] == 0
        assert abstention["citations"] == []


def test_unknown_case_is_rejected(tmp_path):
    settings = Settings(db_path=tmp_path / "case.db", session_secret=secrets.token_hex(32),
                        audit_key=secrets.token_bytes(32), demo_mode=True)
    with client_for(settings) as client:
        client.app.state.db.seed(ROOT / "data/demo/manifest.json",
                                 ROOT / "data/demo/principals.json")
        assert client.post("/api/cases/case_9", headers=headers(client)).status_code == 404
