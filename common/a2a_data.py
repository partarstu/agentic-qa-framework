# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Conversion between JSON objects and the A2A data parts that carry them between agents."""

from collections.abc import Iterable, Mapping
from typing import Any

from a2a.types import Part
from google.protobuf.json_format import MessageToDict


def data_part(data: Mapping[str, Any]) -> Part:
    """Return a part carrying the JSON object; its numbers become floats on the wire."""
    part = Part()
    part.data.struct_value.update(data)
    return part


def data_objects(parts: Iterable[Part]) -> list[dict[str, Any]]:
    """Return the JSON objects of the parts that carry one, in their order."""
    return [
        MessageToDict(part.data.struct_value)
        for part in parts
        if part.HasField("data") and part.data.WhichOneof("kind") == "struct_value"
    ]
