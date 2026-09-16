# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Sync state for the Confluence document ingestion (WS9): fingerprints per item.

One fingerprint per page body and per attachment holds the version number, the raw
content hash, the ingestion-schema version and identity/metadata (space, page,
title, URL, attachment name). Fingerprints live in the metadata collection as
payload records and never call the embedding service.

Change detection is version numbers plus raw-content hashes; the per-scope cursor
records the last successful sync but does not decide what gets skipped (see the
implementation plan's decisions table).
"""

import hashlib
import json

from common.services.vector_db_service import VectorDbService

FINGERPRINT_RECORD_KIND = "sync-fingerprint"

# Bump when normalization, chunking or rendering logic changes, so stored
# fingerprints no longer match and items are re-ingested.
INGESTION_SCHEMA_VERSION = 1


def content_hash(raw_content: str | bytes, *extra: str) -> str:
    """A stable hash of an item's raw content plus identity fields feeding it.

    The page title is hashed together with the raw body, because the title is part
    of every chunk's breadcrumb (WS9 step 5).
    """
    if isinstance(raw_content, str):
        raw_content = raw_content.encode("utf-8")
    digest = hashlib.sha256(raw_content)
    for value in extra:
        digest.update(b"\x00")
        digest.update(value.encode("utf-8"))
    return digest.hexdigest()


class FingerprintStore:
    """Reads and writes per-scope fingerprints in the metadata collection."""

    def __init__(self, metadata_db: VectorDbService):
        self._metadata_db = metadata_db

    @staticmethod
    def record_id(scope: str, item_key: str) -> str:
        return f"{FINGERPRINT_RECORD_KIND}-{scope}-{item_key}"

    async def load_scope(self, scope: str) -> dict[str, dict]:
        """Loads every stored fingerprint of one scope in one read.

        Returns a mapping from item key to fingerprint payload; item keys are
        ``page:<pageId>`` for page bodies and ``attachment:<attachmentId>`` for
        attachments. The records are re-filtered client-side so a server that
        ignores payload filters (or returns neighbouring records) cannot leak
        other kinds into the result.
        """
        records = await self._metadata_db.scroll_payload_records(
            filter_by={"kind": FINGERPRINT_RECORD_KIND, "scope": scope}
        )
        return {
            payload["item_key"]: payload
            for payload in records
            if payload.get("kind") == FINGERPRINT_RECORD_KIND and payload.get("scope") == scope and payload.get("item_key")
        }

    async def save(self, scope: str, item_key: str, fingerprint: dict) -> None:
        record = {
            "kind": FINGERPRINT_RECORD_KIND,
            "scope": scope,
            "item_key": item_key,
            **fingerprint,
        }
        await self._metadata_db.upsert_payload_record(self.record_id(scope, item_key), record)

    async def delete(self, scope: str, item_key: str) -> None:
        await self._metadata_db.delete_payload_record(self.record_id(scope, item_key))

    async def delete_scope(self, scope: str) -> None:
        """Deletes every fingerprint of a scope (a removed page takes its attachments)."""
        records = await self._metadata_db.scroll_payload_records(
            filter_by={"kind": FINGERPRINT_RECORD_KIND, "scope": scope}
        )
        for payload in records:
            await self._metadata_db.delete_payload_record(
                self.record_id(scope, payload["item_key"])
            )


def to_json(value: dict) -> str:
    """Canonical JSON for hashing-adjacent storage; keys sorted for stability."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
