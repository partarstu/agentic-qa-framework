# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Render declared deployment configuration for Google Cloud Run."""

import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml

RUNTIME_OVERRIDE_PREFIX = "QUAIA_DEPLOY_OVERRIDE_"


def _resolve(manifest: dict, service: str, environment: str, runtime: dict[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    """Resolve defaults, target identity, environment overrides, and declared runtime overrides."""
    service_config = manifest["services"].get(service)
    if service_config is None:
        raise ValueError(f"Unknown service: {service}")
    environment_config = manifest["environments"].get(environment)
    if environment_config is None:
        raise ValueError(f"Unknown environment: {environment}")
    env = {key: str(value) for key, value in manifest.get("shared_defaults", {}).items()}
    env.update({key: str(value) for key, value in service_config.get("env", {}).items()})
    env.update({"GOOGLE_CLOUD_PROJECT": str(environment_config["project"]), "GOOGLE_CLOUD_REGION": str(environment_config["region"])})
    env.update({key: str(value) for key, value in environment_config.get("overrides", {}).items() if value not in (None, "")})
    declared = set(env) | set(service_config.get("env", {}))
    for key, value in (runtime or {}).items():
        if key not in declared:
            raise ValueError(f"Runtime override {key!r} is not declared by the manifest.")
        if value:
            env[key] = value
    return env, list(service_config.get("secrets", []))


def main() -> None:
    """Render env YAML, secrets flags, and a stable configuration marker."""
    parser = argparse.ArgumentParser()
    parser.add_argument("service")
    parser.add_argument("environment")
    parser.add_argument("--manifest", type=Path, default=Path("deploy/manifest.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("deploy/rendered"))
    args = parser.parse_args()
    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    runtime = {
        key.removeprefix(RUNTIME_OVERRIDE_PREFIX): value
        for key, value in os.environ.items()
        if key.startswith(RUNTIME_OVERRIDE_PREFIX)
    }
    env, secrets = _resolve(manifest, args.service, args.environment, runtime)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    marker = hashlib.sha256(json.dumps({"env": env, "secrets": secrets}, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    (args.output_dir / f"{args.service}.env.yaml").write_text(yaml.safe_dump(env, sort_keys=True), encoding="utf-8")
    (args.output_dir / f"{args.service}.secrets.txt").write_text(
        ",".join(f"{secret}={secret}:latest" for secret in secrets), encoding="utf-8"
    )
    print(marker)


if __name__ == "__main__":
    main()
