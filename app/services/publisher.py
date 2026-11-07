import asyncio
import logging

import httpx

from app.schemas.analytics_message_dto import AnalyticsMessage
from app.services.http_request_service import HttpRequestService

logger = logging.getLogger(__name__)


class Publisher[T: AnalyticsMessage]:
    def __init__(
        self, name, http: HttpRequestService, max_queue: int = 200, max_retries: int = 3
    ):
        self._http = http
        self._max_retries = max_retries
        self._name = name
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=self._name)

    def publish(self, message: T):
        """Manda los eventos y transacciones a su respectivo microservicio a través de una cola"""
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            dropped = self._queue.get_nowait()
            self._queue.task_done()
            logger.error(
                "[%s] Mensaje descartado tras %s intentos: %s",
                self._name,
                self._max_retries,
                message.model_dump_json(),
            )
            self._queue.put_nowait(message)

    async def _run(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                await self._send(message)
            finally:
                self._queue.task_done()

    async def _send(self, message: T) -> None:
        for attempt in range(self._max_retries):
            try:
                await self._http.post(dict, message)
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            except Exception:
                return
            if attempt < self._max_retries - 1:
                await asyncio.sleep(2**attempt)
        logger.error(
            "[%s] Mensaje descartado tras %s intentos: %s",
            self._name,
            self._max_retries,
            message.model_dump_json(),
        )

    async def stop(self) -> None:
        """Intenta vaciar la cola unos segundos antes de apagar."""
        try:
            await asyncio.wait_for(self._queue.join(), timeout=3)
        except asyncio.TimeoutError:
            logger.warning("Quedaron eventos sin enviar al apagar")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
