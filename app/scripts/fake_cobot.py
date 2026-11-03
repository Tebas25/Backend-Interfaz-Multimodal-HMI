import asyncio

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer

HOST, PORT, DEVICE_ID = "127.0.0.1", 5020, 1
ORDER, STATUS = 0, 1


async def simulate() -> None:
    await asyncio.sleep(1)  # espera a que el servidor esté arriba
    client = AsyncModbusTcpClient(HOST, port=PORT)
    await client.connect()

    async def get_order() -> int:
        r = await client.read_holding_registers(ORDER, count=1, device_id=DEVICE_ID)
        return r.registers[0]

    async def set_status(value: int) -> None:
        await client.write_register(STATUS, value, device_id=DEVICE_ID)

    await set_status(0)
    print("[Cobot] listo, en reposo")
    while True:
        await asyncio.sleep(0.1)
        if await get_order() == 0:
            continue
        print(f"[Cobot] orden recibida: {await get_order()}")
        await set_status(101)
        await asyncio.sleep(1)
        await set_status(102)
        print("[Cobot] preparando, esperando handshake...")
        while await get_order() != 0:
            await asyncio.sleep(0.1)
        print("[Cobot] handshake OK")
        await asyncio.sleep(3)
        await set_status(200)
        await asyncio.sleep(1)
        await set_status(0)
        print("[Cobot] bebida entregada, en reposo")


async def main() -> None:
    device = ModbusDeviceContext(hr=ModbusSequentialDataBlock(1, [0] * 100))
    context = ModbusServerContext(devices=device, single=True)
    await asyncio.gather(
        StartAsyncTcpServer(context=context, address=(HOST, PORT)),
        simulate(),
    )


asyncio.run(main())
