"""Periodic watchdog: the monitor agent's own clock.

Separate from the Gmail scheduler because it must run whether or not Google is configured.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.core.config import settings
from app.core.database import get_database
from app.services.agents.monitor import follow_up_overdue_orders

logger = logging.getLogger(__name__)


class AgentWatchdog:
    def __init__(self, interval_minutes: Optional[int] = None):
        self.interval = (settings.AGENT_WATCHDOG_INTERVAL_MINUTES if interval_minutes is None else interval_minutes) * 60
        self._task: Optional[asyncio.Task] = None

    @property
    def enabled(self) -> bool:
        return self.interval > 0 and settings.AGENT_AUTOPILOT

    async def start(self) -> None:
        if not self.enabled or self._task is not None:
            logger.info("Agent watchdog disabled (interval=%ss, autopilot=%s)", self.interval, settings.AGENT_AUTOPILOT)
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Agent watchdog started (every %s minutes)", self.interval // 60)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval)
                result = await follow_up_overdue_orders(get_database())
                if result["drafted"]:
                    logger.info("Agent watchdog drafted %s follow-up(s)", result["drafted"])
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Agent watchdog tick failed")


_watchdog: Optional[AgentWatchdog] = None


def get_agent_watchdog() -> AgentWatchdog:
    global _watchdog
    if _watchdog is None:
        _watchdog = AgentWatchdog()
    return _watchdog
