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
from app.services.publisher import Publisher
from app.services.screen_state import ScreenState
from typing import Callable
from app.core.voice_response import VoiceEvent

ORDER_SCREEN = Screen.PAYMENT
ALLOWED_ORDER_SCREENS = (Screen.PAYMENT, Screen.PAYMENT_RESULT)


class OrderService:
    def __init__(
        self,
        manager: ConnectionManager,
        watcher,
        cobot: CobotService,
        publisher: Publisher[EventsDTO],
        on_voice: Callable[..., asyncio.Task | None] | None = None,
    ):
        self._manager = manager
        self._watcher = watcher
        self._cobot = cobot
        self._task: asyncio.Task | None = None
        self._publisher = publisher
        self._on_voice = on_voice

    def request_order(self, nombre_item: str) -> str | None:
        """Devuelve un mensaje de error, o None si el pedido arrancó."""
        if self._task and not self._task.done():
            return "Ya hay un pedido en curso"
        if ScreenState.current not in ALLOWED_ORDER_SCREENS:
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
            self._run(item.codigo_modbus, item.nombre_item), name="cobot-order"
        )
        return None

    async def _run(self, codigo_modbus: int, nombre_item: str) -> None:
        announced_prep = False
        farewell_task: asyncio.Task | None = None
        try:
            async with aclosing(self._cobot.prepare_drink(codigo_modbus)) as events:
                async for evento in events:
                    payload = self._to_payload(evento)
                    await self._manager.broadcast(CobotStatus(payload=payload))
                    self._publisher.publish(evento)

                    if self._on_voice:
                        if payload.codigo in (101, 102) and not announced_prep:
                            announced_prep = True
                            self._on_voice(
                                VoiceEvent.PREPARING_DRINK, drink=nombre_item
                            )
                        elif payload.codigo == 200:
                            farewell_task = self._on_voice(
                                VoiceEvent.PREPARING_COMPLETE, drink=nombre_item
                            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[Pedido] Error: {type(e).__name__}: {e}")

        if farewell_task is not None:
            try:
                await asyncio.wait_for(farewell_task, timeout=8.0)
            except Exception:
                pass

    @staticmethod
    def _to_payload(evento: EventsDTO) -> CobotStatusPayload:
        return CobotStatusPayload(
            codigo=int(evento.codigo) if evento.codigo is not None else -1,
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
