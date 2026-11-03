import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.schemas.events_dto import EventsDTO, TipoEvento
from app.services.event_publisher import EventPublisher


def _evento(evento_id: str = "1") -> EventsDTO:
    return EventsDTO(
        cobot_id="CBT000T",
        evento_id=evento_id,
        tipo_evento=TipoEvento.INFO_ROBOT,
        descripcion="d",
    )


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://test/events")
    return httpx.HTTPStatusError(
        "boom", request=req, response=httpx.Response(code, request=req)
    )


@pytest.fixture
def http():
    h = MagicMock()
    h.post = AsyncMock(return_value={"status": "success"})
    return h


@pytest.fixture
def no_sleep(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    return sleep


def test_publish_drops_oldest_when_queue_is_full(http):
    publisher = EventPublisher(http, max_queue=2)
    for i in ("1", "2", "3"):
        publisher.publish(_evento(i))
    remaining = [publisher._queue.get_nowait().evento_id for _ in range(2)]
    assert remaining == ["2", "3"]


@pytest.mark.asyncio
class TestPublisher:
    async def test_worker_delivers_published_events(self, http):
        publisher = EventPublisher(http)
        publisher.start()
        evento = _evento()
        publisher.publish(evento)
        await asyncio.wait_for(publisher._queue.join(), timeout=1)
        http.post.assert_awaited_once_with(dict, evento)
        await publisher.stop()

    async def test_send_retries_on_server_error(self, http, no_sleep):
        http.post = AsyncMock(side_effect=[_status_error(503), {"ok": True}])
        publisher = EventPublisher(http)
        await publisher._send(_evento())
        assert http.post.await_count == 2
        no_sleep.assert_awaited_once_with(1)

    async def test_send_does_not_retry_client_errors(self, http, no_sleep):
        http.post = AsyncMock(side_effect=_status_error(422))
        publisher = EventPublisher(http)
        await publisher._send(_evento())
        assert http.post.await_count == 1
        no_sleep.assert_not_awaited()

    async def test_send_gives_up_after_max_retries(self, http, no_sleep):
        http.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        publisher = EventPublisher(http, max_retries=3)
        await publisher._send(_evento())
        assert http.post.await_count == 3

    async def test_send_does_not_retry_unexpected_errors(self, http, no_sleep):
        http.post = AsyncMock(side_effect=ValueError("respuesta rara"))
        publisher = EventPublisher(http)
        await publisher._send(_evento())
        assert http.post.await_count == 1

    async def test_stop_cancels_worker(self, http):
        publisher = EventPublisher(http)
        publisher.start()
        await publisher.stop()
        assert publisher._task.done()

    async def test_stop_without_start_does_not_fail(self, http):
        await EventPublisher(http).stop()
