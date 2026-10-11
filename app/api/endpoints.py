from fastapi import HTTPException, APIRouter

from app.core import core_constants
from app.core.config import settings
from app.models.cobot_menu_item import CobotMenuItem
from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.services.http_request_service import HttpRequestService

catalog_router = APIRouter(prefix="/catalog", tags=["catalog"])


@catalog_router.get("/get-items", response_model=CobotCatalogResponse)
async def get_catalog_items():
    request_url = f"{settings.get_catalog_url}{core_constants.COBOT_ID}"
    http_service = HttpRequestService(request_url, settings.kong_auth_key)
    catalog = http_service.get(CobotCatalogResponse)
    if catalog is None:
        raise HTTPException(status_code=404, detail="Error al obtener catalogo")
    updated_items: list[CobotMenuItem] = []
    for item in catalog.items:
        if item.estado:
            updated_items.append(item)
    return CobotCatalogResponse(items=updated_items, total=len(updated_items))
