from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app import main
from app.main import lifespan
from app.schemas.ws_messages import (
    CloseIngredients,
    Navigate,
    Screen,
    SelectDrink,
    ShowIngredients,
)
from app.services.command_processor import (
    CloseIngredientsAction,
    NavigateAction,
    SelectDrinkAction,
    ShowIngredientsAction,
)


def _servicio_con_close():
    servicio = MagicMock()
    servicio.close = AsyncMock()
    return servicio


@pytest.fixture
def dobles(monkeypatch):
    watcher = MagicMock(name="watcher")
    watcher.stop = AsyncMock()
    watcher.items_activos = []

    listener = MagicMock(name="listener")
    listener.start = AsyncMock(return_value=True)
    listener.stop = AsyncMock()
    listener_cls = MagicMock(return_value=listener)

    publisher = MagicMock(name="publisher")
    publisher.stop = AsyncMock()
    order_service = MagicMock(name="order_service")
    order_service.stop = AsyncMock()

    monkeypatch.setattr(
        main,
        "HttpRequestService",
        MagicMock(side_effect=lambda *a, **k: _servicio_con_close()),
    )
    monkeypatch.setattr(main, "CatalogWatcher", MagicMock(return_value=watcher))
    monkeypatch.setattr(main, "CommandListenerService", listener_cls)
    monkeypatch.setattr(main, "EventPublisher", MagicMock(return_value=publisher))
    monkeypatch.setattr(main, "OrderService", MagicMock(return_value=order_service))
    monkeypatch.setattr(main, "modbus_connection", MagicMock())
    return {"watcher": watcher, "listener": listener, "listener_cls": listener_cls}


@pytest.fixture
async def app_en_marcha(dobles):
    app = FastAPI()
    async with lifespan(app):
        app.state.ws_manager.broadcast = AsyncMock()
        yield app


def _on_action(dobles):
    return dobles["listener_cls"].call_args.kwargs["on_action"]



async def test_el_listener_se_crea_con_on_action_y_get_items(dobles):
    async with lifespan(FastAPI()):
        pass

    kwargs = dobles["listener_cls"].call_args.kwargs
    assert callable(kwargs["on_action"])
    assert callable(kwargs["get_items"])


async def test_el_listener_queda_en_app_state_y_se_inicia(dobles):
    app = FastAPI()

    async with lifespan(app):
        assert app.state.command_listener is dobles["listener"]
        dobles["listener"].start.assert_awaited_once()


async def test_al_apagar_se_detiene_el_listener(dobles):
    async with lifespan(FastAPI()):
        dobles["listener"].stop.assert_not_awaited()

    dobles["listener"].stop.assert_awaited_once()


async def test_get_items_devuelve_las_bebidas_activas_actuales_del_watcher(dobles):
    async with lifespan(FastAPI()):
        get_items = dobles["listener_cls"].call_args.kwargs["get_items"]
        assert get_items() == []

        dobles["watcher"].items_activos = ["mojito", "daiquiri"]

        assert get_items() == ["mojito", "daiquiri"]


async def test_navigate_action_envia_navigate(dobles, app_en_marcha):
    await _on_action(dobles)(NavigateAction(Screen.MENU))

    broadcast = app_en_marcha.state.ws_manager.broadcast
    broadcast.assert_awaited_once()
    mensaje = broadcast.await_args.args[0]
    assert isinstance(mensaje, Navigate)
    assert mensaje.payload.screen is Screen.MENU


async def test_select_drink_action_envia_select_drink_con_el_nombre(
    dobles, app_en_marcha
):
    await _on_action(dobles)(SelectDrinkAction("Piña colada"))

    broadcast = app_en_marcha.state.ws_manager.broadcast
    broadcast.assert_awaited_once()
    mensaje = broadcast.await_args.args[0]
    assert isinstance(mensaje, SelectDrink)
    assert mensaje.payload.name == "Piña colada"


async def test_show_ingredients_action_envia_show_ingredients_con_el_nombre(
    dobles, app_en_marcha
):
    await _on_action(dobles)(ShowIngredientsAction("Mojito"))

    broadcast = app_en_marcha.state.ws_manager.broadcast
    broadcast.assert_awaited_once()
    mensaje = broadcast.await_args.args[0]
    assert isinstance(mensaje, ShowIngredients)
    assert mensaje.payload.name == "Mojito"


async def test_close_ingredients_action_envia_close_ingredients(dobles, app_en_marcha):
    await _on_action(dobles)(CloseIngredientsAction())

    broadcast = app_en_marcha.state.ws_manager.broadcast
    broadcast.assert_awaited_once()
    assert isinstance(broadcast.await_args.args[0], CloseIngredients)


async def test_una_accion_desconocida_no_envia_nada(dobles, app_en_marcha):
    await _on_action(dobles)(object())

    app_en_marcha.state.ws_manager.broadcast.assert_not_awaited()


async def test_cada_accion_envia_un_solo_mensaje_con_su_propio_id(
    dobles, app_en_marcha
):
    on_action = _on_action(dobles)

    await on_action(SelectDrinkAction("Mojito"))
    await on_action(SelectDrinkAction("Mojito"))

    enviados = [
        c.args[0] for c in app_en_marcha.state.ws_manager.broadcast.await_args_list
    ]
    assert len(enviados) == 2
    assert enviados[0].id != enviados[1].id