"""Work that outlives the request that started it.

An assistant turn keeps running when the client disconnects, so its reply is still
saved, and a manual schedule run is answered before it finishes. Their tasks are held
here so they are not garbage collected mid-flight, and cancelled when the process ends.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class BackgroundWork:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coroutine: Coroutine[Any, Any, None], *, name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    async def wait(self) -> None:
        """Wait until every task has ended. Never raises a task's error."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        await self.wait()

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("background_task_failed", task=task.get_name(), exc_info=error)
