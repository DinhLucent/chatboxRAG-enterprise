from __future__ import annotations

import os
import sys

import pytest


if sys.platform == "win32":
    _original_mkdir = os.mkdir

    def _windows_mkdir_without_unix_mode(path, mode=0o777, *, dir_fd=None):  # type: ignore[no-untyped-def]
        # Pytest creates tmp_path roots with 0o700; on this workstation that ACL
        # becomes unreadable in constrained Windows sessions. Keep test dirs usable.
        if dir_fd is not None:
            return _original_mkdir(path, 0o777, dir_fd=dir_fd)
        return _original_mkdir(path, 0o777)

    os.mkdir = _windows_mkdir_without_unix_mode  # type: ignore[assignment]


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
