"""
Compatibility shim for historical `src.api.middleware.rate_limit` imports.

The canonical rate limiting middleware lives in `src.middleware.rate_limit`.
This wrapper keeps the older import path working without maintaining a
second diverging rate limiting implementation.
"""

from __future__ import annotations

from typing import Optional

from starlette.types import ASGIApp

from src.config.settings import Settings, get_settings
from src.middleware.rate_limit import RateLimitMiddleware as CanonicalRateLimitMiddleware


class RateLimitMiddleware(CanonicalRateLimitMiddleware):
    """Backward-compatible alias to the canonical rate limiting middleware."""

    def __init__(self, app: ASGIApp, settings: Optional[Settings] = None):
        super().__init__(app, settings=settings or get_settings())


__all__ = ["RateLimitMiddleware", "CanonicalRateLimitMiddleware"]
