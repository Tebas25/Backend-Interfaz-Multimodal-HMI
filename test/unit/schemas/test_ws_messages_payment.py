import json
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.ws_messages import (
    CancelPayment,
    CancelPaymentPayload,
    ClientMessage,
    PaymentResult,
    PaymentResultPayload,
    PaymentStarted,
    PaymentStartedPayload,
    Screen,
    ServerMessage,
    StartPayment,
    StartPaymentPayload,
    StatePayload,
    StateSource,
    client_adapter,
)
from app.services.payment_service import PaymentStatus

server_adapter = TypeAdapter(ServerMessage)


def started(**cambios):
    datos = dict(
        payment_id="tok-123456",
        pay_url="http://host:8888/pay/tok-123456",
        drink_name="Mojito",
        price=Decimal("5.50"),
    )
    datos.update(cambios)
    return PaymentStarted(payload=PaymentStartedPayload(**datos))


# ---------- Screen ----------


def test_screen_incluye_las_pantallas_de_pago():
    assert Screen.PAYMENT.value == "payment"
    assert Screen.PAYMENT_RESULT.value == "payment_result"


@pytest.mark.parametrize("pantalla", [Screen.PAYMENT, Screen.PAYMENT_RESULT])
def test_el_front_puede_reportar_las_pantallas_de_pago(pantalla):
    p = StatePayload(screen=pantalla, source=StateSource.TOUCH)

    assert p.screen is pantalla


# ---------- PaymentStarted ----------


def test_payment_started_tiene_su_discriminador_y_envelope():
    a, b = started(), started()

    assert a.type == "payment_started"
    assert a.id != b.id
    assert a.ts.tzinfo is not None


def test_payment_started_serializa_el_precio_como_texto_decimal():
    """Contrato con el front: pydantic serializa Decimal como cadena ("5.50")."""
    datos = json.loads(started().model_dump_json())

    assert datos["type"] == "payment_started"
    assert datos["payload"] == {
        "payment_id": "tok-123456",
        "pay_url": "http://host:8888/pay/tok-123456",
        "drink_name": "Mojito",
        "price": "5.50",
    }


@pytest.mark.parametrize("campo", ["payment_id", "pay_url", "drink_name", "price"])
def test_payment_started_exige_todos_los_campos(campo):
    datos = dict(payment_id="a", pay_url="u", drink_name="n", price="1")
    datos.pop(campo)

    with pytest.raises(ValidationError):
        PaymentStartedPayload(**datos)


def test_payment_started_rechaza_campos_extra():
    with pytest.raises(ValidationError):
        PaymentStartedPayload(
            payment_id="a", pay_url="u", drink_name="n", price="1", extra=1
        )


def test_payment_started_ida_y_vuelta_json():
    original = started()

    leido = server_adapter.validate_json(original.model_dump_json())

    assert isinstance(leido, PaymentStarted)
    assert leido == original


# ---------- PaymentResult ----------


@pytest.mark.parametrize("estado", ["approved", "rejected", "expired", "error"])
def test_payment_result_acepta_los_estados_validos(estado):
    assert PaymentResultPayload(status=estado).status == estado


@pytest.mark.parametrize("estado", ["pending", "cancelled", "ok", "APPROVED", ""])
def test_payment_result_rechaza_otros_estados(estado):
    with pytest.raises(ValidationError):
        PaymentResultPayload(status=estado)


def test_payment_result_payment_id_y_reason_son_opcionales():
    p = PaymentResultPayload(status="error")

    assert p.payment_id is None
    assert p.reason is None


def test_payment_result_rechaza_campos_extra():
    with pytest.raises(ValidationError):
        PaymentResultPayload(status="error", detalle="x")


def test_payment_result_requiere_estado():
    with pytest.raises(ValidationError):
        PaymentResultPayload()


def test_los_estados_que_el_servicio_notifica_caben_en_payment_result():
    for estado in (
        PaymentStatus.APPROVED,
        PaymentStatus.REJECTED,
        PaymentStatus.EXPIRED,
    ):
        PaymentResultPayload(status=estado.value)

    with pytest.raises(ValidationError):
        PaymentResultPayload(status=PaymentStatus.CANCELLED.value)


def test_payment_result_ida_y_vuelta_json():
    original = PaymentResult(
        payload=PaymentResultPayload(
            payment_id="tok-123456", status="error", reason="drink_unavailable"
        )
    )

    leido = server_adapter.validate_json(original.model_dump_json())

    assert isinstance(leido, PaymentResult)
    assert leido == original
    assert json.loads(original.model_dump_json())["type"] == "payment_result"


# ---------- StartPayment ----------


def test_start_payment_tiene_su_discriminador():
    assert (
        StartPayment(payload=StartPaymentPayload(drink="Mojito")).type
        == "start_payment"
    )


def test_start_payment_acepta_nombres_de_1_a_100_caracteres():
    StartPaymentPayload(drink="a")
    StartPaymentPayload(drink="a" * 100)


@pytest.mark.parametrize("drink", ["", "a" * 101])
def test_start_payment_rechaza_nombres_fuera_de_rango(drink):
    with pytest.raises(ValidationError):
        StartPaymentPayload(drink=drink)


def test_start_payment_requiere_la_bebida():
    with pytest.raises(ValidationError):
        StartPaymentPayload()


def test_start_payment_rechaza_campos_extra():
    with pytest.raises(ValidationError):
        StartPaymentPayload(drink="Mojito", precio=1)


# ---------- CancelPayment ----------


def test_cancel_payment_no_requiere_id():
    p = CancelPaymentPayload()

    assert p.payment_id is None
    assert CancelPayment(payload=p).type == "cancel_payment"


def test_cancel_payment_acepta_un_id():
    assert CancelPaymentPayload(payment_id="tok").payment_id == "tok"


def test_cancel_payment_rechaza_campos_extra():
    with pytest.raises(ValidationError):
        CancelPaymentPayload(payment_id="tok", motivo="x")


# ---------- adaptadores ----------


def test_client_adapter_interpreta_start_payment():
    msg = client_adapter.validate_json(
        '{"type":"start_payment","payload":{"drink":"Mojito"}}'
    )

    assert isinstance(msg, StartPayment)
    assert msg.payload.drink == "Mojito"


@pytest.mark.parametrize(
    "raw, id_esperado",
    [
        ('{"type":"cancel_payment","payload":{"payment_id":"tok"}}', "tok"),
        ('{"type":"cancel_payment","payload":{}}', None),
        ('{"type":"cancel_payment","payload":{"payment_id":null}}', None),
    ],
)
def test_client_adapter_interpreta_cancel_payment(raw, id_esperado):
    msg = client_adapter.validate_json(raw)

    assert isinstance(msg, CancelPayment)
    assert msg.payload.payment_id == id_esperado


@pytest.mark.parametrize(
    "raw",
    [
        '{"type":"start_payment","payload":{}}',
        '{"type":"start_payment","payload":{"drink":""}}',
        '{"type":"start_payment"}',
    ],
)
def test_client_adapter_rechaza_start_payment_invalido(raw):
    with pytest.raises(ValidationError):
        client_adapter.validate_json(raw)


@pytest.mark.parametrize(
    "modelo",
    [started(), PaymentResult(payload=PaymentResultPayload(status="approved"))],
)
def test_los_mensajes_del_servidor_no_se_aceptan_como_mensajes_del_cliente(modelo):
    with pytest.raises(ValidationError):
        client_adapter.validate_json(modelo.model_dump_json())


def test_los_mensajes_del_cliente_no_se_aceptan_como_mensajes_del_servidor():
    raw = StartPayment(payload=StartPaymentPayload(drink="Mojito")).model_dump_json()

    with pytest.raises(ValidationError):
        server_adapter.validate_json(raw)


def test_el_tipo_client_message_incluye_los_mensajes_de_pago():
    nombres = {t.__name__ for t in ClientMessage.__args__[0].__args__}
    assert {"StartPayment", "CancelPayment"} <= nombres