"""Pruebas de integración del flujo de sincronización del catálogo.

Se usan las piezas reales (CatalogWatcher, ConnectionManager, mensajes
pydantic y un WebSocket real de Starlette) y solo se simula el microservicio
del catálogo.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.schemas.ws_messages import CatalogUpdate, build_catalog_update
from app.services.catalog_watcher_service import CatalogWatcher
from app.services.connection_manager import ConnectionManager


@pytest.fixture
def catalogo(make_item):
    items = [
        make_item(nombre="Mojito", estado=True),
        make_item(nombre="Margarita", estado=False),
        make_item(nombre="Daiquiri", estado=True),
    ]
    return CobotCatalogResponse(items=items, total=len(items))


@pytest.fixture
def build_app(catalogo):
    """Construye una app mínima conectando watcher + manager reales."""

    def _build(fechas):
        update_service = AsyncMock()
        update_service.get.side_effect = fechas
        catalog_service = AsyncMock()
        catalog_service.get.return_value = catalogo

        manager = ConnectionManager()
        watcher = CatalogWatcher(update_service, catalog_service)

        async def on_change():
            msg = build_catalog_update(watcher)
            if msg is not None:
                await manager.broadcast(msg)

        watcher._on_change = on_change

        app = FastAPI()

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await manager.connect(ws)
            try:
                # Simula los ciclos del watcher mientras el cliente está conectado
                for _ in fechas:
                    await watcher._tick()
                while True:
                    await ws.receive_text()
            except WebSocketDisconnect:
                manager.disconnect(ws)

        app.state.manager = manager
        app.state.watcher = watcher
        return app

    return _build


def test_cambio_de_catalogo_llega_al_cliente_websocket(build_app):
    app = build_app(["f1"])

    with TestClient(app).websocket_connect("/ws") as ws:
        data = ws.receive_json()

    msg = CatalogUpdate.model_validate(data)
    nombres = [i.nombre_item for i in msg.payload.catalogo.items]
    assert msg.payload.ultima_actualizacion == "f1"
    assert nombres == ["Mojito", "Daiquiri"]  # el inactivo no se envía
    assert msg.payload.catalogo.total == 2


def test_catalogo_sin_cambios_no_vuelve_a_enviarse(build_app):
    app = build_app(["f1", "f1"])  # dos ciclos, misma fecha

    with TestClient(app).websocket_connect("/ws") as ws:
        primero = ws.receive_json()
        # Solo hubo un cambio: el watcher descargó una sola vez
        assert app.state.watcher._catalog_service.get.await_count == 1

    assert primero["type"] == "catalog_update"


def test_un_segundo_cambio_envia_un_segundo_mensaje(build_app):
    app = build_app(["f1", "f2"])

    with TestClient(app).websocket_connect("/ws") as ws:
        m1 = ws.receive_json()
        m2 = ws.receive_json()

    assert m1["payload"]["ultima_actualizacion"] == "f1"
    assert m2["payload"]["ultima_actualizacion"] == "f2"
    assert m1["id"] != m2["id"]


def test_cliente_desconectado_se_elimina_del_manager(build_app):
    app = build_app(["f1"])

    with TestClient(app).websocket_connect("/ws") as ws:
        ws.receive_json()

    assert app.state.manager._clients == {}