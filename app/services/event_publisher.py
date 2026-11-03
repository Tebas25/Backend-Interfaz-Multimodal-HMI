import asyncio
import logging

import httpx

from app.schemas.events_dto import EventsDTO
from app.services.http_request_service import HttpRequestService

logger = logging.getLogger(__name__)


class EventPublisher:
    def __init__(
        self,
        http: HttpRequestService,
        max_queue: int = 200,
        max_retries: int = 3,
    ):
        self._http = http
        self._max_retries = max_retries
        self._queue: asyncio.Queue[EventsDTO] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="event-publisher")

    def publish(self, evento: EventsDTO) -> None:
        """No bloquea: encola el evento. Si la cola está llena, descarta el más viejo."""
        try:
            self._queue.put_nowait(evento)
        except asyncio.QueueFull:
            dropped = self._queue.get_nowait()
            self._queue.task_done()
            logger.warning("Cola de eventos llena, se descarta %s", dropped.evento_id)
            self._queue.put_nowait(evento)

    async def _run(self) -> None:
        while True:
            evento = await self._queue.get()
            try:
                await self._send(evento)
            finally:
                self._queue.task_done()

    async def _send(self, evento: EventsDTO) -> None:
        for attempt in range(self._max_retries):
            try:
                await self._http.post(dict, evento)
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    logger.error("Micro rechazó el evento %s: %s", evento.evento_id, e)
                    return
                logger.warning("Micro respondió %s", e.response.status_code)
            except httpx.HTTPError as e:
                logger.warning(
                    "No se pudo enviar el evento %s: %s", evento.evento_id, e
                )
            except Exception as e:
                logger.error("Respuesta inesperada del micro, no se reintenta: %s", e)
                return
            await asyncio.sleep(2**attempt)
        logger.error(
            "Evento %s descartado tras %s intentos", evento.evento_id, self._max_retries
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
