"""Pruebas de integración del endpoint /ws.

Se usan el router, el ConnectionManager, el CatalogWatcher y los mensajes
reales, con un WebSocket real de Starlette. Solo el microservicio del
catálogo se omite.
"""
import time
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import ws_router
from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.schemas.ws_messages import (
    CatalogUpdate,
    Navigate,
    NavigatePayload,
    Screen,
)
from app.services.catalog_watcher_service import CatalogWatcher
from app.services.connection_manager import ConnectionManager


def esperar(condicion, timeout=2.0):
    """Espera activa breve: el servidor corre en otro hilo/bucle."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def cargar_catalogo(watcher, items, fecha):
    watcher.catalogo = CobotCatalogResponse(items=list(items), total=len(items))
    watcher.ultima_actualizacion = fecha


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(ws_router)
    app.state.ws_manager = ConnectionManager()
    app.state.catalog_watcher = CatalogWatcher(AsyncMock(), AsyncMock())
    return app


@pytest.fixture
def navegar_al_menu():
    return Navigate(payload=NavigatePayload(screen=Screen.MENU))


# ---------- snapshot al conectar ----------

def test_al_conectar_recibe_el_catalogo_actual_solo_con_activos(app, make_item):
    cargar_catalogo(
        app.state.catalog_watcher,
        [
            make_item(nombre="Mojito", estado=True),
            make_item(nombre="Margarita", estado=False),
        ],
        "f1",
    )

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        msg = CatalogUpdate.model_validate(ws.receive_json())

    assert msg.payload.ultima_actualizacion == "f1"
    assert [i.nombre_item for i in msg.payload.catalogo.items] == ["Mojito"]
    assert msg.payload.catalogo.total == 1


def test_sin_catalogo_descargado_no_envia_snapshot(app, navegar_al_menu):
    manager = app.state.ws_manager

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert esperar(lambda: len(manager._clients) == 1)
        client.portal.call(manager.broadcast, navegar_al_menu)

        # Lo primero que llega es el broadcast, no un snapshot
        recibido = ws.receive_json()

    assert recibido["type"] == "navigate"
    assert recibido["id"] == navegar_al_menu.id


def test_reconexion_recibe_el_catalogo_actualizado(app, make_item):
    watcher = app.state.catalog_watcher
    cargar_catalogo(watcher, [make_item(nombre="Mojito")], "f1")

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            primero = ws.receive_json()

        # El catálogo cambia mientras el cliente estaba desconectado
        cargar_catalogo(watcher, [make_item(nombre="Daiquiri")], "f2")

        with client.websocket_connect("/ws") as ws:
            segundo = ws.receive_json()

    assert primero["payload"]["ultima_actualizacion"] == "f1"
    assert segundo["payload"]["ultima_actualizacion"] == "f2"
    assert segundo["payload"]["catalogo"]["items"][0]["nombre_item"] == "Daiquiri"


# ---------- registro de clientes ----------

def test_cliente_se_registra_al_conectar_y_se_elimina_al_desconectar(app):
    manager = app.state.ws_manager

    with TestClient(app) as client:
        with client.websocket_connect("/ws"):
            assert esperar(lambda: len(manager._clients) == 1)

        assert esperar(lambda: len(manager._clients) == 0)


# ---------- mensajes ----------

def test_broadcast_llega_a_varios_clientes_conectados(app, navegar_al_menu):
    manager = app.state.ws_manager

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws1, client.websocket_connect("/ws") as ws2:
            assert esperar(lambda: len(manager._clients) == 2)
            client.portal.call(manager.broadcast, navegar_al_menu)

            r1 = ws1.receive_json()
            r2 = ws2.receive_json()

    assert r1["id"] == r2["id"] == navegar_al_menu.id


def test_los_mensajes_del_cliente_no_cierran_la_conexion(app, navegar_al_menu):
    manager = app.state.ws_manager

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert esperar(lambda: len(manager._clients) == 1)
        ws.send_text("hola")  # de momento el backend los ignora
        client.portal.call(manager.broadcast, navegar_al_menu)

        recibido = ws.receive_json()

    assert recibido["id"] == navegar_al_menu.id