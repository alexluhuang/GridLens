from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient


AUTH_MODE_NONE = "none"
AUTH_MODE_COGNITO = "cognito"


@dataclass(slots=True, frozen=True)
class AuthSettings:
    mode: str = AUTH_MODE_NONE
    cognito_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""

    @property
    def enabled(self) -> bool:
        return self.mode == AUTH_MODE_COGNITO

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"


@dataclass(slots=True, frozen=True)
class AuthenticatedUser:
    subject: str
    username: str
    email: str
    is_authenticated: bool = True

    @property
    def storage_namespace(self) -> str:
        return hashlib.sha256(self.subject.encode("utf-8")).hexdigest()[:32]


def load_auth_settings() -> AuthSettings:
    mode = os.environ.get("GRIDLENS_AUTH_MODE", AUTH_MODE_NONE).strip().lower() or AUTH_MODE_NONE
    if mode not in {AUTH_MODE_NONE, AUTH_MODE_COGNITO}:
        raise RuntimeError("GRIDLENS_AUTH_MODE must be either 'none' or 'cognito'.")
    if mode == AUTH_MODE_NONE:
        return AuthSettings(mode=AUTH_MODE_NONE)

    region = os.environ.get("GRIDLENS_COGNITO_REGION", "").strip()
    user_pool_id = os.environ.get("GRIDLENS_COGNITO_USER_POOL_ID", "").strip()
    client_id = os.environ.get("GRIDLENS_COGNITO_CLIENT_ID", "").strip()
    missing = [
        name
        for name, value in (
            ("GRIDLENS_COGNITO_REGION", region),
            ("GRIDLENS_COGNITO_USER_POOL_ID", user_pool_id),
            ("GRIDLENS_COGNITO_CLIENT_ID", client_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing Cognito auth configuration: {', '.join(missing)}")
    return AuthSettings(
        mode=AUTH_MODE_COGNITO,
        cognito_region=region,
        cognito_user_pool_id=user_pool_id,
        cognito_client_id=client_id,
    )


class CognitoTokenVerifier:
    def __init__(self, settings: AuthSettings):
        self.settings = settings
        self._jwks_client = PyJWKClient(settings.jwks_url)

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.") from exc

        token_use = str(unverified_claims.get("token_use") or "")
        if token_use not in {"id", "access"}:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unsupported authentication token.")

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            if token_use == "id":
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=self.settings.cognito_client_id,
                    issuer=self.settings.issuer,
                )
            else:
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    issuer=self.settings.issuer,
                    options={"verify_aud": False},
                )
                client_id = str(claims.get("client_id") or "")
                if client_id != self.settings.cognito_client_id:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token was not issued for this client.")
        except HTTPException:
            raise
        except (jwt.PyJWTError, URLError, OSError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication could not be verified.") from exc

        subject = str(claims.get("sub") or "").strip()
        username = str(claims.get("cognito:username") or claims.get("username") or claims.get("email") or subject).strip()
        email = str(claims.get("email") or "").strip()
        if not subject:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token is missing a subject.")
        return AuthenticatedUser(subject=subject, username=username or subject, email=email)


def get_current_user(request: Request) -> AuthenticatedUser:
    settings: AuthSettings = request.app.state.auth_settings
    if not settings.enabled:
        return AuthenticatedUser(subject="local-user", username="local-user", email="", is_authenticated=False)

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")

    verifier: CognitoTokenVerifier = request.app.state.token_verifier
    return verifier.verify(token)


def auth_metadata(settings: AuthSettings) -> dict[str, Any]:
    return {
        "enabled": settings.enabled,
        "mode": settings.mode,
    }


def load_json_url(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
