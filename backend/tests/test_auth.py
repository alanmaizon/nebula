from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

import app.auth as auth_module
from app.config import settings
from app.main import create_app


@pytest.fixture()
def restore_auth_settings() -> None:
    original = {
        "auth_enabled": settings.auth_enabled,
        "database_url": settings.database_url,
        "storage_root": settings.storage_root,
        "cognito_region": settings.cognito_region,
        "cognito_user_pool_id": settings.cognito_user_pool_id,
        "cognito_app_client_id": settings.cognito_app_client_id,
        "cognito_issuer": settings.cognito_issuer,
    }
    yield
    settings.auth_enabled = original["auth_enabled"]
    settings.database_url = original["database_url"]
    settings.storage_root = original["storage_root"]
    settings.cognito_region = original["cognito_region"]
    settings.cognito_user_pool_id = original["cognito_user_pool_id"]
    settings.cognito_app_client_id = original["cognito_app_client_id"]
    settings.cognito_issuer = original["cognito_issuer"]


def _configure_auth(tmp_path: Path) -> None:
    settings.auth_enabled = True
    settings.database_url = f"sqlite:///{tmp_path}/auth.db"
    settings.storage_root = str(tmp_path / "uploads")
    settings.cognito_region = "eu-central-1"
    settings.cognito_user_pool_id = "eu-central-1_testpool"
    settings.cognito_app_client_id = "test-client-id"
    settings.cognito_issuer = "https://cognito-idp.eu-central-1.amazonaws.com/eu-central-1_testpool"


def test_protected_routes_require_bearer_token_when_auth_enabled(
    tmp_path: Path, restore_auth_settings: None
) -> None:
    _configure_auth(tmp_path)
    app = create_app()
    with TestClient(app) as client:
        for path in ("/projects", "/api/projects"):
            response = client.post(path, json={"name": "Auth Required"})
            assert response.status_code == 401
            assert response.json()["detail"] == "Missing bearer token."


def test_protected_routes_accept_valid_bearer_token_when_auth_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_auth_settings: None,
) -> None:
    _configure_auth(tmp_path)
    monkeypatch.setattr(
        auth_module,
        "decode_and_validate_cognito_token",
        lambda token: {"sub": "user-123", "token_use": "access", "client_id": "test-client-id"},
    )

    app = create_app()
    with TestClient(app) as client:
        for path in ("/projects", "/api/projects"):
            response = client.post(
                path,
                json={"name": "Auth Success"},
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            assert "id" in response.json()


def test_decode_and_validate_cognito_token_accepts_any_configured_client_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_auth_settings: None,
) -> None:
    _configure_auth(tmp_path)
    settings.cognito_app_client_id = "client-a, client-b"

    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(auth_module, "_get_jwks_keys_by_kid", lambda issuer: {"kid-1": {"kid": "kid-1"}})
    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {"sub": "user-123", "token_use": "access", "client_id": "client-b"},
    )

    claims = auth_module.decode_and_validate_cognito_token("test-token")
    assert claims["client_id"] == "client-b"


def test_decode_and_validate_cognito_token_rejects_unknown_client_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_auth_settings: None,
) -> None:
    _configure_auth(tmp_path)
    settings.cognito_app_client_id = "client-a, client-b"

    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(auth_module, "_get_jwks_keys_by_kid", lambda issuer: {"kid-1": {"kid": "kid-1"}})
    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {"sub": "user-123", "token_use": "access", "client_id": "client-c"},
    )

    with pytest.raises(HTTPException) as exc_info:
        auth_module.decode_and_validate_cognito_token("test-token")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Cognito access token client_id does not match configured app client."
