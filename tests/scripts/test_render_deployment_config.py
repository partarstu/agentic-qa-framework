# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the deployment configuration renderer (WS26)."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import render_deployment_config
from scripts.render_deployment_config import render

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def manifest():
    return {
        "secrets": ["API_KEY", "DB_PASSWORD"],
        "shared_defaults": {"TZ": "UTC", "LOG_LEVEL": "INFO"},
        "services": {
            "api": {
                "version": "1.0",
                "env": {
                    "PORT_LABEL": "8000",
                    "JOB_NAME": "projects/{project}/locations/{region}/jobs/sync",
                    "API_VERSION": "{version}",
                    "QDRANT_URL": "",
                    "GOOGLE_CLOUD_REGION": "default-region",
                },
                "secrets": {"API_KEY": "API_KEY", "DATABASE_PASSWORD": "DB_PASSWORD"},
            },
            "worker": {"version": "2.0", "env": {"WORKER_ONLY": "on"}, "secrets": {}},
        },
        "environments": {
            "dev": {
                "platform": "gcp",
                "project": "${PROJECT_ID}",
                "region": "europe-west1",
                "overrides": {"LOG_LEVEL": "DEBUG", "PORT_LABEL": "8100"},
            }
        },
    }


def _render(manifest, service="api", runtime=None, **kwargs):
    return render(manifest, service, "dev", runtime, environ={"PROJECT_ID": "proj"}, **kwargs)


class TestPrecedenceChain:
    def test_later_layers_win_over_earlier_ones(self, manifest):
        env = _render(manifest, runtime={"PORT_LABEL": "8200"}).env

        assert env["TZ"] == "UTC"  # shared default
        assert env["GOOGLE_CLOUD_REGION"] == "europe-west1"  # identity beats the service default
        assert env["LOG_LEVEL"] == "DEBUG"  # environment override beats the shared default
        assert env["PORT_LABEL"] == "8200"  # runtime override beats the environment override

    def test_values_are_derived_from_the_target_identity(self, manifest):
        env = _render(manifest).env

        assert env["GOOGLE_CLOUD_PROJECT"] == "proj"
        assert env["JOB_NAME"] == "projects/proj/locations/europe-west1/jobs/sync"
        assert env["API_VERSION"] == "1.0"

    def test_a_target_referencing_an_unset_variable_fails(self, manifest):
        with pytest.raises(ValueError, match="unset variable 'PROJECT_ID'"):
            render(manifest, "api", "dev", environ={})


class TestOverrideRules:
    def test_an_undeclared_runtime_key_is_rejected(self, manifest):
        with pytest.raises(ValueError, match="Runtime override 'UNDECLARED' is not declared"):
            _render(manifest, runtime={"UNDECLARED": "value"})

    def test_an_undeclared_environment_override_is_rejected(self, manifest):
        manifest["environments"]["dev"]["overrides"]["TYPO_KEY"] = "x"

        with pytest.raises(ValueError, match="Environment override 'TYPO_KEY' is not declared"):
            _render(manifest)

    @pytest.mark.parametrize("empty", ["", None], ids=["empty-string", "null"])
    def test_an_empty_override_never_beats_a_default(self, manifest, empty):
        manifest["environments"]["dev"]["overrides"]["TZ"] = empty

        env = _render(manifest, runtime={"PORT_LABEL": ""}).env

        assert env["TZ"] == "UTC"
        assert env["PORT_LABEL"] == "8100"

    def test_an_override_of_another_services_key_is_not_applied(self, manifest):
        env = _render(manifest, runtime={"WORKER_ONLY": "off"}).env

        assert "WORKER_ONLY" not in env

    def test_a_declared_key_without_a_value_is_not_deployed(self, manifest):
        assert "QDRANT_URL" not in _render(manifest).env

    def test_a_runtime_value_fills_a_declared_key_without_default(self, manifest):
        assert _render(manifest, runtime={"QDRANT_URL": "http://qdrant"}).env["QDRANT_URL"] == "http://qdrant"


class TestSecrets:
    def test_secrets_render_as_name_references_only(self, manifest):
        rendered = _render(manifest)

        assert rendered.secrets_flag_value() == "API_KEY=API_KEY:latest,DATABASE_PASSWORD=DB_PASSWORD:latest"
        assert "API_KEY" not in rendered.env

    def test_an_undeclared_secret_name_fails(self, manifest):
        manifest["services"]["api"]["secrets"]["OTHER"] = "NOT_DECLARED"

        with pytest.raises(ValueError, match="undeclared secret 'NOT_DECLARED'"):
            _render(manifest)


class TestRedeployMarker:
    def test_the_marker_is_stable_for_the_same_configuration(self, manifest):
        assert _render(manifest).marker == _render(manifest).marker

    def test_the_marker_starts_with_the_label_safe_version(self, manifest):
        marker = _render(manifest).marker

        assert marker.startswith("1_0-")
        assert re.fullmatch(r"[a-z0-9_-]{1,63}", marker)

    @pytest.mark.parametrize(
        ("runtime", "version"),
        [({"QDRANT_URL": "http://other"}, None), ({}, "1.1")],
        ids=["configuration-changed", "version-changed"],
    )
    def test_the_marker_changes_when_the_configuration_or_version_changes(self, manifest, runtime, version):
        assert _render(manifest, runtime=runtime, version=version).marker != _render(manifest).marker

    def test_the_marker_changes_when_a_secret_reference_changes(self, manifest):
        before = _render(manifest).marker
        manifest["services"]["api"]["secrets"]["API_KEY"] = "DB_PASSWORD"

        assert _render(manifest).marker != before

    def test_a_service_without_version_needs_one_passed(self, manifest):
        del manifest["services"]["api"]["version"]

        with pytest.raises(ValueError, match="declares no version"):
            _render(manifest)
        assert _render(manifest, version="V1.16.3").marker.startswith("v1_16_3-")


@pytest.mark.parametrize(("section", "service", "environment"), [("service", "missing", "dev"), ("environment", "api", "prod")])
def test_an_unknown_service_or_environment_fails(manifest, section, service, environment):
    with pytest.raises(ValueError, match=f"Unknown {section}"):
        render(manifest, service, environment, environ={"PROJECT_ID": "proj"})


def test_main_writes_the_env_file_the_secrets_and_the_marker(manifest, tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    monkeypatch.setenv("PROJECT_ID", "proj")
    monkeypatch.setenv("QUAIA_DEPLOY_OVERRIDE_QDRANT_URL", "http://qdrant")
    monkeypatch.setattr(
        sys, "argv", ["render", "api", "dev", "--manifest", str(manifest_path), "--output-dir", str(output_dir)]
    )

    render_deployment_config.main()

    env = yaml.safe_load((output_dir / "api.env.yaml").read_text(encoding="utf-8"))
    assert env["QDRANT_URL"] == "http://qdrant"
    assert all(isinstance(value, str) for value in env.values())
    assert (output_dir / "api.secrets.txt").read_text(encoding="utf-8").startswith("API_KEY=API_KEY:latest")
    marker = (output_dir / "api.marker").read_text(encoding="utf-8")
    assert capsys.readouterr().out.strip() == marker


def test_every_service_of_the_repository_manifest_renders():
    manifest = yaml.safe_load((REPOSITORY_ROOT / "deploy" / "manifest.yaml").read_text(encoding="utf-8"))

    for service in manifest["services"]:
        rendered = render(manifest, service, "production", version="tag", environ={"PROJECT_ID": "proj"})
        assert rendered.env["TZ"]


@pytest.mark.parametrize(
    ("deployed_marker", "expected_decision"),
    [("1_0-abc", "skip"), ("1_0-old", "deploy"), ("", "deploy")],
    ids=["unchanged", "changed", "never-deployed"],
)
def test_the_redeploy_gate_skips_only_an_unchanged_marker(tmp_path, deployed_marker, expected_decision):
    fake_gcloud = tmp_path / "gcloud"
    fake_gcloud.write_text(f'#!/usr/bin/env bash\necho "{deployed_marker}"\n', encoding="utf-8", newline="\n")
    fake_gcloud.chmod(0o755)
    gate = REPOSITORY_ROOT / "deploy" / "redeploy_gate.sh"

    # The fake gcloud is found through the working directory, which keeps Windows drive letters out of PATH.
    result = subprocess.run(
        [shutil.which("bash"), "-c", 'PATH=".:$PATH" bash "$1" service orchestrator us-central1 1_0-abc', "gate",
         gate.as_posix()],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.stdout.strip() == expected_decision


def test_cloudbuild_deploys_exactly_the_manifest_services_from_their_rendered_files():
    manifest = yaml.safe_load((REPOSITORY_ROOT / "deploy" / "manifest.yaml").read_text(encoding="utf-8"))
    cloudbuild = (REPOSITORY_ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")

    rendered_services = set(re.findall(r"deploy/rendered/([a-z-]+)\.env\.yaml", cloudbuild))
    gated_services = set(re.findall(r"deploy/redeploy_gate\.sh (?:service|job) ([a-z-]+) ", cloudbuild))

    assert rendered_services == set(manifest["services"])
    assert gated_services == set(manifest["services"])
    assert "--set-env-vars" not in cloudbuild
