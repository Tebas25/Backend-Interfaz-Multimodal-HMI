from decimal import Decimal

from pydantic import BaseModel


class CobotMenuItem(BaseModel):
    nombre_item: str
    precio_item: Decimal
    imagen: str | None
    estado: bool
    ingredientes: str | None
    codigo_modbus: int | None

    model_config = {"from_attributes": True}
