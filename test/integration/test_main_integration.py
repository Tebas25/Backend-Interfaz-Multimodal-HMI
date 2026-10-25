"""Integración de la app completa (lifespan real).

Se usan el watcher, el ConnectionManager y el endpoint /ws reales. Solo se
reemplaza HttpRequestService por una versión falsa que no sale a la red.
"""
import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models.cobot_menu_item import CobotMenuItem
from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.schemas.ws_messages import CatalogUpdate

CATALOGO = CobotCatalogResponse(
    items=[
        CobotMenuItem(
            nombre_item="Mojito", precio_item=Decimal("5.50"), estado=True,
            ingredientes="Ron, menta", codigo_modbus="0x01",
        ),
        CobotMenuItem(
            nombre_item="Margarita", precio_item=Decimal("6.00"), estado=False,
            ingredientes="Tequila", codigo_modbus="0x02",
        ),
    ],
    total=2,
)


class ServicioFalso:
    """Imita a HttpRequestService: consulta de fecha o descarga de catálogo."""

    creados: list["ServicioFalso"] = []

    def __init__(self, url, authkey=None):
        self.url = url
        self.authkey = authkey
        self.cerrado = False
        ServicioFalso.creados.append(self)

    async def get(self, tipo, **kwargs):
        if "check-update" in self.url:
            return "2026-10-22T10:00:00"
        return CATALOGO

    async def close(self):
        self.cerrado = True


@pytest.fixture
def servicios_falsos(monkeypatch):
    ServicioFalso.creados = []
    monkeypatch.setattr(main, "HttpRequestService", ServicioFalso)
    return ServicioFalso.creados


def esperar(condicion, timeout=3.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def test_la_app_arranca_descarga_el_catalogo_y_lo_entrega_por_websocket(servicios_falsos):
    with TestClient(main.app) as client:
        assert esperar(lambda: main.app.state.catalog_watcher.catalogo is not None)

        with client.websocket_connect("/ws") as ws:
            msg = CatalogUpdate.model_validate(ws.receive_json())

    assert msg.payload.ultima_actualizacion == "2026-10-22T10:00:00"
    assert [i.nombre_item for i in msg.payload.catalogo.items] == ["Mojito"]


def test_el_watcher_hace_broadcast_a_los_clientes_ya_conectados(servicios_falsos):
    with TestClient(main.app) as client:
        manager = main.app.state.ws_manager
        watcher = main.app.state.catalog_watcher
        # Se conecta antes de que el watcher complete su primera descarga
        # (si ya terminó, recibe el snapshot; en ambos casos llega el catálogo).
        with client.websocket_connect("/ws") as ws:
            assert esperar(lambda: len(manager._clients) == 1)
            msg = CatalogUpdate.model_validate(ws.receive_json())
            assert watcher.catalogo is not None

    assert msg.payload.catalogo.total == 1


def test_al_apagar_se_cierran_los_servicios_http(servicios_falsos):
    with TestClient(main.app):
        assert len(servicios_falsos) == 2
        assert not any(s.cerrado for s in servicios_falsos)

    assert all(s.cerrado for s in servicios_falsos)


def test_al_apagar_el_watcher_queda_cancelado(servicios_falsos):
    with TestClient(main.app):
        watcher = main.app.state.catalog_watcher
        tarea = watcher._task
        assert tarea is not None

    assert tarea.done()


def test_los_servicios_usan_la_authkey_configurada(servicios_falsos):
    from app.core.config import settings

    with TestClient(main.app):
        pass

    assert {s.authkey for s in servicios_falsos} == {settings.kong_auth_key}


def test_root_funciona_con_el_lifespan_activo(servicios_falsos):
    with TestClient(main.app) as client:
        assert client.get("/").json()["status"] == "ok"