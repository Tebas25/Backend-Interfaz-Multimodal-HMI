import asyncio
from contextlib import aclosing

from app.schemas.events_dto import EventsDTO
from app.schemas.ws_messages import (
    CobotStatus,
    CobotStatusPayload,
    Navigate,
    NavigatePayload,
    Screen,
)
from app.services.cobot_service import CobotService
from app.services.connection_manager import ConnectionManager
from app.services.event_publisher import EventPublisher
from app.services.screen_state import ScreenState

ORDER_SCREEN = Screen.PAYMENT


class OrderService:
    def __init__(
        self,
        manager: ConnectionManager,
        watcher,
        cobot: CobotService,
        publisher: EventPublisher,
    ):
        self._manager = manager
        self._watcher = watcher
        self._cobot = cobot
        self._task: asyncio.Task | None = None
        self._publisher = publisher

    def request_order(self, nombre_item: str) -> str | None:
        """Devuelve un mensaje de error, o None si el pedido arrancó."""
        if self._task and not self._task.done():
            return "Ya hay un pedido en curso"
        if ScreenState.current is not ORDER_SCREEN:
            return "Los pedidos solo se aceptan desde la pantalla de pago"

        item = next(
            (i for i in self._watcher.items_activos if i.nombre_item == nombre_item),
            None,
        )
        if item is None:
            return "Bebida no disponible"
        if item.codigo_modbus is None:
            return "La bebida no tiene código para el cobot"

        self._task = asyncio.create_task(
            self._run(item.codigo_modbus), name="cobot-order"
        )
        return None

    async def _run(self, codigo_modbus: int) -> None:
        try:
            async with aclosing(self._cobot.prepare_drink(codigo_modbus)) as events:
                async for evento in events:
                    await self._manager.broadcast(
                        CobotStatus(payload=self._to_payload(evento))
                    )
                    self._publisher.publish(evento)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[Pedido] Error: {type(e).__name__}: {e}")
        await self._manager.broadcast(
            Navigate(payload=NavigatePayload(screen=Screen.WELCOME))
        )

    @staticmethod
    def _to_payload(evento: EventsDTO) -> CobotStatusPayload:
        return CobotStatusPayload(
            codigo=int(evento.evento_id) if evento.evento_id.isdigit() else -1,
            tipo_evento=evento.tipo_evento,
            descripcion=evento.descripcion,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
