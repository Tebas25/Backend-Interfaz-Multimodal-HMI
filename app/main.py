from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.endpoints import ws_router

# catalog_router
from app.core.config import settings
from app.core.core_constants import COBOT_ID
from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.schemas.ws_messages import build_catalog_update
from app.services.catalog_watcher_service import CatalogWatcher
from app.services.connection_manager import ConnectionManager
from app.services.http_request_service import HttpRequestService


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = ConnectionManager()
    app.state.ws_manager = manager

    update_svc = HttpRequestService(
        f"{settings.micro_url}/catalog/check-update/{COBOT_ID}",
        authkey=settings.kong_auth_key,
    )
    catalog_svc = HttpRequestService(
        f"{settings.get_catalog_url}/{COBOT_ID}", authkey=settings.kong_auth_key
    )

    async def broadcast_catalog() -> None:
        msg = build_catalog_update(watcher)
        if msg:
            await manager.broadcast(msg)

    watcher = CatalogWatcher(
        update_svc,
        catalog_svc,
        CobotCatalogResponse,
        interval=5,
        on_change=broadcast_catalog,
    )
    app.state.catalog_watcher = watcher
    watcher.start()

    yield

    await watcher.stop()
    await update_svc.close()
    await catalog_svc.close()


app = FastAPI(
    title="API Bartender Robótico - Módulo Multimodal",
    description="Estructura base de la API local.",
    version="1.0.0",
    lifespan=lifespan,
)
# app.include_router(catalog_router)
app.include_router(ws_router)


@app.get("/")
async def root():
    return {"status": "ok", "message": "Estructura base configurada y en línea."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888)
