import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import ws_router
from app.schemas.events_dto import EventsDTO, TipoEvento
from app.schemas.ws_messages import (
    FrontState,
    OrderPayload,
    OrderRequest,
    Screen,
    StatePayload,
    StateSource,
)
from app.services.connection_manager import ConnectionManager
from app.services.order_service import ORDER_SCREEN, OrderService

BEBIDA = SimpleNamespace(nombre_item="Cuba Libre", codigo_modbus=3)
SIN_CODIGO = SimpleNamespace(nombre_item="Agua", codigo_modbus=None)


def esperar(condicion, timeout=2.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def evento(evento_id: str, tipo=TipoEvento.INFO_ROBOT) -> EventsDTO:
    return EventsDTO(
        cobot_id="CBT000T", evento_id=evento_id, tipo_evento=tipo, descripcion="d"
    )


def state_json(screen=ORDER_SCREEN) -> str:
    return FrontState(
        payload=StatePayload(screen=screen, source=StateSource.TOUCH)
    ).model_dump_json()


def order_json(nombre="Cuba Libre") -> str:
    return OrderRequest(payload=OrderPayload(nombre_item=nombre)).model_dump_json()


def construir_app(prepare_drink):
    """App real (endpoint + ConnectionManager + OrderService); solo el cobot y la
    analítica son dobles, así que no hay red ni Modbus."""
    app = FastAPI()
    app.include_router(ws_router)
    manager = ConnectionManager()
    watcher = SimpleNamespace(
        catalogo=None, ultima_actualizacion=None, items_activos=[BEBIDA, SIN_CODIGO]
    )
    publisher = MagicMock()
    cobot = SimpleNamespace(prepare_drink=prepare_drink)
    app.state.ws_manager = manager
    app.state.catalog_watcher = watcher
    app.state.order_service = OrderService(manager, watcher, cobot, publisher)
    return app, manager, publisher


async def pedido_completo(codigo):
    yield evento("101")
    yield evento("102")
    yield evento("200")


def test_un_pedido_llega_al_front_en_orden_y_termina_en_bienvenida():
    app, _, publisher = construir_app(pedido_completo)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(state_json(ORDER_SCREEN))
        ws.send_text(order_json())
        mensajes = [ws.receive_json() for _ in range(4)]

    assert [m["type"] for m in mensajes] == ["cobot_status"] * 3 + ["navigate"]
    assert [m["payload"]["codigo"] for m in mensajes[:3]] == [101, 102, 200]
    assert mensajes[3]["payload"]["screen"] == "welcome"
    enviados = [c.args[0].evento_id for c in publisher.publish.call_args_list]
    assert enviados == ["101", "102", "200"]


def test_el_codigo_del_catalogo_es_el_que_recibe_el_cobot():
    recibido = []

    async def registrando(codigo):
        recibido.append(codigo)
        yield evento("200")

    app, _, _ = construir_app(registrando)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(state_json(ORDER_SCREEN))
        ws.send_text(order_json("Cuba Libre"))
        ws.receive_json()  # cobot_status
        ws.receive_json()  # navigate

    assert recibido == [3]


def test_un_evento_de_sistema_llega_con_codigo_menos_uno():
    async def con_timeout(codigo):
        yield evento("TIMEOUT", TipoEvento.ERROR_SISTEMA)

    app, _, _ = construir_app(con_timeout)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(state_json(ORDER_SCREEN))
        ws.send_text(order_json())
        estado = ws.receive_json()
        final = ws.receive_json()

    assert estado["payload"]["codigo"] == -1
    assert estado["payload"]["tipo_evento"] == "ErrorSistema"
    assert final["type"] == "navigate"


def test_todos_los_clientes_reciben_el_estado_del_pedido():
    app, manager, _ = construir_app(pedido_completo)

    with TestClient(app) as client:
        with (
            client.websocket_connect("/ws") as ws1,
            client.websocket_connect("/ws") as ws2,
        ):
            assert esperar(lambda: len(manager._clients) == 2)
            ws1.send_text(state_json(ORDER_SCREEN))
            ws1.send_text(order_json())
            r1 = [ws1.receive_json()["type"] for _ in range(4)]
            r2 = [ws2.receive_json()["type"] for _ in range(4)]

    assert r1 == r2 == ["cobot_status"] * 3 + ["navigate"]


def test_un_segundo_pedido_en_curso_recibe_un_error():
    gate = threading.Event()

    async def lento(codigo):
        yield evento("101")
        await asyncio.get_running_loop().run_in_executor(None, gate.wait, 5)
        yield evento("200")

    app, _, _ = construir_app(lento)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(state_json(ORDER_SCREEN))
        ws.send_text(order_json())
        assert ws.receive_json()["payload"]["codigo"] == 101

        ws.send_text(order_json())
        rechazo = ws.receive_json()
        gate.set()
        resto = [ws.receive_json()["type"] for _ in range(2)]

    assert rechazo["type"] == "error"
    assert rechazo["payload"]["detail"] == [
        {"loc": ["order"], "msg": "Ya hay un pedido en curso"}
    ]
    assert resto == ["cobot_status", "navigate"]


def test_un_pedido_fuera_de_la_pantalla_de_pago_recibe_un_error():
    arrancado = []

    async def registrando(codigo):
        arrancado.append(codigo)
        yield evento("200")

    app, _, _ = construir_app(registrando)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(state_json(Screen.WELCOME))
        ws.send_text(order_json())
        respuesta = ws.receive_json()

    assert respuesta["type"] == "error"
    assert "pantalla de pago" in respuesta["payload"]["detail"][0]["msg"]
    assert arrancado == []


def test_pedir_desde_el_menu_antes_de_pagar_no_arranca_el_cobot():
    arrancado = []

    async def registrando(codigo):
        arrancado.append(codigo)
        yield evento("200")

    app, _, _ = construir_app(registrando)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(state_json(Screen.MENU))
        ws.send_text(order_json())
        respuesta = ws.receive_json()

    assert respuesta["type"] == "error"
    assert arrancado == []


def test_bebidas_invalidas_reciben_un_error_y_no_arrancan_el_cobot():
    arrancado = []

    async def registrando(codigo):
        arrancado.append(codigo)
        yield evento("200")

    app, _, _ = construir_app(registrando)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text(state_json(ORDER_SCREEN))
        ws.send_text(order_json("No existe"))
        inexistente = ws.receive_json()
        ws.send_text(order_json("Agua"))
        sin_codigo = ws.receive_json()

    assert inexistente["payload"]["detail"][0]["msg"] == "Bebida no disponible"
    assert "código" in sin_codigo["payload"]["detail"][0]["msg"]
    assert arrancado == []
