from app.core.config import settings
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException


class ModbusConnection:
    def __init__(self):
        # El cliente se crea en el primer connect(): pymodbus necesita un event loop activo
        self.client: AsyncModbusTcpClient | None = None

    async def connect(self) -> bool:
        if self.client is None:
            self.client = AsyncModbusTcpClient(
                host=settings.cobot_host,
                port=settings.cobot_port,
                timeout=settings.modbus_timeout,
                retries=settings.modbus_retries,
            )
        if self.client.connected:
            return True
        else:
            connect_cobot = await self.client.connect()
            if connect_cobot:
                return True
            else:
                raise ConnectionException

    def close(self):
        if self.client is not None:
            self.client.close()


modbus_connection = ModbusConnection()
