from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.endpoints import handle_client_message
from app.schemas.ws_messages import (
    ErrorMessage,
    FrontState,
    OrderPayload,
    OrderRequest,
    Screen,
    StatePayload,
    StateSource,
)
from app.services.screen_state import ScreenState


@pytest.fixture(autouse=True)
def reset_screen():
    ScreenState.reset()
    yield
    ScreenState.reset()


@pytest.fixture
def ws():
    ws = MagicMock()
    ws.app.state.ws_manager.send = AsyncMock()
    ws.app.state.order_service.request_order = MagicMock(return_value=None)
    return ws


def _order(name="Cuba Libre"):
    return OrderRequest(payload=OrderPayload(nombre_item=name))


@pytest.mark.asyncio
class TestHandleClientMessage:
    async def test_state_updates_screen_state(self, ws):
        msg = FrontState(
            payload=StatePayload(screen=Screen.MENU, source=StateSource.TOUCH)
        )
        await handle_client_message(msg, ws)
        assert ScreenState.current is Screen.MENU
        assert ScreenState.source is StateSource.TOUCH

    async def test_order_is_delegated_to_order_service(self, ws):
        await handle_client_message(_order(), ws)
        ws.app.state.order_service.request_order.assert_called_once_with("Cuba Libre")
        ws.app.state.ws_manager.send.assert_not_awaited()

    async def test_rejected_order_sends_error_to_that_client(self, ws):
        ws.app.state.order_service.request_order.return_value = "boom"
        await handle_client_message(_order(), ws)
        ws.app.state.ws_manager.send.assert_awaited_once()
        target, message = ws.app.state.ws_manager.send.await_args.args
        assert target is ws
        assert isinstance(message, ErrorMessage)
        assert message.payload.detail == [{"loc": ["order"], "msg": "boom"}]
