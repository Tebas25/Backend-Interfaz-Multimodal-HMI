import json

import pytest
from pydantic import ValidationError

from app.schemas.events_dto import TipoEvento
from app.schemas.ws_messages import (
    CobotStatus,
    CobotStatusPayload,
    FrontState,
    OrderRequest,
    client_adapter,
)


def test_order_message_is_parsed():
    raw = '{"type": "order", "payload": {"nombre_item": "Cuba Libre"}}'
    msg = client_adapter.validate_json(raw)
    assert isinstance(msg, OrderRequest)
    assert msg.payload.nombre_item == "Cuba Libre"


def test_state_message_still_parsed_with_the_union():
    raw = '{"type": "state", "payload": {"screen": "menu", "source": "touch"}}'
    assert isinstance(client_adapter.validate_json(raw), FrontState)


@pytest.mark.parametrize(
    "raw",
    [
        '{"type": "order", "payload": {}}',
        '{"type": "order", "payload": {"nombre_item": "X", "extra": 1}}',
        '{"type": "order", "payload": {"nombre_item": 5}}',
        '{"type": "order", "extra": 1, "payload": {"nombre_item": "X"}}',
        '{"type": "unknown", "payload": {}}',
        '{"payload": {"nombre_item": "X"}}',
    ],
)
def test_invalid_client_messages_are_rejected(raw):
    with pytest.raises(ValidationError):
        client_adapter.validate_json(raw)


def test_cobot_status_serialization():
    msg = CobotStatus(
        payload=CobotStatusPayload(
            codigo=999,
            tipo_evento=TipoEvento.ERROR_SISTEMA,
            descripcion="Sin conexión con el cobot",
        )
    )
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "cobot_status"
    assert data["payload"] == {
        "codigo": 999,
        "tipo_evento": "ErrorSistema",
        "descripcion": "Sin conexión con el cobot",
    }
    assert data["id"] and data["ts"]


def test_cobot_status_rejects_extra_fields_and_bad_types():
    with pytest.raises(ValidationError):
        CobotStatusPayload(
            codigo="abc", tipo_evento=TipoEvento.INFO_ROBOT, descripcion="d"
        )
    with pytest.raises(ValidationError):
        CobotStatusPayload(
            codigo=1, tipo_evento=TipoEvento.INFO_ROBOT, descripcion="d", extra=1
        )


def test_envelopes_get_unique_ids():
    payload = CobotStatusPayload(
        codigo=1, tipo_evento=TipoEvento.INFO_ROBOT, descripcion="d"
    )
    assert CobotStatus(payload=payload).id != CobotStatus(payload=payload).id
