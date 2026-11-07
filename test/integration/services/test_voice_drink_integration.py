import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models.cobot_menu_item import CobotMenuItem
from app.schemas.ws_messages import (
    CloseIngredients,
    FrontState,
    Navigate,
    NavigatePayload,
    Screen,
    SelectDrink,
    ShowIngredients,
    StatePayload,
    StateSource,
)
from app.services.command_listener_service import CommandListenerService
from app.services.screen_state import ScreenState


def bebida(nombre: str) -> CobotMenuItem:
    return CobotMenuItem(
        nombre_item=nombre,
        ingredientes="Ron, menta",
        imagen=None,
        codigo_modbus=1,
        estado=True,
        precio_item=Decimal("5.50"),
    )


class ServicioHttpInerte:
    def __init__(self, url, authkey=None):
        self.url = url

    async def get(self, tipo, **kwargs):
        raise RuntimeError("sin red en las pruebas")

    async def close(self):
        pass


class WatcherConBebidas:

    catalogo = None
    ultima_actualizacion = None
    items_activos: list = []

    def __init__(self, *args, **kwargs):
        WatcherConBebidas.items_activos = [bebida("Mojito"), bebida("Piña colada")]

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


def estado(pantalla: Screen, origen=StateSource.TOUCH, ref=None) -> str:
    return FrontState(
        payload=StatePayload(screen=pantalla, source=origen, ref=ref)
    ).model_dump_json()


@pytest.fixture(autouse=True)
def app_sin_red(monkeypatch):
    monkeypatch.setattr(main, "HttpRequestService", ServicioHttpInerte)
    monkeypatch.setattr(main, "CatalogWatcher", WatcherConBebidas)
    for nombre in ("Publisher", "OrderService"):
        doble = MagicMock()
        doble.return_value.stop = AsyncMock()
        monkeypatch.setattr(main, nombre, doble)


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


def en_menu(client, ws):
    ws.send_text(estado(Screen.MENU))
    assert esperar(lambda: ScreenState.current is Screen.MENU)


def test_nombrar_una_bebida_en_el_menu_envia_select_drink(microfono_falso, procesados):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        en_menu(client, ws)

        microfono_falso.hablar("a1", "Rony, quiero un mojito")
        mensaje = ws.receive_json()

    assert mensaje["type"] == "select_drink"
    assert mensaje["payload"] == {"name": "Mojito"}


def test_el_nombre_enviado_es_el_del_catalogo_con_tildes(microfono_falso, procesados):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        en_menu(client, ws)

        microfono_falso.hablar("a1", "Rony dame una piña colada")
        mensaje = ws.receive_json()

    assert mensaje["payload"] == {"name": "Piña colada"}


def test_pedir_los_ingredientes_envia_show_ingredients(microfono_falso, procesados):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        en_menu(client, ws)

        microfono_falso.hablar("a1", "Rony, ¿qué ingredientes tiene el mojito?")
        mensaje = ws.receive_json()

    assert mensaje["type"] == "show_ingredients"
    assert mensaje["payload"] == {"name": "Mojito"}


def test_cerrar_los_ingredientes_envia_close_ingredients(microfono_falso, procesados):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        en_menu(client, ws)

        microfono_falso.hablar("a1", "Rony, cierra eso")
        mensaje = ws.receive_json()

    assert mensaje["type"] == "close_ingredients"
    assert mensaje["payload"] == {}


def test_los_mensajes_de_voz_son_validos_para_el_contrato(microfono_falso, procesados):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        en_menu(client, ws)

        microfono_falso.hablar("a1", "Rony un mojito")
        seleccion = SelectDrink.model_validate(ws.receive_json())
        microfono_falso.hablar("a2", "Rony que lleva el mojito")
        ingredientes = ShowIngredients.model_validate(ws.receive_json())
        microfono_falso.hablar("a3", "Rony volver")
        cierre = CloseIngredients.model_validate(ws.receive_json())

    assert seleccion.payload.name == ingredientes.payload.name == "Mojito"
    assert len({seleccion.id, ingredientes.id, cierre.id}) == 3


def test_la_orden_de_bebida_llega_a_todos_los_clientes(microfono_falso, procesados):
    with TestClient(main.app) as client:
        with (
            client.websocket_connect("/ws") as ws1,
            client.websocket_connect("/ws") as ws2,
        ):
            en_menu(client, ws1)

            microfono_falso.hablar("a1", "Rony un mojito")
            m1, m2 = ws1.receive_json(), ws2.receive_json()

    assert m1["id"] == m2["id"]
    assert m1["type"] == "select_drink"


# ---------- recorrido completo ----------


def test_recorrido_completo_de_bienvenida_a_ver_ingredientes_y_elegir(
    microfono_falso, procesados
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)

        microfono_falso.hablar("a1", "Rony quiero tomar algo")
        assert ws.receive_json()["type"] == "navigate"

        ws.send_text(estado(Screen.MENU, StateSource.BACKEND, ref="voz-1"))
        assert esperar(lambda: ScreenState.current is Screen.MENU)

        microfono_falso.hablar("a2", "Rony ingredientes del mojito")
        primero = ws.receive_json()
        microfono_falso.hablar("a3", "Rony cierra")
        segundo = ws.receive_json()
        microfono_falso.hablar("a4", "Rony quiero la pina colada")
        tercero = ws.receive_json()

    assert [m["type"] for m in (primero, segundo, tercero)] == [
        "show_ingredients",
        "close_ingredients",
        "select_drink",
    ]
    assert tercero["payload"] == {"name": "Piña colada"}


# ---------- lo que NO debe enviarse ----------


def test_una_bebida_dicha_en_bienvenida_no_se_selecciona(microfono_falso, procesados):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.WELCOME, StateSource.INIT))
        assert esperar(lambda: ScreenState.current is Screen.WELCOME)

        microfono_falso.hablar("a1", "Rony quiero un mojito")
        assert esperar(lambda: len(procesados) == 1)
        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        primero = ws.receive_json()

    assert primero["type"] == "navigate"
    assert primero["payload"]["screen"] == "welcome"


@pytest.mark.parametrize(
    "frase",
    [
        "un mojito sin la palabra clave",
        "Rony quiero un tequila",
        "Rony ingredientes",
        "Rony hola",
    ],
)
def test_ordenes_que_no_se_entienden_no_envian_nada(microfono_falso, procesados, frase):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        en_menu(client, ws)

        microfono_falso.hablar("a1", frase)
        assert esperar(lambda: len(procesados) == 1)
        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        primero = ws.receive_json()

    assert primero["type"] == "navigate"


def test_una_bebida_nueva_en_el_catalogo_se_reconoce_sin_reiniciar(
    microfono_falso, procesados
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        en_menu(client, ws)
        microfono_falso.hablar("a1", "Rony quiero un daiquiri")
        assert esperar(lambda: len(procesados) == 1)

        WatcherConBebidas.items_activos.append(bebida("Daiquiri"))
        microfono_falso.hablar("a2", "Rony quiero un daiquiri")
        mensaje = ws.receive_json()

    assert mensaje["type"] == "select_drink"
    assert mensaje["payload"] == {"name": "Daiquiri"}


# ---------- pantalla de pago ----------


def test_el_estado_payment_del_front_es_aceptado_por_el_backend(
    microfono_falso, procesados
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.PAYMENT))
        assert esperar(lambda: ScreenState.current is Screen.PAYMENT)

        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        primero = ws.receive_json()

    assert primero["type"] == "navigate"
    assert ScreenState.current is Screen.PAYMENT


@pytest.mark.parametrize(
    "frase", ["Rony un mojito", "Rony cierra", "Rony quiero tomar algo"]
)
def test_en_la_pantalla_de_pago_la_voz_no_envia_nada(
    microfono_falso, procesados, frase
):
    with TestClient(main.app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(estado(Screen.PAYMENT))
        assert esperar(lambda: ScreenState.current is Screen.PAYMENT)

        microfono_falso.hablar("a1", frase)
        assert esperar(lambda: len(procesados) == 1)
        client.portal.call(main.app.state.ws_manager.broadcast, marcador())
        primero = ws.receive_json()

    assert primero["payload"]["screen"] == "welcome"
