from decimal import Decimal

from pydantic import BaseModel


class CobotMenuItem(BaseModel):
    nombre_item: str
    precio_item: Decimal
    estado: bool
    ingredientes: str | None
    codigo_modbus: str | None

    model_config = {"from_attributes": True}
