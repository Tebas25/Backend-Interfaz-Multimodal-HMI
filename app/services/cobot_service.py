import asyncio
from collections.abc import AsyncIterator
from pymodbus.exceptions import ModbusException

from app.client.session import modbus_connection
from app.core.config import settings
from app.core.core_constants import (
    CONNECTION_LOST_CODE,
    CRITICAL_STATES,
    DEFAULT_VALUE,
    MAX_REGISTER_VALUE,
    ORDER_REGISTER,
    STATE_DELIVERED,
    STATE_IDLE,
    STATE_PREPARING,
    STATUS_REGISTER,
    COBOT_ID,
    cobot_logs,
)
from app.schemas.events_dto import EventsDTO, TipoEvento


class CobotService:
    def __init__(self):
        self.modbus_connection = modbus_connection
        self.cobot_slave_id = settings.cobot_slave_id
        self._lock = asyncio.Lock()

    async def write_order(self, modbus_code: int) -> int | None:
        """Devuelve None si escribió bien, o CONNECTION_LOST_CODE si falló la comunicación."""
        if not 0 <= modbus_code <= MAX_REGISTER_VALUE:
            raise ValueError("El código debe caber en 16 bits sin signo")
        try:
            await self.modbus_connection.connect()
            response = await self.modbus_connection.client.write_register(
                ORDER_REGISTER, modbus_code, device_id=self.cobot_slave_id
            )
            if response.isError():
                return CONNECTION_LOST_CODE
            return None
        except (ModbusException, asyncio.TimeoutError, OSError):
            self.modbus_connection.close()
            return CONNECTION_LOST_CODE

    async def read_status(self) -> int:
        """Devuelve el código de estado leído o CONNECTION_LOST_CODE si falló la comunicación."""
        try:
            await self.modbus_connection.connect()
            response = await self.modbus_connection.client.read_holding_registers(
                STATUS_REGISTER, count=1, device_id=self.cobot_slave_id
            )
            if response.isError():
                return CONNECTION_LOST_CODE
            return response.registers[0]
        except (ModbusException, asyncio.TimeoutError, OSError):
            self.modbus_connection.close()
            return CONNECTION_LOST_CODE

    def _translate(self, codigo: int) -> EventsDTO:
        return cobot_logs.get(codigo)

    @staticmethod
    def _system_event(event_id: str, description: str) -> EventsDTO:
        return EventsDTO(
            cobot_id=COBOT_ID,
            evento_id=event_id,
            tipo_evento=TipoEvento.ERROR_SISTEMA,
            descripcion=description,
        )

    async def prepare_drink(self, drink_code: int) -> AsyncIterator[EventsDTO]:
        if self._lock.locked():
            yield self._system_event("BUSY", "Cobot ocupado con otro pedido")
            return

        async with self._lock:
            try:
                async with asyncio.timeout(settings.order_timeout):
                    state = await self.read_status()
                    if state != STATE_IDLE:
                        yield self._translate(state) or self._system_event(
                            "NOT_IDLE", "El cobot no está en reposo"
                        )
                        return

                    error = await self.write_order(drink_code)
                    if error is not None:
                        yield self._translate(error)
                        return

                    last_read_state = state
                    handshake = False
                    delivered = False

                    while True:
                        await asyncio.sleep(settings.polling_interval)
                        state = await self.read_status()
                        if state == last_read_state:
                            continue
                        last_read_state = state

                        if state == STATE_IDLE:
                            if delivered:
                                return
                            continue

                        if state == STATE_PREPARING and not handshake:
                            error = await self.write_order(DEFAULT_VALUE)
                            if error is not None:
                                yield self._translate(error)
                                return
                            handshake = True

                        event = self._translate(state)

                        if event is not None:
                            yield event
                        if state == STATE_DELIVERED:
                            delivered = True
                        if state in CRITICAL_STATES:
                            return
            except TimeoutError:
                yield self._system_event(
                    "TIMEOUT", "El pedido excedió el tiempo máximo"
                )


cobot_service = CobotService()
