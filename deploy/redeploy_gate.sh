#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

# Redeploy gate (WS26). Prints "deploy" when the workload must be (re)deployed and "skip" when its
# deployed marker label equals the rendered one; a workload that doesn't exist yet is always deployed.
# Usage: redeploy_gate.sh <service|job> <name> <region> <marker>
set -euo pipefail

kind="$1"
name="$2"
region="$3"
marker="$4"

case "$kind" in
  service) describe=(gcloud run services describe) ;;
  job) describe=(gcloud run jobs describe) ;;
  *) echo "Unknown workload kind: $kind" >&2; exit 2 ;;
esac

deployed=$("${describe[@]}" "$name" --region="$region" \
  --format='value(metadata.labels.quaia_deploy_marker)' 2>/dev/null || true)

if [ "$deployed" = "$marker" ]; then
  echo "Skipping $kind $name: its deployed marker $marker is unchanged." >&2
  echo "skip"
else
  echo "Deploying $kind $name: marker '${deployed:-none}' -> '$marker'." >&2
  echo "deploy"
fi
