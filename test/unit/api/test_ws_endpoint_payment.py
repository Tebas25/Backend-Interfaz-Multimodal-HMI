from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.endpoints import handle_client_message, start_payment
from app.schemas.ws_messages import (
    CancelPayment,
    CancelPaymentPayload,
    PaymentResult,
    PaymentStarted,
    StartPayment,
    StartPaymentPayload,
)
from app.services.payment_service import PaymentSession

PAY_URL = "http://192.168.0.10:8888/pay/tok-123456"


@pytest.fixture
def ws(make_item):
    ws = MagicMock(name="ws")
    state = ws.app.state
    state.ws_manager.send = AsyncMock()
    state.catalog_watcher.items_activos = [
        make_item(nombre="Mojito", precio="5.50"),
        make_item(nombre="Piña Colada", precio="7"),
    ]
    state.payment_service.pay_url = MagicMock(return_value=PAY_URL)
    state.payment_service.cancel = MagicMock()

    def _start(drink):
        return PaymentSession(
            drink=drink,
            price=drink.precio_item,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=120),
            id="tok-123456",
        )

    state.payment_service.start = MagicMock(side_effect=_start)
    return ws


def enviado(ws):
    return [c.args[1] for c in ws.app.state.ws_manager.send.await_args_list]


def start(nombre):
    return StartPayment(payload=StartPaymentPayload(drink=nombre))


# ---------- start_payment ----------


async def test_start_payment_inicia_el_pago_de_la_bebida_del_catalogo(ws):
    await start_payment("Mojito", ws)

    ws.app.state.payment_service.start.assert_called_once()
    drink = ws.app.state.payment_service.start.call_args.args[0]
    assert drink.nombre_item == "Mojito"


async def test_start_payment_responde_solo_al_cliente_que_lo_pidio(ws):
    await start_payment("Mojito", ws)

    ws.app.state.ws_manager.send.assert_awaited_once()
    assert ws.app.state.ws_manager.send.await_args.args[0] is ws
    ws.app.state.ws_manager.broadcast.assert_not_called()


async def test_start_payment_envia_payment_started_con_los_datos_del_pago(ws):
    await start_payment("Mojito", ws)

    [msg] = enviado(ws)
    assert isinstance(msg, PaymentStarted)
    assert msg.payload.payment_id == "tok-123456"
    assert msg.payload.pay_url == PAY_URL
    assert msg.payload.drink_name == "Mojito"
    assert msg.payload.price == Decimal("5.50")
    ws.app.state.payment_service.pay_url.assert_called_once()


@pytest.mark.parametrize("pedido", ["mojito", "MOJITO", "MoJiTo"])
async def test_la_busqueda_de_la_bebida_ignora_mayusculas(ws, pedido):
    await start_payment(pedido, ws)

    [msg] = enviado(ws)
    assert isinstance(msg, PaymentStarted)
    assert msg.payload.drink_name == "Mojito"  # el nombre canónico del catálogo


async def test_la_busqueda_ignora_mayusculas_con_acentos_y_espacios(ws):
    await start_payment("PIÑA COLADA", ws)

    [msg] = enviado(ws)
    assert isinstance(msg, PaymentStarted)
    assert msg.payload.drink_name == "Piña Colada"
    assert msg.payload.price == Decimal("7")


@pytest.mark.parametrize("pedido", ["Daiquiri", "Mojit", "Mojito 2", "Pina Colada"])
async def test_bebida_que_no_esta_activa_responde_error_y_no_inicia_pago(ws, pedido):
    await start_payment(pedido, ws)

    ws.app.state.payment_service.start.assert_not_called()
    [msg] = enviado(ws)
    assert isinstance(msg, PaymentResult)
    assert msg.payload.status == "error"
    assert msg.payload.reason == "drink_unavailable"
    assert msg.payload.payment_id is None


async def test_sin_bebidas_activas_responde_drink_unavailable(ws):
    ws.app.state.catalog_watcher.items_activos = []

    await start_payment("Mojito", ws)

    [msg] = enviado(ws)
    assert msg.payload.reason == "drink_unavailable"


async def test_start_payment_imprime_el_inicio_del_pago(ws, capsys):
    await start_payment("Mojito", ws)

    salida = capsys.readouterr().out
    assert "[Pago] iniciado Mojito" in salida
    assert PAY_URL in salida


# ---------- handle_client_message ----------


async def test_handle_start_payment_inicia_el_pago(ws):
    await handle_client_message(start("Mojito"), ws)

    ws.app.state.payment_service.start.assert_called_once()
    [msg] = enviado(ws)
    assert isinstance(msg, PaymentStarted)


async def test_handle_start_payment_con_bebida_inexistente_responde_error(ws):
    await handle_client_message(start("Nada"), ws)

    [msg] = enviado(ws)
    assert isinstance(msg, PaymentResult)
    assert msg.payload.status == "error"


async def test_handle_cancel_payment_cancela_el_pago_indicado(ws):
    msg = CancelPayment(payload=CancelPaymentPayload(payment_id="tok-123456"))

    await handle_client_message(msg, ws)

    ws.app.state.payment_service.cancel.assert_called_once_with("tok-123456")


async def test_handle_cancel_payment_sin_id_cancela_el_pago_en_curso(ws):
    await handle_client_message(CancelPayment(payload=CancelPaymentPayload()), ws)

    ws.app.state.payment_service.cancel.assert_called_once_with(None)


async def test_cancelar_no_envia_nada_al_cliente(ws):

    await handle_client_message(CancelPayment(payload=CancelPaymentPayload()), ws)

    ws.app.state.ws_manager.send.assert_not_awaited()
    ws.app.state.ws_manager.broadcast.assert_not_called()


async def test_los_mensajes_de_pago_no_tocan_el_estado_de_pantalla(ws):
    from app.services.screen_state import ScreenState

    await handle_client_message(start("Mojito"), ws)
    await handle_client_message(CancelPayment(payload=CancelPaymentPayload()), ws)

    assert ScreenState.current is None
    ws.app.state.order_service.request_order.assert_not_called()