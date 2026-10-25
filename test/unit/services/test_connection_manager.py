"""Pruebas unitarias de ConnectionManager con WebSockets falsos."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from app.services.connection_manager import ConnectionManager


class Ping(BaseModel):
    texto: str = "hola"


def make_ws(send_side_effect=None):
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock(side_effect=send_side_effect)
    return ws


@pytest.fixture
def manager():
    return ConnectionManager()


# ---------- connect / disconnect ----------

async def test_connect_acepta_y_registra_el_cliente(manager):
    ws = make_ws()

    await manager.connect(ws)

    ws.accept.assert_awaited_once()
    assert ws in manager._clients


async def test_disconnect_elimina_el_cliente(manager):
    ws = make_ws()
    await manager.connect(ws)

    manager.disconnect(ws)

    assert ws not in manager._clients


def test_disconnect_de_cliente_desconocido_no_falla(manager):
    manager.disconnect(make_ws())  # no debe lanzar


# ---------- send ----------

async def test_send_a_cliente_no_conectado_devuelve_false(manager):
    ws = make_ws()

    assert await manager.send(ws, Ping()) is False
    ws.send_text.assert_not_awaited()


async def test_send_envia_el_mensaje_como_json(manager):
    ws = make_ws()
    await manager.connect(ws)

    resultado = await manager.send(ws, Ping(texto="menu"))

    assert resultado is True
    ws.send_text.assert_awaited_once_with('{"texto":"menu"}')


async def test_send_con_error_descarta_al_cliente(manager, capsys):
    ws = make_ws(send_side_effect=RuntimeError("conexión rota"))
    await manager.connect(ws)

    resultado = await manager.send(ws, Ping())

    assert resultado is False
    assert ws not in manager._clients
    assert "[WS] Error al enviar" in capsys.readouterr().out


async def test_send_con_timeout_descarta_al_cliente(manager, monkeypatch):
    async def colgado(_):
        await asyncio.sleep(10)

    ws = make_ws(send_side_effect=colgado)
    await manager.connect(ws)

    # El timeout real es de 5 s; se acorta para que la prueba sea rápida.
    wait_for_real = asyncio.wait_for
    monkeypatch.setattr(
        asyncio, "wait_for", lambda coro, timeout: wait_for_real(coro, 0.01)
    )

    resultado = await manager.send(ws, Ping())

    assert resultado is False
    assert ws not in manager._clients


async def test_send_serializa_envios_al_mismo_cliente(manager):
    """El lock por conexión evita que dos envíos se solapen."""
    activos = 0
    max_activos = 0

    async def send_text(_):
        nonlocal activos, max_activos
        activos += 1
        max_activos = max(max_activos, activos)
        await asyncio.sleep(0.01)
        activos -= 1

    ws = make_ws(send_side_effect=send_text)
    await manager.connect(ws)

    await asyncio.gather(*(manager.send(ws, Ping()) for _ in range(5)))

    assert max_activos == 1
    assert ws.send_text.await_count == 5


# ---------- broadcast ----------

async def test_broadcast_sin_clientes_no_hace_nada(manager):
    await manager.broadcast(Ping())  # no debe lanzar


async def test_broadcast_envia_a_todos_los_clientes(manager):
    ws1, ws2, ws3 = make_ws(), make_ws(), make_ws()
    for ws in (ws1, ws2, ws3):
        await manager.connect(ws)

    await manager.broadcast(Ping(texto="a todos"))

    for ws in (ws1, ws2, ws3):
        ws.send_text.assert_awaited_once_with('{"texto":"a todos"}')


async def test_broadcast_un_cliente_roto_no_afecta_a_los_demas(manager):
    sano = make_ws()
    roto = make_ws(send_side_effect=RuntimeError("caído"))
    await manager.connect(sano)
    await manager.connect(roto)

    await manager.broadcast(Ping())

    sano.send_text.assert_awaited_once()
    assert sano in manager._clients
    assert roto not in manager._clients