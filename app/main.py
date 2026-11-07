from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.endpoints import ws_router
from app.api.pay_pages import router as pay_router

# catalog_router
from app.core.config import settings
from app.core.core_constants import COBOT_ID
from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.schemas.ws_messages import (
    build_catalog_update,
    Navigate,
    NavigatePayload,
    SelectDrink,
    DrinkRefPayload,
    ShowIngredients,
    CloseIngredients,
    PaymentResultPayload,
    PaymentResult,
)
from app.services.catalog_watcher_service import CatalogWatcher
from app.services.command_listener_service import CommandListenerService
from app.services.command_processor import (
    NavigateAction,
    SelectDrinkAction,
    ShowIngredientsAction,
    CloseIngredientsAction,
)
from app.services.connection_manager import ConnectionManager
from app.services.http_request_service import HttpRequestService
from app.client.session import modbus_connection
from app.services.cobot_service import cobot_service
from app.services.order_service import OrderService
from app.schemas.events_dto import EventsDTO, TipoEvento
from app.services.publisher import Publisher
from app.services.payment_service import PaymentSession, PaymentStatus, PaymentService
from app.core.core_constants import COBOT_ID, DEFAULT_EVENT_ID
from app.schemas.transactions_dto import TransactionsDTO


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = ConnectionManager()
    app.state.ws_manager = manager

    update_svc = HttpRequestService(
        f"{settings.micro_url}/check-update/{COBOT_ID}",
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

    # --- Publisher de eventos ---
    analytics_svc = HttpRequestService(
        settings.analytics_events_url, authkey=settings.kong_auth_key
    )
    publisher = Publisher[EventsDTO]("event-publisher", analytics_svc)
    app.state.event_publisher = publisher
    publisher.start()
    publisher.publish(
        EventsDTO(
            cobot_id=COBOT_ID,
            evento_id=DEFAULT_EVENT_ID,
            tipo_evento=TipoEvento.INFO_SISTEMA,
            descripcion="Backend multimodal iniciado",
        )
    )

    # --- Publisher de transacciones ---
    transactions_svc = HttpRequestService(
        settings.analytics_transactions_url, authkey=settings.kong_auth_key
    )
    tx_publisher = Publisher[TransactionsDTO](
        "transaction-publisher", transactions_svc, max_retries=5
    )
    app.state.transaction_publisher = tx_publisher
    tx_publisher.start()

    order_service = OrderService(manager, watcher, cobot_service, publisher)
    app.state.order_service = order_service

    async def execute_action(action) -> None:
        match action:
            case NavigateAction(screen=screen):
                await manager.broadcast(
                    Navigate(payload=NavigatePayload(screen=screen))
                )
            case SelectDrinkAction(name=name):
                await manager.broadcast(SelectDrink(payload=DrinkRefPayload(name=name)))
            case ShowIngredientsAction(name=name):
                await manager.broadcast(
                    ShowIngredients(payload=DrinkRefPayload(name=name))
                )
            case CloseIngredientsAction():
                await manager.broadcast(CloseIngredients())

    listener = CommandListenerService(
        on_action=execute_action,
        get_items=lambda: watcher.items_activos,
    )
    app.state.command_listener = listener
    await listener.start()

    async def on_payment_result(session: PaymentSession) -> None:
        await manager.broadcast(
            PaymentResult(
                payload=PaymentResultPayload(
                    payment_id=session.id, status=session.status.value
                )
            )
        )
        if session.status is PaymentStatus.APPROVED:
            print(
                f"[Pago] APROBADO: {session.drink.nombre_item} (modbus={session.drink.codigo_modbus})"
            )
            try:
                tx_publisher.publish(
                    TransactionsDTO(
                        cobot_id=COBOT_ID,
                        evento_id=DEFAULT_EVENT_ID,
                        item=session.drink.nombre_item,
                        ingreso=session.drink.precio_item,
                    )
                )
            except Exception as e:
                print(f"[Pago] No se pudo encolar la transacción: {e}")

            error = order_service.request_order(session.drink.nombre_item)
            if error:
                print(f"[Pedido] No pudo arrancar el cobot: {error}")

    payments = PaymentService(
        settings.PUBLIC_BASE_URL, on_payment_result, settings.PAYMENT_TTL_SECONDS
    )
    app.state.payment_service = payments

    yield

    await order_service.stop()
    publisher.publish(
        EventsDTO(
            cobot_id=COBOT_ID,
            evento_id=DEFAULT_EVENT_ID,
            tipo_evento=TipoEvento.INFO_SISTEMA,
            descripcion="Backend multimodal detenido",
        )
    )
    await tx_publisher.stop()
    await transactions_svc.close()
    await publisher.stop()
    await analytics_svc.close()
    modbus_connection.close()
    await listener.stop()
    await watcher.stop()
    await update_svc.close()
    await catalog_svc.close()
    payments.close()


app = FastAPI(
    title="API Bartender Robótico - Módulo Multimodal",
    description="Estructura base de la API local.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(ws_router)
app.include_router(pay_router)


@app.get("/")
async def root():
    return {"status": "ok", "message": "Estructura base configurada y en línea."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888)
