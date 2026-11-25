from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api import endpoints
from app.api.endpoints import handle_client_message, ws_endpoint, ws_router
from app.core.voice_response import VoiceEvent
from app.schemas.ws_messages import (
    ErrorMessage,
    FrontState,
    Navigate,
    NavigatePayload,
    Screen,
    StatePayload,
    StateSource,
)
from app.services.screen_state import ScreenState


def state_json(screen=Screen.MENU, source=StateSource.TOUCH, ref=None) -> str:
    """Mensaje 'state' válido tal como lo enviaría el front."""
    return FrontState(
        payload=StatePayload(screen=screen, source=source, ref=ref)
    ).model_dump_json()


@pytest.fixture
def manager():
    m = MagicMock()
    m.connect = AsyncMock()
    m.send = AsyncMock()
    m.disconnect = MagicMock()
    return m


@pytest.fixture
def watcher():
    return MagicMock()


@pytest.fixture(autouse=True)
def sin_snapshot(monkeypatch):
    """Por defecto no hay catálogo descargado; las pruebas de snapshot lo sobrescriben."""
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: None)


@pytest.fixture
def make_ws(manager, watcher):
    def _make(receive_side_effect):
        ws = MagicMock()
        ws.app.state.ws_manager = manager
        ws.app.state.catalog_watcher = watcher
        ws.receive_text = AsyncMock(side_effect=receive_side_effect)
        return ws

    return _make


def mensajes_de_error(manager):
    """ErrorMessage enviados al cliente durante la prueba."""
    return [
        c.args[1]
        for c in manager.send.await_args_list
        if isinstance(c.args[1], ErrorMessage)
    ]


# ---------- router ----------


def test_ws_router_registra_la_ruta_ws():
    rutas = {r.path for r in ws_router.routes}

    assert "/ws" in rutas


# ---------- handle_client_message ----------


async def test_handle_front_state_actualiza_screen_state():
    msg = FrontState(payload=StatePayload(screen=Screen.MENU, source=StateSource.TOUCH))

    await handle_client_message(msg, MagicMock())

    assert ScreenState.current is Screen.MENU
    assert ScreenState.source is StateSource.TOUCH


async def test_handle_front_state_con_ref_guarda_la_referencia():
    msg = FrontState(
        payload=StatePayload(
            screen=Screen.WELCOME, source=StateSource.BACKEND, ref="r-1"
        )
    )

    await handle_client_message(msg, MagicMock())

    assert ScreenState.ref == "r-1"


@pytest.mark.parametrize(
    "mensaje",
    [
        Navigate(payload=NavigatePayload(screen=Screen.MENU)),
        object(),
        None,
        "texto",
    ],
)
async def test_handle_ignora_mensajes_que_no_son_front_state(mensaje):
    await handle_client_message(mensaje, MagicMock())  # no debe lanzar

    assert ScreenState.current is None


# ---------- conexión ----------


async def test_conecta_al_cliente_con_el_manager(make_ws, manager):
    ws = make_ws([WebSocketDisconnect()])

    await ws_endpoint(ws)

    manager.connect.assert_awaited_once_with(ws)


async def test_imprime_el_handshake(make_ws, capsys):
    ws = make_ws([WebSocketDisconnect()])

    await ws_endpoint(ws)

    assert "[WS] handshake recibido" in capsys.readouterr().out


# ---------- snapshot inicial ----------


async def test_envia_snapshot_si_hay_catalogo(make_ws, manager, watcher, monkeypatch):
    snapshot = MagicMock(name="snapshot")
    construir = MagicMock(return_value=snapshot)
    monkeypatch.setattr(endpoints, "build_catalog_update", construir)
    ws = make_ws([WebSocketDisconnect()])

    await ws_endpoint(ws)

    construir.assert_called_once_with(watcher)
    manager.send.assert_awaited_once_with(ws, snapshot)


async def test_no_envia_snapshot_si_no_hay_catalogo(make_ws, manager):
    ws = make_ws([WebSocketDisconnect()])

    await ws_endpoint(ws)

    manager.send.assert_not_awaited()


async def test_el_snapshot_se_envia_despues_de_conectar(make_ws, manager, monkeypatch):
    orden = []
    manager.connect.side_effect = lambda ws: orden.append("connect")
    manager.send.side_effect = lambda ws, msg: orden.append("send")
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: MagicMock())
    ws = make_ws([WebSocketDisconnect()])

    await ws_endpoint(ws)

    assert orden == ["connect", "send"]


# ---------- mensajes 'state' válidos ----------


async def test_mensaje_state_valido_actualiza_screen_state(make_ws):
    ws = make_ws([state_json(Screen.MENU, StateSource.TOUCH), WebSocketDisconnect()])

    await ws_endpoint(ws)

    assert ScreenState.current is Screen.MENU
    assert ScreenState.source is StateSource.TOUCH


async def test_mensaje_state_con_origen_backend_guarda_la_referencia(make_ws):
    raw = state_json(Screen.WELCOME, StateSource.BACKEND, ref="r-7")
    ws = make_ws([raw, WebSocketDisconnect()])

    await ws_endpoint(ws)

    assert ScreenState.current is Screen.WELCOME
    assert ScreenState.ref == "r-7"


async def test_varios_mensajes_state_dejan_el_ultimo(make_ws):
    ws = make_ws(
        [
            state_json(Screen.WELCOME, StateSource.INIT),
            state_json(Screen.MENU, StateSource.TOUCH),
            WebSocketDisconnect(),
        ]
    )

    await ws_endpoint(ws)

    assert ScreenState.current is Screen.MENU
    assert ScreenState.source is StateSource.TOUCH


async def test_mensaje_state_valido_no_genera_respuesta(make_ws, manager):
    ws = make_ws([state_json(), WebSocketDisconnect()])

    await ws_endpoint(ws)

    manager.send.assert_not_awaited()


async def test_imprime_el_mensaje_recibido(make_ws, capsys):
    raw = state_json()
    ws = make_ws([raw, WebSocketDisconnect()])

    await ws_endpoint(ws)

    assert f"[WS] recibido: {raw}" in capsys.readouterr().out


# ---------- mensajes inválidos ----------


@pytest.mark.parametrize(
    "raw",
    [
        "hola",  # no es JSON
        "{}",  # faltan campos
        '{"type":"otro","payload":{"screen":"menu","source":"touch"}}',  # tipo desconocido
        '{"type":"state","payload":{"screen":"no_existe","source":"touch"}}',  # pantalla inválida
        '{"type":"state","payload":{"screen":"menu","source":"touch","x":1}}',  # campo extra
    ],
)
async def test_mensaje_invalido_responde_con_un_error_y_no_cambia_el_estado(
    make_ws, manager, raw
):
    ws = make_ws([raw, WebSocketDisconnect()])

    await ws_endpoint(ws)

    errores = mensajes_de_error(manager)
    assert len(errores) == 1
    assert errores[0].type == "error"
    assert errores[0].payload.detail
    assert ScreenState.current is None


async def test_el_error_se_envia_al_mismo_cliente(make_ws, manager):
    ws = make_ws(["hola", WebSocketDisconnect()])

    await ws_endpoint(ws)

    assert manager.send.await_args.args[0] is ws


async def test_el_detalle_del_error_incluye_ubicacion_y_mensaje(make_ws, manager):
    raw = '{"type":"state","payload":{"screen":"no_existe","source":"touch"}}'
    ws = make_ws([raw, WebSocketDisconnect()])

    await ws_endpoint(ws)

    detalle = mensajes_de_error(manager)[0].payload.detail
    assert detalle[0]["loc"] == ["state", "payload", "screen"]
    assert isinstance(detalle[0]["msg"], str) and detalle[0]["msg"]


async def test_backend_sin_ref_responde_con_el_motivo(make_ws, manager):
    raw = '{"type":"state","payload":{"screen":"menu","source":"backend"}}'
    ws = make_ws([raw, WebSocketDisconnect()])

    await ws_endpoint(ws)

    detalle = mensajes_de_error(manager)[0].payload.detail
    assert "ref es obligatorio" in detalle[0]["msg"]
    assert ScreenState.current is None


async def test_touch_con_ref_responde_con_el_motivo(make_ws, manager):
    raw = '{"type":"state","payload":{"screen":"menu","source":"touch","ref":"x"}}'
    ws = make_ws([raw, WebSocketDisconnect()])

    await ws_endpoint(ws)

    detalle = mensajes_de_error(manager)[0].payload.detail
    assert "ref solo se permite" in detalle[0]["msg"]


async def test_mensaje_invalido_imprime_el_detalle(make_ws, capsys):
    ws = make_ws(["hola", WebSocketDisconnect()])

    await ws_endpoint(ws)

    assert "[WS] Mensaje inválido del front" in capsys.readouterr().out


async def test_tras_un_mensaje_invalido_sigue_procesando_los_siguientes(
    make_ws, manager
):
    ws = make_ws(
        ["hola", state_json(Screen.MENU, StateSource.TOUCH), WebSocketDisconnect()]
    )

    await ws_endpoint(ws)

    assert len(mensajes_de_error(manager)) == 1
    assert ScreenState.current is Screen.MENU


async def test_un_mensaje_valido_despues_de_uno_invalido_no_borra_el_estado_previo(
    make_ws,
):
    ws = make_ws(
        [state_json(Screen.WELCOME, StateSource.INIT), "hola", WebSocketDisconnect()]
    )

    await ws_endpoint(ws)

    assert ScreenState.current is Screen.WELCOME  # el mensaje inválido no lo pisa


# ---------- bucle de recepción y limpieza ----------


async def test_sigue_escuchando_hasta_que_el_cliente_se_desconecta(make_ws):
    ws = make_ws(
        [
            state_json(),
            state_json(Screen.WELCOME, StateSource.INIT),
            WebSocketDisconnect(),
        ]
    )

    await ws_endpoint(ws)  # no debe lanzar

    assert ws.receive_text.await_count == 3


async def test_desconexion_normal_limpia_al_cliente(make_ws, manager):
    ws = make_ws([WebSocketDisconnect()])

    await ws_endpoint(ws)

    manager.disconnect.assert_called_once_with(ws)


async def test_error_inesperado_se_propaga_pero_limpia_al_cliente(make_ws, manager):
    ws = make_ws([RuntimeError("falla")])

    with pytest.raises(RuntimeError):
        await ws_endpoint(ws)

    manager.disconnect.assert_called_once_with(ws)


async def test_error_al_enviar_snapshot_tambien_limpia_al_cliente(
    make_ws, manager, monkeypatch
):
    manager.send.side_effect = RuntimeError("socket roto")
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: MagicMock())
    ws = make_ws([WebSocketDisconnect()])

    with pytest.raises(RuntimeError):
        await ws_endpoint(ws)

    manager.disconnect.assert_called_once_with(ws)


async def test_error_al_responder_un_mensaje_invalido_tambien_limpia_al_cliente(
    make_ws, manager
):
    manager.send.side_effect = RuntimeError("socket roto")
    ws = make_ws(["hola"])

    with pytest.raises(RuntimeError):
        await ws_endpoint(ws)

    manager.disconnect.assert_called_once_with(ws)


# ---------- saludo inicial por voz ----------


class Reloj:
    def __init__(self, t=1000.0):
        self.t = t

    def monotonic(self):
        return self.t


@pytest.fixture
def reloj(monkeypatch):
    """Reloj controlable solo para el módulo de endpoints (no toca el del bucle de asyncio)."""
    r = Reloj()
    monkeypatch.setattr(endpoints, "time", r)
    return r


@pytest.fixture
def ws_con_voz():
    ws = MagicMock()
    ws.app.state.speak = MagicMock()
    return ws


def estado(pantalla, origen=StateSource.TOUCH):
    return FrontState(payload=StatePayload(screen=pantalla, source=origen))


async def test_el_primer_estado_welcome_dice_el_saludo_inicial(ws_con_voz, reloj):
    await handle_client_message(estado(Screen.WELCOME, StateSource.INIT), ws_con_voz)

    ws_con_voz.app.state.speak.assert_called_once_with(VoiceEvent.INITIAL_WELCOME)


async def test_volver_a_welcome_desde_otra_pantalla_dice_el_saludo(ws_con_voz, reloj):
    await handle_client_message(estado(Screen.MENU), ws_con_voz)

    await handle_client_message(estado(Screen.WELCOME), ws_con_voz)

    ws_con_voz.app.state.speak.assert_called_once_with(VoiceEvent.INITIAL_WELCOME)


async def test_seguir_en_welcome_no_repite_el_saludo(ws_con_voz, reloj):
    await handle_client_message(estado(Screen.WELCOME, StateSource.INIT), ws_con_voz)
    reloj.t += 60  # aunque el cooldown ya haya pasado

    await handle_client_message(estado(Screen.WELCOME, StateSource.INIT), ws_con_voz)

    ws_con_voz.app.state.speak.assert_called_once()


@pytest.mark.parametrize("pantalla", [p for p in Screen if p is not Screen.WELCOME])
async def test_las_otras_pantallas_no_dicen_el_saludo(ws_con_voz, reloj, pantalla):
    await handle_client_message(estado(pantalla), ws_con_voz)

    ws_con_voz.app.state.speak.assert_not_called()


async def test_el_saludo_respeta_el_cooldown_de_10_segundos(ws_con_voz, reloj):
    speak = ws_con_voz.app.state.speak

    await handle_client_message(estado(Screen.WELCOME), ws_con_voz)  # t=1000
    assert speak.call_count == 1

    reloj.t = 1005  # pasó menos del cooldown
    await handle_client_message(estado(Screen.MENU), ws_con_voz)
    await handle_client_message(estado(Screen.WELCOME), ws_con_voz)
    assert speak.call_count == 1

    reloj.t = 1010  # justo el cooldown: ya puede volver a saludar
    await handle_client_message(estado(Screen.MENU), ws_con_voz)
    await handle_client_message(estado(Screen.WELCOME), ws_con_voz)
    assert speak.call_count == 2


async def test_el_cooldown_solo_se_consume_cuando_se_saluda(ws_con_voz, reloj):
    speak = ws_con_voz.app.state.speak
    await handle_client_message(estado(Screen.WELCOME), ws_con_voz)  # saluda en t=1000
    inicio = endpoints._last_welcome_speak

    reloj.t = 1003
    await handle_client_message(estado(Screen.MENU), ws_con_voz)  # no saluda
    await handle_client_message(estado(Screen.WELCOME), ws_con_voz)  # cooldown activo

    assert speak.call_count == 1
    assert endpoints._last_welcome_speak == inicio == 1000.0


async def test_la_pantalla_se_actualiza_aunque_se_hable(ws_con_voz, reloj):
    await handle_client_message(estado(Screen.WELCOME), ws_con_voz)

    assert ScreenState.current is Screen.WELCOME


async def test_sin_speak_en_el_estado_de_la_app_no_falla_ni_consume_el_cooldown(reloj):
    ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    await handle_client_message(estado(Screen.WELCOME), ws)  # no debe lanzar

    assert ScreenState.current is Screen.WELCOME
    assert endpoints._last_welcome_speak == -10.0


async def test_el_saludo_se_dispara_al_recibir_el_estado_por_el_websocket(
    make_ws, reloj
):
    ws = make_ws([state_json(Screen.WELCOME, StateSource.INIT), WebSocketDisconnect()])
    ws.app.state.speak = MagicMock()

    await ws_endpoint(ws)

    ws.app.state.speak.assert_called_once_with(VoiceEvent.INITIAL_WELCOME)


async def test_un_mensaje_invalido_no_dispara_el_saludo(make_ws, reloj):
    ws = make_ws(["hola", WebSocketDisconnect()])
    ws.app.state.speak = MagicMock()

    await ws_endpoint(ws)

    ws.app.state.speak.assert_not_called()
