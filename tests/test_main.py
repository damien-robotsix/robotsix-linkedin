"""Tests for the ``python -m linkedin_service`` entrypoint."""

from __future__ import annotations

from unittest.mock import patch

from linkedin_service.__main__ import main


def test_main_wires_structured_logging_before_serving() -> None:
    """``main`` sets up fleet structured logging, then starts uvicorn."""
    call_order: list[str] = []

    with (
        patch("linkedin_service.__main__.setup_structlog") as mock_setup,
        patch("linkedin_service.__main__.uvicorn.run") as mock_run,
    ):
        mock_setup.side_effect = lambda *a, **k: call_order.append("setup")
        mock_run.side_effect = lambda *a, **k: call_order.append("run")

        main()

    # Logging must be configured before the server starts.
    assert call_order == ["setup", "run"]

    # JSON renderer and the service + uvicorn loggers are wired.
    _, setup_kwargs = mock_setup.call_args
    assert setup_kwargs["fmt"] == "json"
    assert "linkedin_service" in setup_kwargs["loggers"]
    assert "uvicorn" in setup_kwargs["loggers"]

    # uvicorn must not install its own handlers so records reach the root bridge.
    _, run_kwargs = mock_run.call_args
    assert run_kwargs["log_config"] is None
