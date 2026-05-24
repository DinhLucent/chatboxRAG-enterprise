from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def stable_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "RAGFLOW_BASE_URL",
        "RAGFLOW_API_KEY",
        "RAGFLOW_TECHNICAL_ACTIVE_DATASET_ID",
        "RAGFLOW_CHAT_ID",
        "RAGFLOW_SEARCH_ID",
        "KB_REQUIRE_AUTH",
        "KB_AUTH_TOKEN",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KB_ENABLE_LOCAL_FALLBACK", "true")
    monkeypatch.setenv("KB_ALLOWED_PROVIDERS", "auto,ragflow,local")
