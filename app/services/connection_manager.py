import asyncio
from fastapi import WebSocket
from pydantic import BaseModel


class ConnectionManager:
    def __init__(self):
        # Un lock por conexión: evita dos envíos simultáneos al mismo cliente
        self._clients: dict[WebSocket, asyncio.Lock] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients[ws] = asyncio.Lock()

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)

    async def send(self, ws: WebSocket, message: BaseModel) -> bool:
        lock = self._clients.get(ws)
        if lock is None:
            return False
        try:
            async with lock:
                await asyncio.wait_for(
                    ws.send_text(message.model_dump_json()), timeout=5
                )
            return True
        except Exception as e:
            print(
                f"[WS] Error al enviar, se descarta el cliente: {type(e).__name__}: {e!r}"
            )
            self.disconnect(ws)
            return False

    async def broadcast(self, message: BaseModel) -> None:
        clients = list(self._clients)  # copia: la lista puede cambiar mientras se envía
        if not clients:
            return
        await asyncio.gather(*(self.send(ws, message) for ws in clients))
