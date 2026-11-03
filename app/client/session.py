from app.core.config import settings
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException


class ModbusConnection:
    def __init__(self):
        self.client = AsyncModbusTcpClient(
            host=settings.cobot_host,
            port=settings.cobot_port,
            timeout=settings.modbus_timeout,
            retries=settings.modbus_retries,
        )

    async def connect(self) -> bool:
        if self.client.connected:
            return True
        else:
            connect_cobot = await self.client.connect()
            if connect_cobot:
                return True
            else:
                raise ConnectionException

    def close(self):
        self.client.close()


modbus_connection = ModbusConnection()
