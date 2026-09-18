# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Render the declared deployment configuration of one workload for Google Cloud Run (WS26).

The precedence chain, later layers winning: shared defaults and the service's own env -> values
derived from the deployment target's identity -> the environment's overrides -> runtime overrides
(``QUAIA_DEPLOY_OVERRIDE_<KEY>`` variables). An override may only set a key the manifest declares,
and an empty value never beats a default. The output per service is an env-vars file for
``--env-vars-file``, the ``--set-secrets`` value (secret names only) and the redeploy marker: the
service version plus a hash of the rendered configuration, stored as a label on the deployed workload.
"""

import argparse
import hashlib
import json
import os
import re
import string
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

RUNTIME_OVERRIDE_PREFIX = "QUAIA_DEPLOY_OVERRIDE_"
# Cloud Run label values allow lowercase letters, digits, underscores and dashes, up to 63 characters.
_LABEL_VALUE_INVALID_CHARACTERS = re.compile(r"[^a-z0-9_-]")
_LABEL_VALUE_MAX_LENGTH = 63
_CONFIG_HASH_LENGTH = 16


@dataclass(frozen=True, slots=True)
class RenderedService:
    """The platform-native configuration of one service in one environment."""

    env: dict[str, str]
    secrets: dict[str, str]
    marker: str

    def secrets_flag_value(self) -> str:
        """The ``--set-secrets`` value: ``ENV=SECRET_NAME:latest`` pairs."""
        return ",".join(f"{env_key}={secret_name}:latest" for env_key, secret_name in sorted(self.secrets.items()))


def render(
    manifest: Mapping,
    service: str,
    environment: str,
    runtime: Mapping[str, str] | None = None,
    *,
    version: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> RenderedService:
    """Resolve one service's configuration for one environment.

    Args:
        manifest: The parsed deployment manifest.
        service: The service name, as declared under ``services``.
        environment: The environment name, as declared under ``environments``.
        runtime: Runtime overrides by key (without the variable prefix).
        version: Overrides the manifest's version of the service (e.g. a third-party image tag).
        environ: Variables the target identity may reference as ``${NAME}``; defaults to the process environment.

    Raises:
        ValueError: For an unknown service or environment, an undeclared override key or secret name, a
            missing version, or a target identity referencing an unset variable.
    """
    service_config = _lookup(manifest, "services", service)
    environment_config = _lookup(manifest, "environments", environment)
    project, region = _target_identity(environment_config, os.environ if environ is None else environ)
    resolved_version = version or service_config.get("version")
    if not resolved_version:
        raise ValueError(f"Service {service!r} declares no version and none was passed.")

    declared_by_manifest = _declared_keys(manifest)
    env = _strings(manifest.get("shared_defaults", {})) | _strings(service_config.get("env", {}))
    declared_by_service = set(env)
    env |= {"GOOGLE_CLOUD_PROJECT": project, "GOOGLE_CLOUD_REGION": region}
    for source, overrides in (
        ("Environment override", environment_config.get("overrides", {})),
        ("Runtime override", runtime or {}),
    ):
        env |= _applicable_overrides(source, overrides, declared_by_manifest, declared_by_service)

    placeholders = {"{project}": project, "{region}": region, "{version}": str(resolved_version)}
    rendered_env = {key: _expand(value, placeholders) for key, value in sorted(env.items()) if value}
    secrets = _secrets(manifest, service, service_config)
    return RenderedService(env=rendered_env, secrets=secrets, marker=_marker(str(resolved_version), rendered_env, secrets))


def _lookup(manifest: Mapping, section: str, name: str) -> Mapping:
    entry = manifest.get(section, {}).get(name)
    if entry is None:
        raise ValueError(f"Unknown {section.removesuffix('s')}: {name!r}")
    return entry


def _target_identity(environment_config: Mapping, environ: Mapping[str, str]) -> tuple[str, str]:
    """The target project and region; either may reference a variable as ``${NAME}``."""
    raw_project, raw_region = str(environment_config["project"]), str(environment_config["region"])
    try:
        project = string.Template(raw_project).substitute(environ)
        region = string.Template(raw_region).substitute(environ)
    except KeyError as exc:
        raise ValueError(f"The deployment target references the unset variable {exc.args[0]!r}.") from exc
    return project, region


def _declared_keys(manifest: Mapping) -> set[str]:
    """Every env key the manifest declares, in the shared defaults or in any service."""
    declared = set(manifest.get("shared_defaults", {}))
    for service_config in manifest.get("services", {}).values():
        declared |= set(service_config.get("env", {}))
    return declared


def _applicable_overrides(
    source: str, overrides: Mapping, declared_by_manifest: set[str], declared_by_service: set[str]
) -> dict[str, str]:
    """The non-empty overrides of keys this service declares; a key no service declares is an error."""
    undeclared = sorted(set(overrides) - declared_by_manifest)
    if undeclared:
        raise ValueError(f"{source} {undeclared[0]!r} is not declared by the manifest.")
    return {
        key: str(value)
        for key, value in overrides.items()
        if value not in (None, "") and key in declared_by_service
    }


def _secrets(manifest: Mapping, service: str, service_config: Mapping) -> dict[str, str]:
    """The service's secrets by env key; every referenced secret name must be declared."""
    declared = set(manifest.get("secrets", []))
    secrets = _strings(service_config.get("secrets", {}))
    for secret_name in secrets.values():
        if secret_name not in declared:
            raise ValueError(f"Service {service!r} references the undeclared secret {secret_name!r}.")
    return secrets


def _strings(values: Mapping) -> dict[str, str]:
    return {str(key): "" if value is None else str(value) for key, value in values.items()}


def _expand(value: str, placeholders: Mapping[str, str]) -> str:
    for placeholder, replacement in placeholders.items():
        value = value.replace(placeholder, replacement)
    return value


def _marker(version: str, env: Mapping[str, str], secrets: Mapping[str, str]) -> str:
    """The redeploy marker: a label-safe version plus a hash of the rendered configuration."""
    configuration = json.dumps({"env": env, "secrets": secrets}, sort_keys=True).encode("utf-8")
    config_hash = hashlib.sha256(configuration).hexdigest()[:_CONFIG_HASH_LENGTH]
    label_version = _LABEL_VALUE_INVALID_CHARACTERS.sub("_", version.lower())
    return f"{label_version[: _LABEL_VALUE_MAX_LENGTH - _CONFIG_HASH_LENGTH - 1]}-{config_hash}"


def main() -> None:
    """Render one service and write ``<service>.env.yaml``, ``<service>.secrets.txt`` and ``<service>.marker``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("service")
    parser.add_argument("environment")
    parser.add_argument("--manifest", type=Path, default=Path("deploy/manifest.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("deploy/rendered"))
    parser.add_argument("--version", help="Overrides the manifest's version of the service, e.g. an image tag.")
    args = parser.parse_args()
    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    runtime = {
        key.removeprefix(RUNTIME_OVERRIDE_PREFIX): value
        for key, value in os.environ.items()
        if key.startswith(RUNTIME_OVERRIDE_PREFIX)
    }
    rendered = render(manifest, args.service, args.environment, runtime, version=args.version)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / f"{args.service}.env.yaml").write_text(yaml.safe_dump(rendered.env), encoding="utf-8")
    (args.output_dir / f"{args.service}.secrets.txt").write_text(rendered.secrets_flag_value(), encoding="utf-8")
    (args.output_dir / f"{args.service}.marker").write_text(rendered.marker, encoding="utf-8")
    print(rendered.marker)


if __name__ == "__main__":
    main()
