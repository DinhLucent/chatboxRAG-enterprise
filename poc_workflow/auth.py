from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AuthConfig:
    required: bool
    configured: bool


def auth_config() -> AuthConfig:
    token = os.getenv("KB_AUTH_TOKEN", "")
    require_auth = os.getenv("KB_REQUIRE_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
    return AuthConfig(required=require_auth or bool(token), configured=bool(token))


def public_auth_status() -> dict[str, bool]:
    config = auth_config()
    return {
        "required": config.required,
        "configured": config.configured,
    }


def require_operator_auth(request: Request) -> None:
    config = auth_config()
    if not config.required:
        return

    expected = os.getenv("KB_AUTH_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="KB_REQUIRE_AUTH is enabled but KB_AUTH_TOKEN is not configured",
        )

    provided = request.headers.get("x-kb-token", "")
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()

    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Operator token is required")

