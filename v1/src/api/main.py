"""
Compatibility shim for historical `src.api.main` imports and launch commands.

The canonical FastAPI application entrypoint lives in `src.app`.
This module intentionally re-exports the same objects so older docs,
scripts, and imports do not create a second live backend implementation.
"""

from __future__ import annotations

from src.app import app, create_app, get_app

__all__ = ["app", "create_app", "get_app"]


if __name__ == "__main__":
    import uvicorn

    from src.config.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "src.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers if not settings.reload else 1,
        log_level=settings.log_level.lower(),
    )
