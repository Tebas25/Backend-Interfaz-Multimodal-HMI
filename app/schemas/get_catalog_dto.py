from pydantic import BaseModel

from app.models.cobot_menu_item import CobotMenuItem


class CobotCatalogResponse(BaseModel):
    items: list[CobotMenuItem]
    total: int
