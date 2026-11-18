import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from pymodbus.exceptions import ConnectionException, ModbusException

from app.core.config import settings
from app.core.core_constants import (
    COBOT_ID,
    CONNECTION_LOST_CODE,
    CRITICAL_STATES,
    DEFAULT_VALUE,
    ORDER_REGISTER,
    STATE_DELIVERED,
    STATE_IDLE,
    STATE_PREPARING,
    STATUS_REGISTER,
    cobot_logs,
)
from app.schemas.events_dto import TipoEvento
from app.services.cobot_service import CobotService
from app.core.core_constants import DEFAULT_EVENT_ID

UNKNOWN_CODE = 77
DRINK = 7
# Un estado informativo/warning que no dispara ninguna lógica del bucle
INTERMEDIATE = next(
    c
    for c in cobot_logs
    if c not in CRITICAL_STATES
    and c not in {STATE_PREPARING, STATE_DELIVERED, CONNECTION_LOST_CODE}
)
# Un error crítico que NO sea la pérdida de conexión
CRITICAL = next(c for c in CRITICAL_STATES if c != CONNECTION_LOST_CODE)

NETWORK_ERRORS = [
    ModbusException("modbus"),
    ConnectionException("socket"),
    asyncio.TimeoutError(),
    OSError("cable desconectado"),
]


def codigos(events):
    return [e.codigo for e in events]


def _response(error: bool = False, registers=None):
    r = MagicMock()
    r.isError.return_value = error
    r.registers = registers or []
    return r


async def collect(gen):
    return [e async for e in gen]


@pytest.fixture
def service():
    svc = CobotService()
    svc.modbus_connection = MagicMock()
    svc.modbus_connection.connect = AsyncMock(return_value=True)
    svc.modbus_connection.close = MagicMock()
    svc.modbus_connection.client = MagicMock()
    return svc


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(settings, "polling_interval", 0)
    monkeypatch.setattr(settings, "order_timeout", 2)


class TestHelpers:
    def test_translate_known_code(self, service):
        evento = service._translate(CONNECTION_LOST_CODE)
        assert evento.codigo == CONNECTION_LOST_CODE
        assert evento.evento_id == DEFAULT_EVENT_ID

    def test_translate_unknown_code_returns_none(self, service):
        assert UNKNOWN_CODE not in cobot_logs
        assert service._translate(UNKNOWN_CODE) is None

    def test_system_event(self):
        evento = CobotService._system_event("BUSY", "ocupado")
        assert evento.cobot_id == COBOT_ID
        assert evento.evento_id == "BUSY"
        assert evento.tipo_evento is TipoEvento.ERROR_SISTEMA
        assert evento.descripcion == "ocupado"


@pytest.mark.asyncio
class TestWriteOrder:
    async def test_ok_returns_none(self, service):
        write = AsyncMock(return_value=_response())
        service.modbus_connection.client.write_register = write
        assert await service.write_order(3) is None
        write.assert_awaited_once_with(
            ORDER_REGISTER, 3, device_id=service.cobot_slave_id
        )

    @pytest.mark.parametrize("code", [-1, 65536])
    async def test_rejects_values_outside_16_bits(self, service, code):
        with pytest.raises(ValueError):
            await service.write_order(code)

    async def test_error_response_returns_connection_lost(self, service):
        service.modbus_connection.client.write_register = AsyncMock(
            return_value=_response(error=True)
        )
        assert await service.write_order(3) == CONNECTION_LOST_CODE

    @pytest.mark.parametrize("exc", NETWORK_ERRORS)
    async def test_network_errors_return_connection_lost_and_close(self, service, exc):
        service.modbus_connection.client.write_register = AsyncMock(side_effect=exc)
        assert await service.write_order(3) == CONNECTION_LOST_CODE
        service.modbus_connection.close.assert_called_once()

    async def test_connect_failure_returns_connection_lost(self, service):
        service.modbus_connection.connect = AsyncMock(
            side_effect=ConnectionException("down")
        )
        assert await service.write_order(3) == CONNECTION_LOST_CODE

    async def test_programming_errors_are_not_swallowed(self, service):
        service.modbus_connection.client.write_register = AsyncMock(
            side_effect=RuntimeError("bug")
        )
        with pytest.raises(RuntimeError):
            await service.write_order(3)


@pytest.mark.asyncio
class TestReadStatus:
    async def test_ok_returns_register_value(self, service):
        read = AsyncMock(return_value=_response(registers=[STATE_PREPARING]))
        service.modbus_connection.client.read_holding_registers = read
        assert await service.read_status() == STATE_PREPARING
        read.assert_awaited_once_with(
            STATUS_REGISTER, count=1, device_id=service.cobot_slave_id
        )

    async def test_error_response_returns_connection_lost(self, service):
        service.modbus_connection.client.read_holding_registers = AsyncMock(
            return_value=_response(error=True)
        )
        assert await service.read_status() == CONNECTION_LOST_CODE

    @pytest.mark.parametrize("exc", NETWORK_ERRORS)
    async def test_network_errors_return_connection_lost_and_close(self, service, exc):
        service.modbus_connection.client.read_holding_registers = AsyncMock(
            side_effect=exc
        )
        assert await service.read_status() == CONNECTION_LOST_CODE
        service.modbus_connection.close.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.usefixtures("fast")
class TestPrepareDrink:
    async def test_busy_when_lock_is_taken(self, service):
        await service._lock.acquire()
        try:
            events = await collect(service.prepare_drink(DRINK))
        finally:
            service._lock.release()
        assert [e.evento_id for e in events] == ["BUSY"]
        assert events[0].tipo_evento is TipoEvento.ERROR_SISTEMA

    @pytest.mark.parametrize("state", [STATE_PREPARING, CONNECTION_LOST_CODE])
    async def test_not_idle_known_code_emits_that_event(self, service, state):
        service.read_status = AsyncMock(return_value=state)
        service.write_order = AsyncMock()
        events = await collect(service.prepare_drink(DRINK))
        assert codigos(events) == [state]
        service.write_order.assert_not_awaited()

    async def test_not_idle_unknown_code_emits_not_idle(self, service):
        service.read_status = AsyncMock(return_value=UNKNOWN_CODE)
        service.write_order = AsyncMock()
        events = await collect(service.prepare_drink(DRINK))
        assert [e.evento_id for e in events] == ["NOT_IDLE"]
        service.write_order.assert_not_awaited()

    async def test_write_failure_at_start_emits_connection_lost(self, service):
        service.read_status = AsyncMock(side_effect=[STATE_IDLE])
        service.write_order = AsyncMock(return_value=CONNECTION_LOST_CODE)
        events = await collect(service.prepare_drink(DRINK))
        assert codigos(events) == [CONNECTION_LOST_CODE]

    async def test_happy_path_emits_changes_and_single_handshake(self, service):
        service.read_status = AsyncMock(
            side_effect=[
                STATE_IDLE,  # safe-check
                STATE_IDLE,  # sin cambios
                INTERMEDIATE,
                STATE_PREPARING,
                STATE_DELIVERED,
                STATE_IDLE,
            ]
        )
        service.write_order = AsyncMock(return_value=None)
        events = await collect(service.prepare_drink(DRINK))
        assert codigos(events) == [INTERMEDIATE, STATE_PREPARING, STATE_DELIVERED]
        assert service.write_order.await_args_list == [
            call(DRINK),
            call(DEFAULT_VALUE),
        ]
        assert not service._lock.locked()

    async def test_handshake_happens_only_once(self, service):
        service.read_status = AsyncMock(
            side_effect=[
                STATE_IDLE,
                STATE_PREPARING,
                INTERMEDIATE,
                STATE_PREPARING,
                STATE_DELIVERED,
                STATE_IDLE,
            ]
        )
        service.write_order = AsyncMock(return_value=None)
        await collect(service.prepare_drink(DRINK))
        handshakes = [
            c for c in service.write_order.await_args_list if c == call(DEFAULT_VALUE)
        ]
        assert len(handshakes) == 1

    async def test_handshake_failure_stops_with_connection_lost(self, service):
        service.read_status = AsyncMock(side_effect=[STATE_IDLE, STATE_PREPARING])
        service.write_order = AsyncMock(side_effect=[None, CONNECTION_LOST_CODE])
        events = await collect(service.prepare_drink(DRINK))
        assert codigos(events) == [CONNECTION_LOST_CODE]

    async def test_unknown_codes_are_not_emitted(self, service):
        assert UNKNOWN_CODE not in cobot_logs
        service.read_status = AsyncMock(
            side_effect=[
                STATE_IDLE,
                UNKNOWN_CODE,
                STATE_PREPARING,
                STATE_DELIVERED,
                STATE_IDLE,
            ]
        )
        service.write_order = AsyncMock(return_value=None)
        events = await collect(service.prepare_drink(DRINK))
        assert codigos(events) == [STATE_PREPARING, STATE_DELIVERED]

    async def test_idle_before_delivery_does_not_end_the_order(self, service):
        service.read_status = AsyncMock(
            side_effect=[
                STATE_IDLE,
                STATE_PREPARING,
                STATE_IDLE,
                STATE_DELIVERED,
                STATE_IDLE,
            ]
        )
        service.write_order = AsyncMock(return_value=None)
        events = await collect(service.prepare_drink(DRINK))
        assert codigos(events) == [STATE_PREPARING, STATE_DELIVERED]

    async def test_critical_state_emits_and_ends(self, service):
        service.read_status = AsyncMock(
            side_effect=[STATE_IDLE, STATE_PREPARING, CRITICAL]
        )
        service.write_order = AsyncMock(return_value=None)
        events = await collect(service.prepare_drink(DRINK))
        assert [e.codigo for e in events] == [STATE_PREPARING, CRITICAL]
        assert not service._lock.locked()

    async def test_connection_lost_mid_order_emits_and_ends(self, service):
        service.read_status = AsyncMock(
            side_effect=[STATE_IDLE, STATE_PREPARING, CONNECTION_LOST_CODE]
        )
        service.write_order = AsyncMock(return_value=None)
        events = await collect(service.prepare_drink(DRINK))
        assert events[-1].codigo == CONNECTION_LOST_CODE

    async def test_timeout_emits_timeout_event_and_releases_lock(
        self, service, monkeypatch
    ):
        monkeypatch.setattr(settings, "order_timeout", 0.05)
        service.read_status = AsyncMock(return_value=STATE_IDLE)
        service.write_order = AsyncMock(return_value=None)
        events = await collect(service.prepare_drink(DRINK))
        assert [e.evento_id for e in events] == ["TIMEOUT"]
        assert events[0].tipo_evento is TipoEvento.ERROR_SISTEMA
        assert not service._lock.locked()
