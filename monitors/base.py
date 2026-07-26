"""
Abstract base class for all platform monitors.

Provides shared lifecycle (start/stop), error handling with
exponential backoff reconnection, and a callback registration
mechanism for pushing RawAlerts to the engine queue.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, Awaitable

if TYPE_CHECKING:
    from core.engine import RawAlert

logger = logging.getLogger(__name__)

# Type alias for the callback monitors use to push alerts
AlertCallback = Callable[["RawAlert"], Awaitable[None]]


class BaseMonitor(ABC):
    """
    Base class that all platform monitors extend.

    Subclasses implement _run() with their platform-specific logic.
    The base class handles lifecycle, reconnection backoff, and
    callback management.
    """

    PLATFORM: str = "unknown"  # Override in subclasses

    def __init__(self, name: str | None = None) -> None:
        self._name = name or self.__class__.__name__
        self._callback: AlertCallback | None = None
        self._running = False
        self._task: asyncio.Task | None = None

        # Exponential backoff state
        self._backoff_base = 2.0
        self._backoff_max = 300.0  # 5 minutes max
        self._consecutive_errors = 0

    @property
    def name(self) -> str:
        return self._name

    def on_message(self, callback: AlertCallback) -> None:
        """Register the callback that receives RawAlert objects."""
        self._callback = callback

    async def _emit(self, alert: "RawAlert") -> None:
        """Push a RawAlert to the registered callback."""
        if self._callback is not None:
            await self._callback(alert)
        else:
            logger.warning("%s: No callback registered, alert dropped", self._name)

    async def start(self) -> None:
        """Start the monitor with automatic reconnection on failure."""
        if self._running:
            logger.warning("%s: Already running", self._name)
            return

        self._running = True
        logger.info("%s: Starting", self._name)

        while self._running:
            try:
                await self._run()
                # If _run() returns normally, reset backoff
                self._consecutive_errors = 0
            except asyncio.CancelledError:
                logger.info("%s: Cancelled", self._name)
                break
            except Exception:
                self._consecutive_errors += 1
                wait = min(
                    self._backoff_base ** self._consecutive_errors,
                    self._backoff_max,
                )
                logger.exception(
                    "%s: Error (attempt %d), retrying in %.1fs",
                    self._name,
                    self._consecutive_errors,
                    wait,
                )
                try:
                    await asyncio.sleep(wait)
                except asyncio.CancelledError:
                    break

        logger.info("%s: Stopped", self._name)

    async def stop(self) -> None:
        """Signal the monitor to stop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("%s: Stop requested", self._name)

    @abstractmethod
    async def _run(self) -> None:
        """
        Implement platform-specific monitoring logic here.

        This method should run indefinitely (e.g., event loop or poll loop)
        until self._running becomes False. If it raises an exception, the
        base class will handle reconnection with backoff.
        """
        ...
