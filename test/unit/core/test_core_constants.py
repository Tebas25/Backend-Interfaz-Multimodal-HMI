from app.core.core_constants import (
    COBOT_ID,
    CONNECTION_LOST_CODE,
    CRITICAL_STATES,
    MAX_REGISTER_VALUE,
    ORDER_REGISTER,
    STATE_DELIVERED,
    STATE_IDLE,
    STATE_PREPARING,
    STATUS_REGISTER,
    cobot_logs,
)
from app.schemas.events_dto import EventsDTO, TipoEvento


def test_every_entry_is_an_events_dto_with_matching_id():
    for code, evento in cobot_logs.items():
        assert isinstance(evento, EventsDTO)
        assert evento.evento_id == str(code)
        assert evento.cobot_id == COBOT_ID
        assert evento.descripcion


def test_all_codes_fit_in_a_16_bit_register():
    assert all(0 <= code <= MAX_REGISTER_VALUE for code in cobot_logs)


def test_connection_lost_is_a_critical_system_error():
    evento = cobot_logs[CONNECTION_LOST_CODE]
    assert evento.tipo_evento is TipoEvento.ERROR_SISTEMA
    assert CONNECTION_LOST_CODE in CRITICAL_STATES


def test_flow_states_are_translatable():
    assert STATE_PREPARING in cobot_logs
    assert STATE_DELIVERED in cobot_logs


def test_idle_is_handled_by_the_flow_not_by_the_dictionary():
    assert STATE_IDLE not in cobot_logs


def test_critical_states_exist_in_dictionary():
    assert CRITICAL_STATES <= set(cobot_logs)


def test_order_and_status_use_different_registers():
    assert ORDER_REGISTER != STATUS_REGISTER
