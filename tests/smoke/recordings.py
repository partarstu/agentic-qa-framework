# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Reading back what reached the recording mocks of the smoke topology.

Shared by the assertions in ``test_smoke.py`` and by the snapshot collection in
``artifacts.py``, which read the same ``/__recorded`` endpoints.
"""

import time
from collections.abc import Callable

import httpx

# The webhook returns only after the whole flow completes, so the recordings are
# already in place; this short poll only absorbs any last write lag.
RECORD_POLL_TIMEOUT = 30.0
RECORD_POLL_INTERVAL = 2.0


def wait_for_recorded(http_client: httpx.Client, url: str, predicate: Callable[[dict], bool]) -> dict:
    """Poll a mock's /__recorded endpoint until the predicate holds or time runs out."""
    deadline = time.monotonic() + RECORD_POLL_TIMEOUT
    data: dict = {}
    while time.monotonic() < deadline:
        response = http_client.get(url)
        if response.status_code == 200:
            data = response.json()
            if predicate(data):
                return data
        time.sleep(RECORD_POLL_INTERVAL)
    return data


def wait_for_any_recorded(
    http_client: httpx.Client, urls: dict[str, str], predicate: Callable[[dict[str, dict]], bool]
) -> dict[str, dict]:
    """Poll several /__recorded endpoints together until the predicate holds over all their data.

    Polling them in one loop means a result on any source ends the wait immediately,
    instead of spending the whole timeout on a source that will never satisfy it.
    """
    deadline = time.monotonic() + RECORD_POLL_TIMEOUT
    data: dict[str, dict] = {name: {} for name in urls}
    while time.monotonic() < deadline:
        for name, url in urls.items():
            response = http_client.get(url)
            if response.status_code == 200:
                data[name] = response.json()
        if predicate(data):
            return data
        time.sleep(RECORD_POLL_INTERVAL)
    return data
