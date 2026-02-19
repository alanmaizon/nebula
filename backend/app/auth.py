from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings


_bearer_scheme = HTTPBearer(auto_error=False)
_JWKS_CACHE_TTL_SECONDS = 300.0
_jwks_cache: dict[str, Any] = {
    "issuer": "",
    "expires_at": 0.0,
    "keys_by_kid": {},
}


def _auth_unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _auth_misconfigured(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


def _cognito_issuer() -> str:
    configured = str(settings.cognito_issuer or "").strip().rstrip("/")
    if configured:
        return configured

    region = str(settings.cognito_region or "").strip() or str(settings.aws_region or "").strip()
    user_pool_id = str(settings.cognito_user_pool_id or "").strip()
    if not region or not user_pool_id:
        raise _auth_misconfigured(
            "Cognito is enabled but issuer is not configured. Set COGNITO_ISSUER or "
            "set both COGNITO_REGION and COGNITO_USER_POOL_ID."
        )
    return f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"


def _get_jwks_keys_by_kid(issuer: str) -> dict[str, dict[str, Any]]:
    now = time.time()
    cached_issuer = str(_jwks_cache.get("issuer") or "")
    cached_expiry = float(_jwks_cache.get("expires_at") or 0.0)
    cached_keys = _jwks_cache.get("keys_by_kid")
    if (
        cached_issuer == issuer
        and cached_expiry > now
        and isinstance(cached_keys, dict)
        and cached_keys
    ):
        return cached_keys

    jwks_url = f"{issuer}/.well-known/jwks.json"
    try:
        response = httpx.get(jwks_url, timeout=5.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise _auth_misconfigured(f"Unable to fetch Cognito JWKS from '{jwks_url}': {exc}") from exc

    keys = payload.get("keys")
    if not isinstance(keys, list):
        raise _auth_misconfigured("Invalid Cognito JWKS payload: missing 'keys' list.")

    keys_by_kid: dict[str, dict[str, Any]] = {}
    for key in keys:
        if isinstance(key, dict):
            kid = key.get("kid")
            if isinstance(kid, str) and kid.strip():
                keys_by_kid[kid] = key

    if not keys_by_kid:
        raise _auth_misconfigured("Cognito JWKS payload did not include any usable signing keys.")

    _jwks_cache["issuer"] = issuer
    _jwks_cache["expires_at"] = now + _JWKS_CACHE_TTL_SECONDS
    _jwks_cache["keys_by_kid"] = keys_by_kid
    return keys_by_kid


def decode_and_validate_cognito_token(token: str) -> dict[str, Any]:
    app_client_id = str(settings.cognito_app_client_id or "").strip()
    if not app_client_id:
        raise _auth_misconfigured("Cognito is enabled but COGNITO_APP_CLIENT_ID is not configured.")

    issuer = _cognito_issuer()
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise _auth_unauthorized("Malformed JWT header.") from exc

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid.strip():
        raise _auth_unauthorized("JWT header does not include a valid key id (kid).")

    keys_by_kid = _get_jwks_keys_by_kid(issuer)
    signing_key = keys_by_kid.get(kid)
    if signing_key is None:
        raise _auth_unauthorized("JWT key id is not recognized by Cognito.")

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise _auth_unauthorized(f"Invalid or expired Cognito token: {exc}") from exc

    token_use = claims.get("token_use")
    if token_use == "access":
        if claims.get("client_id") != app_client_id:
            raise _auth_unauthorized("Cognito access token client_id does not match configured app client.")
    elif token_use == "id":
        audience = claims.get("aud")
        if isinstance(audience, str):
            aud_ok = audience == app_client_id
        elif isinstance(audience, list):
            aud_ok = app_client_id in audience
        else:
            aud_ok = False
        if not aud_ok:
            raise _auth_unauthorized("Cognito ID token audience does not match configured app client.")
    else:
        raise _auth_unauthorized("Unsupported Cognito token type. Use a Cognito access token or ID token.")

    return claims


def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any] | None:
    if not settings.auth_enabled:
        return None

    if credentials is None:
        raise _auth_unauthorized("Missing bearer token.")
    if credentials.scheme.lower() != "bearer":
        raise _auth_unauthorized("Unsupported authorization scheme.")

    token = credentials.credentials.strip()
    if not token:
        raise _auth_unauthorized("Missing bearer token.")

    return decode_and_validate_cognito_token(token)
