from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

_DEFAULT_LIMITS = ["200/day", "50/hour"]


def _default_limits() -> list[str]:
    raw = os.getenv("RATE_LIMIT_DEFAULTS")
    if not raw:
        return _DEFAULT_LIMITS
    return [item.strip() for item in raw.split(",") if item.strip()]


storage_uri = os.getenv("RATE_LIMIT_STORAGE_URI")
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=_default_limits(),
    storage_uri=storage_uri,
)
