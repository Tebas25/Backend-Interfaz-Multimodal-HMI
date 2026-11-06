import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app import main
from app.main import app, lifespan
from app.schemas.ws_messages import PaymentResult
from app.services.payment_service import PaymentService, PaymentSession, PaymentStatus


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
    order_service = MagicMock(name="order_service")
    order_service.stop = AsyncMock()

    monkeypatch.setattr(
        main,
        "HttpRequestService",
        MagicMock(side_effect=lambda *a, **k: _servicio_con_close()),
    )
    monkeypatch.setattr(main, "CatalogWatcher", MagicMock(return_value=watcher))
    monkeypatch.setattr(
        main, "CommandListenerService", MagicMock(return_value=listener)
    )
    monkeypatch.setattr(main, "EventPublisher", MagicMock(return_value=publisher))
    monkeypatch.setattr(main, "OrderService", MagicMock(return_value=order_service))
    monkeypatch.setattr(main, "modbus_connection", MagicMock())
    monkeypatch.setattr(main.settings, "PUBLIC_BASE_URL", "http://10.0.0.5:9000/")
    monkeypatch.setattr(main.settings, "PAYMENT_TTL_SECONDS", 90)
    return {"order_service": order_service}


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