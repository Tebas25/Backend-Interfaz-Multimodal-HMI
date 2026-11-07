import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.events_dto import EventsDTO, TipoEvento
from app.schemas.ws_messages import CobotStatus, Navigate, Screen
from app.services.order_service import ORDER_SCREEN, OrderService
from app.services.screen_state import ScreenState
from app.core.core_constants import DEFAULT_EVENT_ID

ITEM = SimpleNamespace(nombre_item="Cuba Libre", codigo_modbus=3)


def _evento(codigo: int | None) -> EventsDTO:
    return EventsDTO(
        cobot_id="CBT000T",
        evento_id=DEFAULT_EVENT_ID,
        tipo_evento=TipoEvento.INFO_ROBOT,
        descripcion="d",
        codigo=codigo,
    )


async def two_events(code):
    yield _evento(101)
    yield _evento(200)


def make_service(gen_fn=two_events, items=None):
    manager = MagicMock()
    manager.broadcast = AsyncMock()
    watcher = SimpleNamespace(items_activos=[ITEM] if items is None else items)
    cobot = MagicMock()
    cobot.prepare_drink = gen_fn
    publisher = MagicMock()
    service = OrderService(manager, watcher, cobot, publisher)
    return service, manager, publisher


def sent_messages(manager):
    return [c.args[0] for c in manager.broadcast.await_args_list]


@pytest.fixture(autouse=True)
def pantalla_de_pedido():
    ScreenState.reset()
    ScreenState.current = ORDER_SCREEN
    yield
    ScreenState.reset()


def test_to_payload_uses_cobot_code():
    payload = OrderService._to_payload(_evento(102))
    assert payload.codigo == 102
    assert payload.tipo_evento is TipoEvento.INFO_ROBOT


def test_to_payload_without_code_uses_minus_one():
    assert OrderService._to_payload(_evento(None)).codigo == -1


@pytest.mark.asyncio
class TestRequestOrder:
    async def test_rejects_when_not_on_order_screen(self):
        ScreenState.current = Screen.WELCOME
        service, _, _ = make_service()
        error = service.request_order("Cuba Libre")
        assert error == "Los pedidos solo se aceptan desde la pantalla de pago"
        assert service._task is None

    async def test_rejects_from_the_menu_before_paying(self):
        ScreenState.current = Screen.MENU
        service, _, _ = make_service()
        assert service.request_order("Cuba Libre") is not None
        assert service._task is None

    async def test_rejects_when_screen_unknown(self):
        ScreenState.reset()
        service, _, _ = make_service()
        assert service.request_order("Cuba Libre") is not None

    async def test_rejects_unknown_drink(self):
        service, _, _ = make_service()
        assert service.request_order("No existe") == "Bebida no disponible"

    async def test_rejects_drink_without_modbus_code(self):
        item = SimpleNamespace(nombre_item="Agua", codigo_modbus=None)
        service, _, _ = make_service(items=[item])
        assert (
            service.request_order("Agua") == "La bebida no tiene código para el cobot"
        )

    async def test_rejects_second_order_while_one_is_running(self):
        release = asyncio.Event()

        async def blocking(code):
            await release.wait()
            yield _evento("200")

        service, _, _ = make_service(blocking)
        assert service.request_order("Cuba Libre") is None
        assert service.request_order("Cuba Libre") == "Ya hay un pedido en curso"
        release.set()
        await service._task

    async def test_accepts_new_order_after_previous_finished(self):
        service, _, _ = make_service()
        assert service.request_order("Cuba Libre") is None
        await service._task
        assert service.request_order("Cuba Libre") is None
        await service._task


@pytest.mark.asyncio
class TestRun:
    async def test_passes_catalog_code_to_cobot(self):
        received = []

        async def recording(code):
            received.append(code)
            yield _evento("200")

        service, _, _ = make_service(recording)
        service.request_order("Cuba Libre")
        await service._task
        assert received == [3]

    async def test_broadcasts_each_event_then_navigates_to_welcome(self):
        service, manager, publisher = make_service()
        service.request_order("Cuba Libre")
        await service._task
        sent = sent_messages(manager)
        assert [type(m) for m in sent] == [CobotStatus, CobotStatus, Navigate]
        assert [m.payload.codigo for m in sent[:2]] == [101, 200]
        assert sent[2].payload.screen is Screen.WELCOME

    async def test_publishes_each_event_to_analytics(self):
        service, _, publisher = make_service()
        service.request_order("Cuba Libre")
        await service._task
        published = [c.args[0] for c in publisher.publish.call_args_list]
        assert [e.codigo for e in published] == [101, 200]
        assert {e.evento_id for e in published} == {DEFAULT_EVENT_ID}

    async def test_navigates_to_welcome_even_if_cobot_service_fails(self):
        async def boom(code):
            raise RuntimeError("fallo")
            yield

        service, manager, publisher = make_service(boom)
        service.request_order("Cuba Libre")
        await service._task
        sent = sent_messages(manager)
        assert [type(m) for m in sent] == [Navigate]
        publisher.publish.assert_not_called()


@pytest.mark.asyncio
class TestStop:
    async def test_stop_cancels_running_order_without_navigating(self):
        async def never(code):
            await asyncio.Event().wait()
            yield _evento("200")

        service, manager, _ = make_service(never)
        service.request_order("Cuba Libre")
        await asyncio.sleep(0)
        await service.stop()
        assert service._task.cancelled()
        manager.broadcast.assert_not_awaited()

    async def test_stop_without_order_does_nothing(self):
        service, _, _ = make_service()
        await service.stop()
