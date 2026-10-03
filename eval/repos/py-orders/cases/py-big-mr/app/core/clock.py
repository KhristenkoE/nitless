# Copyright (c) 2026 Acme Commerce GmbH
# SPDX-License-Identifier: Apache-2.0
"""Single source of "now" for the whole service.

Tests freeze time by monkeypatching ``app.core.clock.utcnow``, so call it through the
module (``clock.utcnow()``) rather than importing the function.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
