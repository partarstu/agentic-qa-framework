# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import pytest

from scripts.render_deployment_config import _resolve


@pytest.fixture
def manifest():
    return {
        "shared_defaults": {"LOG_LEVEL": "INFO"},
        "services": {"api": {"env": {"PORT": "8000"}, "secrets": ["API_KEY"]}},
        "environments": {"dev": {"platform": "gcp", "project": "project", "region": "region", "overrides": {"LOG_LEVEL": "DEBUG"}}},
    }


def test_resolve_applies_declared_runtime_override_and_ignores_empty(manifest):
    env, secrets = _resolve(manifest, "api", "dev", {"PORT": "9000", "LOG_LEVEL": ""})
    assert env["PORT"] == "9000"
    assert env["LOG_LEVEL"] == "DEBUG"
    assert secrets == ["API_KEY"]


def test_resolve_rejects_undeclared_runtime_override(manifest):
    with pytest.raises(ValueError, match="not declared"):
        _resolve(manifest, "api", "dev", {"UNDECLARED": "value"})
