"""Entry-point for ``python -m linkedin_service``."""

from __future__ import annotations

import uvicorn
from robotsix_llmio.logging import setup_structlog

from .config import settings


def main() -> None:
    """Configure structured logging and start the LinkedIn service with uvicorn.

    Installs the fleet-standard JSON structlog bridge for the ``linkedin_service``
    and uvicorn loggers, then runs ``linkedin_service.app:app`` on the host and
    port from ``settings``. This call blocks until the server exits.
    """
    # Adopt the fleet-standard structured-logging bridge before starting the
    # server so both linkedin_service and uvicorn records render as JSON with
    # OTel trace-id injection.
    setup_structlog(
        fmt="json",
        loggers=("linkedin_service", "uvicorn", "uvicorn.access", "uvicorn.error"),
    )
    uvicorn.run(
        "linkedin_service.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        # ``log_config=None`` stops uvicorn from installing its own handlers,
        # letting its loggers propagate to the root bridge.
        log_config=None,
    )


if __name__ == "__main__":
    main()
