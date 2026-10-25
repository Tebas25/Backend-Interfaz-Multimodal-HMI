"""Pruebas unitarias del endpoint websocket /ws.

Se invoca la función `ws_endpoint` directamente con un WebSocket falso y un
ConnectionManager/watcher falsos: solo se verifica la lógica del endpoint.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api import endpoints
from app.api.endpoints import ws_endpoint, ws_router


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


@pytest.fixture
def make_ws(manager, watcher):
    def _make(receive_side_effect):
        ws = MagicMock()
        ws.app.state.ws_manager = manager
        ws.app.state.catalog_watcher = watcher
        ws.receive_text = AsyncMock(side_effect=receive_side_effect)
        return ws
    return _make


# ---------- router ----------

def test_ws_router_registra_la_ruta_ws():
    rutas = {r.path for r in ws_router.routes}

    assert "/ws" in rutas


# ---------- conexión ----------

async def test_conecta_al_cliente_con_el_manager(make_ws, manager, monkeypatch):
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: None)
    ws = make_ws([WebSocketDisconnect()])

    await ws_endpoint(ws)

    manager.connect.assert_awaited_once_with(ws)


async def test_imprime_el_handshake(make_ws, monkeypatch, capsys):
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: None)
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


async def test_no_envia_snapshot_si_no_hay_catalogo(make_ws, manager, monkeypatch):
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: None)
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


# ---------- bucle de recepción ----------

async def test_sigue_escuchando_hasta_que_el_cliente_se_desconecta(
    make_ws, monkeypatch
):
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: None)
    ws = make_ws(["hola", "otro", WebSocketDisconnect()])

    await ws_endpoint(ws)  # no debe lanzar

    assert ws.receive_text.await_count == 3


async def test_desconexion_normal_limpia_al_cliente(make_ws, manager, monkeypatch):
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: None)
    ws = make_ws([WebSocketDisconnect()])

    await ws_endpoint(ws)

    manager.disconnect.assert_called_once_with(ws)


async def test_error_inesperado_se_propaga_pero_limpia_al_cliente(
    make_ws, manager, monkeypatch
):
    monkeypatch.setattr(endpoints, "build_catalog_update", lambda w: None)
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