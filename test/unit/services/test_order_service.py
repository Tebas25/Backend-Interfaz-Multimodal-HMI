import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.core.core_constants import DEFAULT_EVENT_ID
from app.core.voice_response import VoiceEvent
from app.schemas.events_dto import EventsDTO, TipoEvento
from app.schemas.ws_messages import CobotStatus, Screen
from app.services.order_service import ORDER_SCREEN, OrderService
from app.services.screen_state import ScreenState

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


def make_service(gen_fn=two_events, items=None, on_voice=None):
    manager = MagicMock()
    manager.broadcast = AsyncMock()
    watcher = SimpleNamespace(items_activos=[ITEM] if items is None else items)
    cobot = MagicMock()
    cobot.prepare_drink = gen_fn
    publisher = MagicMock()
    service = OrderService(manager, watcher, cobot, publisher, on_voice=on_voice)
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
            yield _evento(200)

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
            yield _evento(200)

        service, _, _ = make_service(recording)
        service.request_order("Cuba Libre")
        await service._task
        assert received == [3]

    async def test_broadcasts_each_event(self):
        service, manager, publisher = make_service()
        service.request_order("Cuba Libre")
        await service._task
        sent = sent_messages(manager)
        assert [type(m) for m in sent] == [CobotStatus, CobotStatus]
        assert [m.payload.codigo for m in sent] == [101, 200]

    async def test_publishes_each_event_to_analytics(self):
        service, _, publisher = make_service()
        service.request_order("Cuba Libre")
        await service._task
        published = [c.args[0] for c in publisher.publish.call_args_list]
        assert [e.codigo for e in published] == [101, 200]
        assert {e.evento_id for e in published} == {DEFAULT_EVENT_ID}

    async def test_handles_cobot_service_failure_without_broadcasting(self):
        async def boom(code):
            raise RuntimeError("fallo")
            yield

        service, manager, publisher = make_service(boom)
        service.request_order("Cuba Libre")
        await service._task
        assert sent_messages(manager) == []
        publisher.publish.assert_not_called()


@pytest.mark.asyncio
class TestStop:
    async def test_stop_cancels_running_order_without_navigating(self):
        async def never(code):
            await asyncio.Event().wait()
            yield _evento(200)

        service, manager, _ = make_service(never)
        service.request_order("Cuba Libre")
        await asyncio.sleep(0)
        await service.stop()
        assert service._task.cancelled()
        manager.broadcast.assert_not_awaited()

    async def test_stop_without_order_does_nothing(self):
        service, _, _ = make_service()
        await service.stop()


# ---------- respuestas por voz ----------


def secuencia(*codigos):
    """Generador que simula al cobot emitiendo esos códigos, en orden."""

    async def gen(code):
        for codigo in codigos:
            yield _evento(codigo)

    return gen


def voz():
    """on_voice de prueba: como speak, pero sin tarea (devuelve None)."""
    return MagicMock(return_value=None)


async def pedir(service):
    assert service.request_order("Cuba Libre") is None
    await service._task


PREPARANDO = call(VoiceEvent.PREPARING_DRINK, drink="Cuba Libre")
LISTO = call(VoiceEvent.PREPARING_COMPLETE, drink="Cuba Libre")


@pytest.mark.asyncio
class TestVoz:
    @pytest.mark.parametrize("codigo", [101, 102])
    async def test_anuncia_la_preparacion_con_el_nombre_de_la_bebida(self, codigo):
        on_voice = voz()
        service, _, _ = make_service(secuencia(codigo), on_voice=on_voice)

        await pedir(service)

        assert on_voice.call_args_list == [PREPARANDO]

    async def test_anuncia_la_preparacion_una_sola_vez(self):
        on_voice = voz()
        service, _, _ = make_service(secuencia(101, 102, 101), on_voice=on_voice)

        await pedir(service)

        assert on_voice.call_args_list == [PREPARANDO]

    async def test_anuncia_el_final_cuando_llega_el_codigo_200(self):
        on_voice = voz()
        service, _, _ = make_service(secuencia(200), on_voice=on_voice)

        await pedir(service)

        assert on_voice.call_args_list == [LISTO]

    async def test_un_pedido_completo_anuncia_preparacion_y_final_en_orden(self):
        on_voice = voz()
        service, _, _ = make_service(two_events, on_voice=on_voice)

        await pedir(service)

        assert on_voice.call_args_list == [PREPARANDO, LISTO]

    async def test_otros_codigos_no_hablan(self):
        on_voice = voz()
        service, manager, _ = make_service(secuencia(None, 103, 150), on_voice=on_voice)

        await pedir(service)

        on_voice.assert_not_called()
        assert len(sent_messages(manager)) == 3  # igual se difunden al front

    async def test_sin_on_voice_el_pedido_funciona_igual(self):
        service, manager, publisher = make_service(two_events, on_voice=None)

        await pedir(service)

        assert len(sent_messages(manager)) == 2
        assert publisher.publish.call_count == 2

    async def test_la_voz_va_despues_de_difundir_y_publicar_el_evento(self):
        orden = []
        on_voice = MagicMock(side_effect=lambda *a, **k: orden.append("voz"))
        service, manager, publisher = make_service(secuencia(101), on_voice=on_voice)
        manager.broadcast.side_effect = lambda msg: orden.append("broadcast")
        publisher.publish.side_effect = lambda evento: orden.append("publish")

        await pedir(service)

        assert orden == ["broadcast", "publish", "voz"]

    async def test_cada_pedido_vuelve_a_anunciar_la_preparacion(self):
        on_voice = voz()
        service, _, _ = make_service(two_events, on_voice=on_voice)

        await pedir(service)
        await pedir(service)

        assert on_voice.call_args_list == [PREPARANDO, LISTO, PREPARANDO, LISTO]

    async def test_si_el_cobot_falla_antes_del_final_no_hay_despedida(self):
        async def falla_a_medias(code):
            yield _evento(101)
            raise RuntimeError("fallo")

        on_voice = voz()
        service, _, _ = make_service(falla_a_medias, on_voice=on_voice)

        await pedir(service)

        assert on_voice.call_args_list == [PREPARANDO]


@pytest.mark.asyncio
class TestDespedida:
    """La despedida (código 200) devuelve la tarea de speak y el pedido la espera."""

    @staticmethod
    def voz_con_tarea(despedida):
        tareas = []

        def on_voice(evento, **kwargs):
            if evento is VoiceEvent.PREPARING_COMPLETE:
                tareas.append(asyncio.create_task(despedida()))
                return tareas[-1]

        return on_voice, tareas

    async def test_el_pedido_espera_a_que_termine_la_despedida(self):
        terminado = []

        async def despedida():
            await asyncio.sleep(0.01)
            terminado.append(True)

        on_voice, _ = self.voz_con_tarea(despedida)
        service, _, _ = make_service(secuencia(200), on_voice=on_voice)

        await pedir(service)

        assert terminado == [True]  # _run no terminó hasta que acabó el audio

    async def test_si_la_despedida_tarda_demasiado_el_pedido_termina_igual(
        self, monkeypatch
    ):
        espera_real = asyncio.wait_for

        async def espera_corta(awaitable, timeout):
            assert timeout == 8.0  # el tiempo máximo configurado en el servicio
            return await espera_real(awaitable, timeout=0.01)

        monkeypatch.setattr(asyncio, "wait_for", espera_corta)

        async def despedida():
            await asyncio.Event().wait()

        on_voice, tareas = self.voz_con_tarea(despedida)
        service, _, _ = make_service(secuencia(200), on_voice=on_voice)

        await pedir(service)

        assert service._task.exception() is None
        assert tareas[0].cancelled()

    async def test_si_la_despedida_falla_el_pedido_termina_sin_error(self):
        async def despedida():
            raise RuntimeError("sin audio")

        on_voice, _ = self.voz_con_tarea(despedida)
        service, _, _ = make_service(secuencia(200), on_voice=on_voice)

        await pedir(service)

        assert service._task.exception() is None

    async def test_si_on_voice_no_devuelve_tarea_no_hay_nada_que_esperar(self):
        service, _, _ = make_service(secuencia(200), on_voice=voz())

        await pedir(service)

        assert service._task.exception() is None


@pytest.mark.asyncio
class TestStopConVoz:
    async def test_stop_durante_la_preparacion_no_dice_el_final(self):
        async def prepara_y_se_queda(code):
            yield _evento(101)
            await asyncio.Event().wait()
            yield _evento(200)

        on_voice = voz()
        service, _, _ = make_service(prepara_y_se_queda, on_voice=on_voice)
        service.request_order("Cuba Libre")
        for _ in range(5):
            await asyncio.sleep(0)

        await service.stop()

        assert service._task.cancelled()
        assert on_voice.call_args_list == [PREPARANDO]

    async def test_stop_durante_la_despedida_cancela_la_espera_y_el_audio(self):
        async def despedida():
            await asyncio.Event().wait()

        on_voice, tareas = TestDespedida.voz_con_tarea(despedida)
        service, _, _ = make_service(secuencia(200), on_voice=on_voice)
        service.request_order("Cuba Libre")
        for _ in range(5):  # el pedido llega a esperar la despedida
            await asyncio.sleep(0)
        assert not service._task.done()

        await service.stop()

        assert service._task.cancelled()
        assert tareas[0].cancelled()
