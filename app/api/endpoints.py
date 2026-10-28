from fastapi import APIRouter
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.schemas.ws_messages import (
    build_catalog_update,
    FrontState,
    client_adapter,
    ErrorMessage,
    ErrorPayload,
)
from app.services.screen_state import ScreenState

ws_router = APIRouter()


def handle_client_message(msg) -> None:
    match msg:
        case FrontState():
            ScreenState.update(msg.payload)


@ws_router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    print("[WS] handshake recibido")
    manager = ws.app.state.ws_manager
    watcher = ws.app.state.catalog_watcher

    await manager.connect(ws)
    try:
        # Estado actual al conectar: el cliente se sincroniza solo, incluso tras una reconexión
        snapshot = build_catalog_update(watcher)
        if snapshot:
            await manager.send(ws, snapshot)

        while True:
            raw = await ws.receive_text()
            print(f"[WS] recibido: {raw}")
            try:
                msg = client_adapter.validate_json(raw)
            except ValidationError as e:
                detail = [
                    {"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()
                ]
                print(f"[WS] Mensaje inválido del front: {detail}")
                await manager.send(
                    ws, ErrorMessage(payload=ErrorPayload(detail=detail))
                )
                continue
            handle_client_message(msg)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
