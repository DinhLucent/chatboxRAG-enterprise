from __future__ import annotations

import os


VALID_PROVIDERS = {"auto", "ragflow", "local"}


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def local_fallback_enabled() -> bool:
    return env_bool("KB_ENABLE_LOCAL_FALLBACK", True)


def allowed_providers() -> set[str]:
    raw = os.getenv("KB_ALLOWED_PROVIDERS")
    if not raw:
        return set(VALID_PROVIDERS)
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    return values & VALID_PROVIDERS


def provider_allowed(provider: str) -> bool:
    provider = provider.lower().strip()
    if provider not in VALID_PROVIDERS:
        return False
    if provider == "local" and not local_fallback_enabled():
        return False
    return provider in allowed_providers()
