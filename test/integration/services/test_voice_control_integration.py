import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.voice_response import VoiceEvent
from app.schemas.ws_messages import (
    FrontState,
    Navigate,
    NavigatePayload,
    Screen,
    StatePayload,
    StateSource,
)
from app.services.command_listener_service import CommandListenerService
from app.services.screen_state import ScreenState


class ServicioHttpInerte:
    def __init__(self, url, authkey=None):
        self.url = url

    async def get(self, tipo, **kwargs):
        raise RuntimeError("sin red en las pruebas")

    async def close(self):
        pass


class WatcherInerte:

    catalogo = None
    ultima_actualizacion = None
    items_activos = []

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    async def stop(self):
        pass


def esperar(condicion, timeout=3.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def estado(pantalla: Screen, origen=StateSource.TOUCH) -> str:
    return FrontState(
        payload=StatePayload(screen=pantalla, source=origen)
    ).model_dump_json()


@pytest.fixture(autouse=True)
def app_sin_red(monkeypatch):
    monkeypatch.setattr(main, "HttpRequestService", ServicioHttpInerte)
    monkeypatch.setattr(main, "CatalogWatcher", WatcherInerte)


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


def marcador() -> Navigate:
    return Navigate(payload=NavigatePayload(screen=Screen.WELCOME))


# ---------- la orden hablada llega al front ----------


def test_una_orden_de_voz_en_welcome_envia_navigate_al_menu(
    microfono_falso, procesados, voz_falsa
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)

        microfono_falso.hablar("a1", "Rony, quiero tomar algo")
        mensaje = ws.receive_json()
        assert esperar(lambda: len(voz_falsa.eventos()) == 2)

    assert mensaje["type"] == "navigate"
    assert mensaje["payload"] == {"screen": "menu"}
    assert voz_falsa.eventos() == [
        VoiceEvent.INITIAL_WELCOME,  # al reportar el front la pantalla de bienvenida
        VoiceEvent.VISUALIZE_MENU,  # al navegar al menú por voz
    ]


def test_el_navigate_de_voz_llega_a_todos_los_clientes_conectados(
    microfono_falso, procesados
):
    with TestClient(main.app) as client:
        with (
            client.websocket_connect("/ws") as ws1,
            client.websocket_connect("/ws") as ws2,
        ):
            ws1.send_text(estado(Screen.WELCOME, StateSource.INIT))
            assert esperar(lambda: ScreenState.current is Screen.WELCOME)

            microfono_falso.hablar("a1", "Rony dame el menú")
            m1, m2 = ws1.receive_json(), ws2.receive_json()

    assert m1["id"] == m2["id"]
    assert m1["payload"]["screen"] == "menu"


def test_el_navigate_de_voz_es_un_mensaje_valido_con_id_y_fecha(
    microfono_falso, procesados
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)

        microfono_falso.hablar("a1", "Rony quiero una bebida")
        mensaje = Navigate.model_validate(ws.receive_json())

    assert mensaje.payload.screen is Screen.MENU
    assert len(mensaje.id) == 32
    assert mensaje.ts.utcoffset().total_seconds() == 0


# ---------- lo que NO debe navegar ----------


def test_sin_la_palabra_clave_no_se_envia_nada(microfono_falso, procesados):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)

        microfono_falso.hablar("a1", "quiero tomar algo")
        assert esperar(lambda: len(procesados) == 1)
        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        primero = ws.receive_json()

    assert primero["payload"]["screen"] == "welcome"


def test_desde_la_pantalla_menu_la_orden_de_pedir_no_navega(
    microfono_falso, procesados, voz_falsa
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.MENU))
        assert esperar(lambda: ScreenState.current is Screen.MENU)

        microfono_falso.hablar("a1", "Rony quiero tomar algo")
        assert esperar(lambda: len(procesados) == 1)
        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        primero = ws.receive_json()
        assert esperar(lambda: len(voz_falsa.eventos()) == 1)

    assert primero["payload"]["screen"] == "welcome"
    # No hay navegación: el robot solo avisa que esa bebida no está en el menú
    assert voz_falsa.eventos() == [VoiceEvent.DRINK_NOT_IN_MENU]


def test_lo_que_entiende_el_backend_sigue_la_pantalla_que_informa_el_front(
    microfono_falso, procesados, voz_falsa
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)
        microfono_falso.hablar("a1", "Rony quiero tomar algo")
        assert ws.receive_json()["payload"]["screen"] == "menu"

        ws.send_text(estado(Screen.MENU))
        assert esperar(lambda: ScreenState.current is Screen.MENU)
        microfono_falso.hablar("a2", "Rony quiero tomar algo")
        assert esperar(lambda: len(procesados) == 2)
        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        siguiente = ws.receive_json()
        assert esperar(lambda: len(voz_falsa.eventos()) == 3)

    assert (
        siguiente["payload"]["screen"] == "welcome"
    )  # no hubo un segundo navigate a menu
    assert voz_falsa.eventos() == [
        VoiceEvent.INITIAL_WELCOME,
        VoiceEvent.VISUALIZE_MENU,
        VoiceEvent.DRINK_NOT_IN_MENU,  # la misma frase en el menú ya no navega
    ]


@pytest.mark.parametrize("frase", ["Rony hola", "Rony cuéntame un chiste"])
def test_en_welcome_una_orden_sin_sentido_responde_por_voz_y_no_navega(
    microfono_falso, procesados, voz_falsa, frase
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)

        microfono_falso.hablar("a1", frase)
        assert esperar(lambda: len(procesados) == 1)
        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        primero = ws.receive_json()
        assert esperar(lambda: len(voz_falsa.eventos()) == 2)

    assert primero["payload"]["screen"] == "welcome"  # solo llegó el marcador
    assert voz_falsa.eventos() == [
        VoiceEvent.INITIAL_WELCOME,
        VoiceEvent.NOT_UNDERSTOOD,
    ]


def test_sin_la_palabra_clave_el_robot_no_responde_por_voz(
    microfono_falso, procesados, voz_falsa
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.MENU))
        assert esperar(lambda: ScreenState.current is Screen.MENU)

        microfono_falso.hablar("a1", "quiero tomar algo")
        assert esperar(lambda: len(procesados) == 1)
        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        ws.receive_json()

    assert voz_falsa.eventos() == []


def test_el_saludo_inicial_se_dice_una_sola_vez_aunque_welcome_se_repita(
    microfono_falso, voz_falsa
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: len(voz_falsa.eventos()) == 1)

        ws.send_text(estado(Screen.MENU))
        assert esperar(lambda: ScreenState.current is Screen.MENU)
        ws.send_text(estado(Screen.WELCOME))  # vuelve dentro del cooldown
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)
        ws.send_text("hola")  # respuesta de error: los anteriores ya se procesaron
        assert ws.receive_json()["type"] == "error"

    assert voz_falsa.eventos() == [VoiceEvent.INITIAL_WELCOME]


# ---------- resiliencia ----------


def test_un_fallo_del_reconocimiento_no_impide_las_ordenes_siguientes(
    microfono_falso, procesados
):
    import speech_recognition as sr

    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)

        microfono_falso.results["a1"] = sr.RequestError("sin internet")
        microfono_falso.background_callback(microfono_falso, "a1")
        microfono_falso.hablar("a2", "Rony dame el menu")
        mensaje = ws.receive_json()

    assert mensaje["payload"]["screen"] == "menu"


def test_sin_microfono_la_app_arranca_y_el_websocket_funciona():
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        listener = main.app.state.command_listener
        ws.send_text(estado(Screen.MENU))

        assert esperar(lambda: ScreenState.current is Screen.MENU)
        assert listener._task is None

    assert ScreenState.current is Screen.MENU


# ---------- ciclo de vida ----------


def test_al_iniciar_la_app_empieza_a_escuchar(microfono_falso):
    with TestClient(main.app):
        listener = main.app.state.command_listener

        assert microfono_falso.ambient_calls == [("fuente-de-audio", 1)]
        assert len(microfono_falso.background_calls) == 1
        assert listener._task is not None and not listener._task.done()


def test_al_apagar_la_app_se_libera_el_reproductor_de_audio(voz_falsa):
    with TestClient(main.app):
        voz_falsa.tts_cls.assert_called_once_with()
        voz_falsa.player.close.assert_not_called()

    voz_falsa.player.close.assert_called_once()


def test_al_apagar_la_app_se_deja_de_escuchar(microfono_falso):
    with TestClient(main.app):
        listener = main.app.state.command_listener

    microfono_falso.stop_listening.assert_called_once_with(wait_for_stop=False)
    assert listener._task.cancelled()
