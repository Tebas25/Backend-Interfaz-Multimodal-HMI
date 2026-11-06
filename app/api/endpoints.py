from fastapi import APIRouter
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.schemas.ws_messages import (
    build_catalog_update,
    FrontState,
    OrderRequest,
    client_adapter,
    ErrorMessage,
    ErrorPayload,
    StartPayment,
    CancelPayment,
    PaymentResult,
    PaymentResultPayload,
    PaymentStarted,
    PaymentStartedPayload,
)
from app.services.screen_state import ScreenState

ws_router = APIRouter()


async def handle_client_message(msg, ws: WebSocket) -> None:
    match msg:
        case FrontState():
            ScreenState.update(msg.payload)
        case OrderRequest():
            error = ws.app.state.order_service.request_order(msg.payload.nombre_item)
            if error:
                await ws.app.state.ws_manager.send(
                    ws,
                    ErrorMessage(
                        payload=ErrorPayload(detail=[{"loc": ["order"], "msg": error}])
                    ),
                )
        case StartPayment():
            await start_payment(msg.payload.drink, ws)
        case CancelPayment():
            ws.app.state.payment_service.cancel(msg.payload.payment_id)


async def start_payment(drink_name: str, ws: WebSocket) -> None:
    state = ws.app.state
    drink = next(
        (
            i
            for i in state.catalog_watcher.items_activos
            if i.nombre_item.casefold() == drink_name.casefold()
        ),
        None,
    )
    if drink is None:  # se desactivó mientras el usuario elegía
        await state.ws_manager.send(
            ws,
            PaymentResult(
                payload=PaymentResultPayload(status="error", reason="drink_unavailable")
            ),
        )
        return

    session = state.payment_service.start(drink)
    url = state.payment_service.pay_url(session)
    print(f"[Pago] iniciado {drink.nombre_item} ${session.price} -> {url}")
    await state.ws_manager.send(
        ws,
        PaymentStarted(
            payload=PaymentStartedPayload(
                payment_id=session.id,
                pay_url=url,
                drink_name=drink.nombre_item,
                price=session.price,
            )
        ),
    )


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
            await handle_client_message(msg, ws)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
