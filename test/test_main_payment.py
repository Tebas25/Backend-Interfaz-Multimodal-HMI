import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app import main
from app.core.core_constants import COBOT_ID, DEFAULT_EVENT_ID
from app.main import app, lifespan
from app.schemas.ws_messages import PaymentResult
from app.services.payment_service import PaymentService, PaymentSession, PaymentStatus
from app.schemas.transactions_dto import TransactionsDTO


def _servicio_con_close():
    servicio = MagicMock()
    servicio.close = AsyncMock()
    return servicio


@pytest.fixture
def dobles(monkeypatch):
    watcher = MagicMock(name="watcher")
    watcher.stop = AsyncMock()
    watcher.items_activos = []
    listener = MagicMock(name="listener")
    listener.start = AsyncMock(return_value=True)
    listener.stop = AsyncMock()
    publisher = MagicMock(name="publisher")
    publisher.stop = AsyncMock()
    tx_publisher = MagicMock(name="tx_publisher")
    tx_publisher.stop = AsyncMock()
    order_service = MagicMock(name="order_service")
    order_service.stop = AsyncMock()

    monkeypatch.setattr(
        main, "Publisher", MagicMock(side_effect=[publisher, tx_publisher])
    )
    monkeypatch.setattr(main, "CatalogWatcher", MagicMock(return_value=watcher))
    monkeypatch.setattr(
        main, "CommandListenerService", MagicMock(return_value=listener)
    )
    monkeypatch.setattr(main, "OrderService", MagicMock(return_value=order_service))
    monkeypatch.setattr(main, "modbus_connection", MagicMock())
    monkeypatch.setattr(main.settings, "PUBLIC_BASE_URL", "http://10.0.0.5:9000/")
    monkeypatch.setattr(main.settings, "PAYMENT_TTL_SECONDS", 90)
    order_service.request_order.return_value = None  # pedido aceptado
    return {
        "order_service": order_service,
        "publisher": publisher,
        "tx_publisher": tx_publisher,
    }


@pytest.fixture
def sesion(make_item):
    def _crear(estado):
        item = make_item(nombre="Mojito", precio="5.50", codigo=3)
        return PaymentSession(
            drink=item,
            price=item.precio_item,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            id="tok-123456",
            status=estado,
        )

    return _crear


# ---------- rutas ----------


def test_la_app_expone_las_rutas_de_pago():
    rutas = app.openapi()["paths"]

    assert set(rutas["/pay/{payment_id}"]) == {"get"}
    assert set(rutas["/pay/{payment_id}/approve"]) == {"post"}
    assert set(rutas["/pay/{payment_id}/reject"]) == {"post"}


# ---------- lifespan ----------


async def test_lifespan_deja_el_servicio_de_pagos_en_app_state(dobles):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        assert isinstance(app_falsa.state.payment_service, PaymentService)


async def test_el_servicio_de_pagos_usa_la_url_publica_y_el_ttl_de_la_configuracion(
    dobles, make_item
):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        pagos = app_falsa.state.payment_service
        s = pagos.start(make_item())
        try:

            assert pagos.pay_url(s) == f"http://10.0.0.5:9000/pay/{s.id}"
            assert s.expires_at - s.created_at == pytest.approx(
                timedelta(seconds=90), abs=timedelta(seconds=1)
            )
        finally:
            pagos.close()


async def test_lifespan_cierra_el_servicio_de_pagos_al_apagar(dobles, make_item):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        s = app_falsa.state.payment_service.start(make_item())

    try:
        await asyncio.sleep(0)
        assert s.timer.cancelled()
    finally:
        s.timer.cancel()


# ---------- on_payment_result ----------


@pytest.fixture
async def on_result(dobles):
    app_falsa = FastAPI()
    async with lifespan(app_falsa):
        app_falsa.state.ws_manager.broadcast = AsyncMock()
        yield app_falsa.state.payment_service._on_result, app_falsa.state.ws_manager


@pytest.mark.parametrize(
    "estado",
    [PaymentStatus.APPROVED, PaymentStatus.REJECTED, PaymentStatus.EXPIRED],
)
async def test_el_resultado_se_difunde_a_los_clientes(on_result, sesion, estado):
    callback, manager = on_result

    await callback(sesion(estado))

    manager.broadcast.assert_awaited_once()
    msg = manager.broadcast.await_args.args[0]
    assert isinstance(msg, PaymentResult)
    assert msg.payload.payment_id == "tok-123456"
    assert msg.payload.status == estado.value
    assert msg.payload.reason is None


async def test_un_pago_aprobado_imprime_la_bebida_y_su_codigo_modbus(
    on_result, sesion, capsys
):
    callback, _ = on_result

    await callback(sesion(PaymentStatus.APPROVED))

    assert "[Pago] APROBADO: Mojito (modbus=3)" in capsys.readouterr().out


@pytest.mark.parametrize("estado", [PaymentStatus.REJECTED, PaymentStatus.EXPIRED])
async def test_un_pago_no_aprobado_no_imprime_el_aviso_de_aprobacion(
    on_result, sesion, capsys, estado
):
    callback, _ = on_result

    await callback(sesion(estado))

    assert "APROBADO" not in capsys.readouterr().out


async def test_un_pago_aprobado_publica_la_transaccion(on_result, sesion, dobles):
    callback, _ = on_result

    await callback(sesion(PaymentStatus.APPROVED))

    dobles["tx_publisher"].publish.assert_called_once()
    tx = dobles["tx_publisher"].publish.call_args.args[0]
    assert isinstance(tx, TransactionsDTO)
    assert tx.cobot_id == COBOT_ID
    assert tx.evento_id == DEFAULT_EVENT_ID
    assert tx.item == "Mojito"
    assert tx.ingreso == 5.5


@pytest.mark.parametrize("estado", [PaymentStatus.REJECTED, PaymentStatus.EXPIRED])
async def test_un_pago_no_aprobado_no_publica_transaccion(
    on_result, sesion, dobles, estado
):
    callback, _ = on_result

    await callback(sesion(estado))

    dobles["tx_publisher"].publish.assert_not_called()


async def test_la_transaccion_se_publica_aunque_el_cobot_no_arranque(
    on_result, sesion, dobles
):
    dobles["order_service"].request_order.return_value = "Ya hay un pedido en curso"
    callback, _ = on_result

    await callback(sesion(PaymentStatus.APPROVED))

    dobles["tx_publisher"].publish.assert_called_once()


async def test_un_fallo_al_publicar_no_bloquea_el_pedido(on_result, sesion, dobles):
    dobles["tx_publisher"].publish.side_effect = RuntimeError("cola rota")
    callback, _ = on_result

    await callback(sesion(PaymentStatus.APPROVED))

    dobles["order_service"].request_order.assert_called_once_with("Mojito")


async def test_una_transaccion_invalida_no_bloquea_el_pedido(
    on_result, dobles, make_item
):
    # "Ab" incumple item.min_length=3: el DTO falla al construirse
    item = make_item(nombre="Ab", precio="5.50", codigo=3)
    sesion_corta = PaymentSession(
        drink=item,
        price=item.precio_item,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        id="tok-corto",
        status=PaymentStatus.APPROVED,
    )
    callback, _ = on_result

    await callback(sesion_corta)

    dobles["tx_publisher"].publish.assert_not_called()
    dobles["order_service"].request_order.assert_called_once_with("Ab")
