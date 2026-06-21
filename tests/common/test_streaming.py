# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from common.streaming import compute_activity_budget


def test_compute_activity_budget_doubles_base():
    """Verify that activity budget is correctly computed by doubling the base limit."""
    assert compute_activity_budget(5) == 10
    assert compute_activity_budget(1) == 2
    assert compute_activity_budget(100) == 200
