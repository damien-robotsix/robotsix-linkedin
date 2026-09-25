"""Entry-point for ``python -m linkedin_service``."""

from __future__ import annotations

import uvicorn
from robotsix_llmio.logging import setup_structlog

from .config import settings


def main() -> None:
    # Adopt the fleet-standard structured-logging bridge before starting the
    # server so both linkedin_service and uvicorn records render as JSON with
    # OTel trace-id injection. ``log_config=None`` stops uvicorn from installing
    # its own handlers, letting its loggers propagate to the root bridge.
    setup_structlog(
        fmt="json",
        loggers=("linkedin_service", "uvicorn", "uvicorn.access", "uvicorn.error"),
    )
    uvicorn.run(
        "linkedin_service.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
