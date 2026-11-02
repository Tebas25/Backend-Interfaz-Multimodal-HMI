import asyncio

import pytest
import speech_recognition as sr

from app.schemas.ws_messages import Screen
from app.services.command_listener_service import CommandListenerService
from app.services.command_processor import NavigateAction
from app.services.screen_state import ScreenState


async def esperar_hasta(condicion, timeout=3.0):
    limite = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < limite:
        if condicion():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.fixture
def procesados(monkeypatch):
    lista = []
    original = CommandListenerService.handle_text

    async def contado(self, texto):
        try:
            await original(self, texto)
        finally:
            lista.append(texto)

    monkeypatch.setattr(CommandListenerService, "handle_text", contado)
    return lista


@pytest.fixture
async def escucha(microfono_falso, procesados):
    acciones = []

    async def on_action(accion):
        acciones.append(accion)

    servicio = CommandListenerService(on_action=on_action)
    assert await servicio.start() is True
    yield acciones
    await servicio.stop()


async def hablar(microfono, audio, texto):
    await asyncio.to_thread(microfono.hablar, audio, texto)


async def test_una_orden_hablada_desde_welcome_llega_como_accion_de_navegar(
    escucha, microfono_falso, procesados
):
    ScreenState.current = Screen.WELCOME

    await hablar(microfono_falso, "a1", "Rony, quiero tomar algo")
    await esperar_hasta(lambda: len(procesados) == 1)

    assert escucha == [NavigateAction(Screen.MENU)]


async def test_lo_que_se_dice_sin_la_palabra_clave_se_ignora(
    escucha, microfono_falso, procesados
):
    ScreenState.current = Screen.WELCOME

    await hablar(microfono_falso, "a1", "quiero tomar algo")
    await hablar(microfono_falso, "a2", "Rony, quiero tomar algo")
    await esperar_hasta(lambda: len(procesados) == 2)

    assert escucha == [NavigateAction(Screen.MENU)]  # solo la segunda frase


async def test_un_audio_que_no_se_entiende_no_interrumpe_la_escucha(
    escucha, microfono_falso, procesados
):
    ScreenState.current = Screen.WELCOME
    microfono_falso.results["ruido"] = sr.UnknownValueError()

    await asyncio.to_thread(
        microfono_falso.background_callback, microfono_falso, "ruido"
    )
    await hablar(microfono_falso, "a2", "Rony quiero ver la carta")
    await esperar_hasta(lambda: len(procesados) == 1)

    assert escucha == [NavigateAction(Screen.MENU)]


async def test_un_error_del_servicio_de_google_no_interrumpe_la_escucha(
    escucha, microfono_falso, procesados
):
    ScreenState.current = Screen.WELCOME
    microfono_falso.results["a1"] = sr.RequestError("sin internet")

    await asyncio.to_thread(microfono_falso.background_callback, microfono_falso, "a1")
    await hablar(microfono_falso, "a2", "Rony dame el menu")
    await esperar_hasta(lambda: len(procesados) == 1)

    assert escucha == [NavigateAction(Screen.MENU)]


async def test_la_misma_frase_se_interpreta_segun_la_pantalla_en_que_este_el_front(
    escucha, microfono_falso, procesados
):
    ScreenState.current = Screen.WELCOME
    await hablar(microfono_falso, "a1", "Rony quiero tomar algo")
    await esperar_hasta(lambda: len(procesados) == 1)

    ScreenState.current = Screen.MENU
    await hablar(microfono_falso, "a2", "Rony quiero tomar algo")
    await esperar_hasta(lambda: len(procesados) == 2)

    ScreenState.current = Screen.WELCOME
    await hablar(microfono_falso, "a3", "Rony quiero tomar algo")
    await esperar_hasta(lambda: len(procesados) == 3)

    assert escucha == [NavigateAction(Screen.MENU), NavigateAction(Screen.MENU)]


async def test_varias_ordenes_seguidas_se_procesan_en_orden(
    escucha, microfono_falso, procesados
):
    ScreenState.current = Screen.WELCOME

    for i in range(4):
        await hablar(microfono_falso, f"a{i}", f"Rony pedir {i}")
    await esperar_hasta(lambda: len(procesados) == 4)

    assert procesados == [f"Rony pedir {i}" for i in range(4)]
    assert len(escucha) == 4


async def test_al_detener_el_servicio_se_deja_de_escuchar(microfono_falso, procesados):
    acciones = []

    async def on_action(accion):
        acciones.append(accion)

    servicio = CommandListenerService(on_action=on_action)
    await servicio.start()

    await servicio.stop()

    microfono_falso.stop_listening.assert_called_once_with(wait_for_stop=False)
    assert servicio._task.cancelled()