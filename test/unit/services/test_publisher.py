import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.schemas.events_dto import EventsDTO, TipoEvento
from app.schemas.transactions_dto import TransactionsDTO  # ajusta al nombre real
from app.services.publisher import Publisher


def _evento(evento_id: str = "EVT-001", descripcion: str = "d") -> EventsDTO:
    return EventsDTO(
        cobot_id="CBT000T",
        evento_id=evento_id,
        tipo_evento=TipoEvento.INFO_ROBOT,
        descripcion=descripcion,
    )


def _transaccion(item: str = "Cuba Libre", ingreso: float = 6.4) -> TransactionsDTO:
    return TransactionsDTO(
        cobot_id="CBT000T", evento_id="EVT-001", item=item, ingreso=ingreso
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
    publisher = Publisher("test", http, max_queue=2)
    for i in ("1", "2", "3"):
        publisher.publish(_evento(i))
    remaining = [publisher._queue.get_nowait().evento_id for _ in range(2)]
    assert remaining == ["2", "3"]


def test_publish_drops_oldest_transaction_when_queue_is_full(http):
    publisher = Publisher("tx", http, max_queue=1)
    publisher.publish(_transaccion("Ron"))
    publisher.publish(_transaccion("Vodka"))
    assert publisher._queue.get_nowait().item == "Vodka"


@pytest.mark.asyncio
class TestPublisher:
    async def test_worker_delivers_published_events(self, http):
        publisher = Publisher("test", http)
        publisher.start()
        evento = _evento()
        publisher.publish(evento)
        await asyncio.wait_for(publisher._queue.join(), timeout=1)
        http.post.assert_awaited_once_with(dict, evento)
        await publisher.stop()

    async def test_worker_delivers_transactions(self, http):
        publisher = Publisher("tx", http)
        publisher.start()
        tx = _transaccion()
        publisher.publish(tx)
        await asyncio.wait_for(publisher._queue.join(), timeout=1)
        http.post.assert_awaited_once_with(dict, tx)
        await publisher.stop()

    async def test_task_uses_publisher_name(self, http):
        publisher = Publisher("transaction-publisher", http)
        publisher.start()
        assert publisher._task.get_name() == "transaction-publisher"
        await publisher.stop()

    async def test_send_success_does_not_retry(self, http, no_sleep):
        publisher = Publisher("test", http)
        await publisher._send(_evento())
        assert http.post.await_count == 1
        no_sleep.assert_not_awaited()

    async def test_send_retries_on_server_error(self, http, no_sleep):
        http.post = AsyncMock(side_effect=[_status_error(503), {"ok": True}])
        publisher = Publisher("test", http)
        await publisher._send(_evento())
        assert http.post.await_count == 2
        no_sleep.assert_awaited_once_with(1)

    async def test_send_retries_on_network_error(self, http, no_sleep):
        http.post = AsyncMock(side_effect=[httpx.ConnectError("down"), {"ok": True}])
        publisher = Publisher("test", http)
        await publisher._send(_evento())
        assert http.post.await_count == 2

    async def test_send_does_not_retry_client_errors(self, http, no_sleep):
        http.post = AsyncMock(side_effect=_status_error(422))
        publisher = Publisher("test", http)
        await publisher._send(_evento())
        assert http.post.await_count == 1
        no_sleep.assert_not_awaited()

    async def test_send_does_not_retry_unexpected_errors(self, http, no_sleep):
        http.post = AsyncMock(side_effect=ValueError("respuesta rara"))
        publisher = Publisher("test", http)
        await publisher._send(_evento())
        assert http.post.await_count == 1

    async def test_send_gives_up_after_max_retries(self, http, no_sleep):
        http.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        publisher = Publisher("test", http, max_retries=3)
        await publisher._send(_evento())
        assert http.post.await_count == 3

    async def test_no_sleep_after_last_attempt(self, http, no_sleep):
        http.post = AsyncMock(side_effect=_status_error(500))
        publisher = Publisher("test", http, max_retries=3)
        await publisher._send(_evento())
        assert [c.args[0] for c in no_sleep.await_args_list] == [1, 2]

    async def test_discarded_message_is_logged_with_name_and_content(
        self, http, no_sleep, caplog
    ):
        http.post = AsyncMock(side_effect=_status_error(503))
        publisher = Publisher("transaction-publisher", http, max_retries=2)
        with caplog.at_level(logging.ERROR):
            await publisher._send(_transaccion("Ron", 10.4))
        assert "transaction-publisher" in caplog.text
        assert "Ron" in caplog.text
        assert "10.4" in caplog.text

    async def test_success_does_not_log_error(self, http, caplog):
        publisher = Publisher("test", http)
        with caplog.at_level(logging.ERROR):
            await publisher._send(_evento())
        assert caplog.text == ""

    async def test_worker_survives_after_discarding_a_message(self, http, no_sleep):
        http.post = AsyncMock(
            side_effect=[
                _status_error(503),
                _status_error(503),
                {"ok": True},
            ]
        )
        publisher = Publisher("test", http, max_retries=2)
        publisher.start()
        publisher.publish(_evento("1"))
        publisher.publish(_evento("2"))
        await asyncio.wait_for(publisher._queue.join(), timeout=1)
        assert http.post.await_count == 3
        await publisher.stop()

    async def test_stop_cancels_worker(self, http):
        publisher = Publisher("test", http)
        publisher.start()
        await publisher.stop()
        assert publisher._task.done()

    async def test_stop_without_start_does_not_fail(self, http):
        await Publisher("test", http).stop()

    async def test_stop_logs_warning_when_queue_join_times_out(
        self, http, monkeypatch, caplog
    ):
        publisher = Publisher("test", http)

        async def fake_wait_for(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        with caplog.at_level(logging.WARNING):
            await publisher.stop()
        assert "Quedaron eventos sin enviar al apagar" in caplog.text
