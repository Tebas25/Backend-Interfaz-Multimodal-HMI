from unittest.mock import AsyncMock, MagicMock

import pytest
from pymodbus.exceptions import ConnectionException

import app.client.session as session
from app.client.session import ModbusConnection
from app.core.config import settings


@pytest.fixture
def conn():
    c = ModbusConnection()
    c.client = MagicMock()
    return c


def test_client_is_not_created_on_import():
    assert ModbusConnection().client is None


def test_close_without_client_does_not_fail():
    ModbusConnection().close()


def test_close_closes_client(conn):
    conn.close()
    conn.client.close.assert_called_once()


@pytest.mark.asyncio
class TestConnect:
    async def test_creates_client_with_settings_on_first_connect(self, monkeypatch):
        fake_client = MagicMock(connected=False)
        fake_client.connect = AsyncMock(return_value=True)
        factory = MagicMock(return_value=fake_client)
        monkeypatch.setattr(session, "AsyncModbusTcpClient", factory)

        conn = ModbusConnection()
        assert await conn.connect() is True
        factory.assert_called_once_with(
            host=settings.cobot_host,
            port=settings.cobot_port,
            timeout=settings.modbus_timeout,
            retries=settings.modbus_retries,
        )
        assert conn.client is fake_client

    async def test_already_connected_does_not_reconnect(self, conn):
        conn.client.connected = True
        conn.client.connect = AsyncMock()
        assert await conn.connect() is True
        conn.client.connect.assert_not_awaited()

    async def test_connects_when_not_connected(self, conn):
        conn.client.connected = False
        conn.client.connect = AsyncMock(return_value=True)
        assert await conn.connect() is True
        conn.client.connect.assert_awaited_once()

    async def test_raises_when_cobot_is_unreachable(self, conn):
        conn.client.connected = False
        conn.client.connect = AsyncMock(return_value=False)
        with pytest.raises(ConnectionException):
            await conn.connect()
