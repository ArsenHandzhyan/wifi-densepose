"""
Compatibility shim for historical `src.api.middleware.auth` imports.

The canonical authentication middleware lives in `src.middleware.auth`.
This wrapper keeps the older import path working without maintaining a
second diverging authentication implementation.
"""

from __future__ import annotations

from typing import Optional

from starlette.types import ASGIApp

from src.config.settings import Settings, get_settings
from src.middleware.auth import AuthenticationMiddleware


class AuthMiddleware(AuthenticationMiddleware):
    """Backward-compatible alias to the canonical authentication middleware."""

    def __init__(self, app: ASGIApp, settings: Optional[Settings] = None):
        super().__init__(app, settings=settings or get_settings())


__all__ = ["AuthMiddleware", "AuthenticationMiddleware"]
