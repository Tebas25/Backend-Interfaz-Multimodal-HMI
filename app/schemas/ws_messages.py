from datetime import datetime, timezone
from decimal import Decimal
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
from app.schemas.events_dto import TipoEvento

# ---------- Base y enums ----------


class WsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyPayload(WsModel):
    pass


class Screen(StrEnum):
    MENU = "menu"
    WELCOME = "welcome"
    PAYMENT = "payment"
    PAYMENT_RESULT = "payment_result"


class StateSource(StrEnum):
    TOUCH = "touch"
    BACKEND = "backend"
    INIT = "init"


class Envelope(WsModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    ts: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------- Backend -> Front ----------
class DrinkRefPayload(WsModel):
    name: str


class SelectDrink(Envelope):
    type: Literal["select_drink"] = "select_drink"
    payload: DrinkRefPayload


class ShowIngredients(Envelope):
    type: Literal["show_ingredients"] = "show_ingredients"
    payload: DrinkRefPayload


class CloseIngredients(Envelope):
    type: Literal["close_ingredients"] = "close_ingredients"
    payload: EmptyPayload = Field(default_factory=EmptyPayload)


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


class CobotStatusPayload(WsModel):
    codigo: int
    tipo_evento: TipoEvento
    descripcion: str


class CobotStatus(Envelope):
    type: Literal["cobot_status"] = "cobot_status"
    payload: CobotStatusPayload


class PaymentStartedPayload(WsModel):
    payment_id: str
    pay_url: str
    drink_name: str
    price: Decimal


class PaymentStarted(Envelope):
    type: Literal["payment_started"] = "payment_started"
    payload: PaymentStartedPayload


class PaymentResultPayload(WsModel):
    payment_id: str | None = None
    status: Literal["approved", "rejected", "expired", "error"]
    reason: str | None = None


class PaymentResult(Envelope):
    type: Literal["payment_result"] = "payment_result"
    payload: PaymentResultPayload


ServerMessage = Annotated[
    Union[
        CatalogUpdate,
        Navigate,
        ErrorMessage,
        CobotStatus,
        SelectDrink,
        ShowIngredients,
        CloseIngredients,
        PaymentStarted,
        PaymentResult,
    ],
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


class OrderPayload(WsModel):
    nombre_item: str


class OrderRequest(Envelope):
    type: Literal["order"] = "order"
    payload: OrderPayload


class StartPaymentPayload(WsModel):
    drink: str = Field(min_length=1, max_length=100)


class StartPayment(Envelope):
    type: Literal["start_payment"] = "start_payment"
    payload: StartPaymentPayload


class CancelPaymentPayload(WsModel):
    payment_id: str | None = None


class CancelPayment(Envelope):
    type: Literal["cancel_payment"] = "cancel_payment"
    payload: CancelPaymentPayload


ClientMessage = Annotated[
    Union[FrontState, OrderRequest, StartPayment, CancelPayment],
    Field(discriminator="type"),
]
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
