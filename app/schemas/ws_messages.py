from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from app.schemas.get_catalog_dto import CobotCatalogResponse

# ---------- Base y enums ----------


class WsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Screen(StrEnum):
    MENU = "menu"
    WELCOME = "welcome"
    # PREPARANDO = "preparando"
    # LISTO = "listo"


class StateSource(StrEnum):
    TOUCH = "touch"
    BACKEND = "backend"
    INIT = "init"


class Envelope(WsModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    ts: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------- Backend -> Front ----------


class CatalogUpdatePayload(WsModel):
    ultima_actualizacion: str
    catalogo: CobotCatalogResponse


class CatalogUpdate(Envelope):
    type: Literal["catalog_update"] = "catalog_update"
    payload: CatalogUpdatePayload


class NavigatePayload(WsModel):
    screen: Screen


class Navigate(Envelope):
    type: Literal["navigate"] = "navigate"
    payload: NavigatePayload


class ErrorPayload(WsModel):
    detail: list[dict]


class ErrorMessage(Envelope):
    type: Literal["error"] = "error"
    payload: ErrorPayload


ServerMessage = Annotated[
    Union[CatalogUpdate, Navigate, ErrorMessage],
    Field(discriminator="type"),
]


# ---------- Front -> Backend ----------


class StatePayload(WsModel):
    screen: Screen
    source: StateSource
    ref: str | None = None

    @model_validator(mode="after")
    def validar_ref(self):
        if self.source is StateSource.BACKEND and not self.ref:
            raise ValueError("ref es obligatorio cuando source='backend'")
        if self.source is not StateSource.BACKEND and self.ref is not None:
            raise ValueError("ref solo se permite cuando source='backend'")
        return self


class FrontState(Envelope):
    type: Literal["state"] = "state"
    payload: StatePayload


# Hoy hay un solo tipo de mensaje del front. Cuando añadas otro:
# ClientMessage = Annotated[Union[FrontState, OtroMensaje], Field(discriminator="type")]
ClientMessage = FrontState
client_adapter = TypeAdapter(ClientMessage)


def build_catalog_update(watcher) -> CatalogUpdate | None:
    if watcher.catalogo is None or watcher.ultima_actualizacion is None:
        return None  # todavía no hay catálogo descargado

    activos = watcher.items_activos
    return CatalogUpdate(
        payload=CatalogUpdatePayload(
            ultima_actualizacion=watcher.ultima_actualizacion,
            catalogo=CobotCatalogResponse(items=activos, total=len(activos)),
        )
    )
