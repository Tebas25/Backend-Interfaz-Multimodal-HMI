from fastapi import HTTPException, APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.core import core_constants
from app.core.config import settings
from app.models.cobot_menu_item import CobotMenuItem
from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.schemas.ws_messages import build_catalog_update
from app.services.http_request_service import HttpRequestService

# catalog_router = APIRouter(prefix="/catalog", tags=["catalog"])
ws_router = APIRouter()


# @catalog_router.get("/get-items", response_model=CobotCatalogResponse)
# async def get_catalog_items():
#     request_url = f"{settings.get_catalog_url}{core_constants.COBOT_ID}"
#     http_service = HttpRequestService(request_url, settings.kong_auth_key)
#     catalog = await http_service.get(CobotCatalogResponse)
#     if catalog is None:
#         raise HTTPException(status_code=404, detail="Error al obtener catalogo")
#     updated_items: list[CobotMenuItem] = []
#     for item in catalog.items:
#         if item.estado:
#             updated_items.append(item)
#     return CobotCatalogResponse(items=updated_items, total=len(updated_items))


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
            # De momento el front no envía nada; esto mantiene la conexión viva
            # y detecta la desconexión. Aquí se procesarán los mensajes 'state' más adelante.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
