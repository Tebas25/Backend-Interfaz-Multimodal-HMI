from datetime import datetime

from pydantic import BaseModel, Field
from enum import Enum

from app.schemas.analytics_message_dto import AnalyticsMessage


class TipoEvento(str, Enum):
    INFO_ROBOT = "InfoRobot"
    INFO_SISTEMA = "InfoSistema"
    WARNING = "Warning"
    ERROR_ROBOT = "ErrorRobot"
    ERROR_SISTEMA = "ErrorSistema"


class EventsDTO(AnalyticsMessage):
    codigo: int | None = Field(default=None, exclude=True)
    tipo_evento: TipoEvento
    descripcion: str


class EventosResponseDTO(BaseModel):
    cobot_id: str
    fecha: datetime
    evento_id: str
    tipo_evento: TipoEvento
    descripcion: str


class DrinkOrderRequestDto(BaseModel):
    codigo_modbus: int


class CobotStatusResponseDto(BaseModel):
    codigo: int
    tipo_evento: TipoEvento
    descripcion: str
