from unittest.mock import AsyncMock, MagicMock, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Match

from app import main
from app.core.config import settings
from app.core.core_constants import COBOT_ID
from app.main import app, lifespan
from app.schemas.events_dto import TipoEvento
from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.schemas.ws_messages import Navigate, Screen
from app.services.command_processor import NavigateAction
from app.services.connection_manager import ConnectionManager
from app.services.order_service import OrderService

# Sin `with`, TestClient no ejecuta el lifespan: no se arranca el watcher.
client = TestClient(app)


def test_root_endpoint():
    """
    Prueba de Sanidad: Verifica que la API levanta correctamente
    y responde el mensaje base.
    """
    response = client.get("/")

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok",
        "message": "Estructura base configurada y en línea.",
    }


def test_project_config():
    """Prueba que las variables de entorno/configuración se carguen bien"""
    assert settings.PROJECT_NAME == "Bartender Multimodal HMI"
    assert settings.PROJECT_VERSION == "1.0.0"


def test_metadata_de_la_app():
    assert app.title == "API Bartender Robótico - Módulo Multimodal"
    assert app.version == "1.0.0"


def test_la_app_expone_la_ruta_websocket():
    # Se usa matches() y no route.path: según la versión de FastAPI,
    # include_router envuelve las rutas y el wrapper no tiene `path`.
    scope = {"type": "websocket", "path": "/ws", "root_path": "", "method": None}

    assert any(route.matches(scope)[0] == Match.FULL for route in app.routes)


# ---------- lifespan ----------


@pytest.fixture
def dobles(monkeypatch):
    """Reemplaza servicios HTTP, publicador, watcher y voz por dobles.

    El ConnectionManager y el OrderService son reales: no tocan red ni hardware.
    """
    update_svc = MagicMock(name="update_svc")
    update_svc.close = AsyncMock()
    catalog_svc = MagicMock(name="catalog_svc")
    catalog_svc.close = AsyncMock()
    analytics_svc = MagicMock(name="analytics_svc")
    analytics_svc.close = AsyncMock()
    # El lifespan crea tres clientes HTTP, en este orden
    http_cls = MagicMock(side_effect=[update_svc, catalog_svc, analytics_svc])

    publisher = MagicMock(name="publisher")
    publisher.stop = AsyncMock()
    publisher_cls = MagicMock(return_value=publisher)

    watcher = MagicMock(name="watcher")
    watcher.stop = AsyncMock()
    watcher_cls = MagicMock(return_value=watcher)

    listener = MagicMock(name="listener")
    listener.start = AsyncMock(return_value=True)
    listener.stop = AsyncMock()
    listener_cls = MagicMock(return_value=listener)

    monkeypatch.setattr(main, "HttpRequestService", http_cls)
    monkeypatch.setattr(main, "EventPublisher", publisher_cls)
    monkeypatch.setattr(main, "CatalogWatcher", watcher_cls)
    monkeypatch.setattr(
        main, "CommandListenerService", listener_cls
    )  # nunca el micrófono real
    return {
        "update_svc": update_svc,
        "catalog_svc": catalog_svc,
        "analytics_svc": analytics_svc,
        "http_cls": http_cls,
        "publisher": publisher,
        "publisher_cls": publisher_cls,
        "watcher": watcher,
        "watcher_cls": watcher_cls,
        "listener": listener,
        "listener_cls": listener_cls,
    }


async def test_lifespan_deja_manager_y_watcher_en_app_state(dobles):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        assert isinstance(app_falsa.state.ws_manager, ConnectionManager)
        assert app_falsa.state.catalog_watcher is dobles["watcher"]


async def test_lifespan_crea_los_servicios_http_con_sus_urls_y_authkey(dobles):
    async with lifespan(FastAPI()):
        pass

    assert dobles["http_cls"].call_args_list == [
        call(
            f"{settings.micro_url}/check-update/{COBOT_ID}",
            authkey=settings.kong_auth_key,
        ),
        call(
            f"{settings.get_catalog_url}/{COBOT_ID}",
            authkey=settings.kong_auth_key,
        ),
        call(
            settings.analytics_events_url,
            authkey=settings.kong_auth_key,
        ),
    ]


async def test_lifespan_crea_el_watcher_con_la_configuracion_esperada(dobles):
    async with lifespan(FastAPI()):
        pass

    args, kwargs = dobles["watcher_cls"].call_args
    assert args == (
        dobles["update_svc"],
        dobles["catalog_svc"],
        CobotCatalogResponse,
    )
    assert kwargs["interval"] == 5
    assert callable(kwargs["on_change"])


async def test_lifespan_arranca_el_watcher_al_iniciar(dobles):
    async with lifespan(FastAPI()):
        dobles["watcher"].start.assert_called_once()
        dobles["watcher"].stop.assert_not_awaited()


async def test_lifespan_detiene_watcher_y_cierra_servicios_al_apagar(dobles):
    async with lifespan(FastAPI()):
        pass

    dobles["watcher"].stop.assert_awaited_once()
    dobles["update_svc"].close.assert_awaited_once()
    dobles["catalog_svc"].close.assert_awaited_once()


# ---------- publicador de eventos hacia analítica ----------


async def test_lifespan_crea_el_publicador_con_el_cliente_de_analitica(dobles):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        dobles["publisher_cls"].assert_called_once_with(dobles["analytics_svc"])
        dobles["publisher"].start.assert_called_once()
        assert app_falsa.state.event_publisher is dobles["publisher"]


async def test_lifespan_publica_un_evento_de_sistema_al_iniciar(dobles):
    async with lifespan(FastAPI()):
        dobles["publisher"].publish.assert_called_once()
        evento = dobles["publisher"].publish.call_args.args[0]

    assert evento.evento_id == "SYS_START"
    assert evento.cobot_id == COBOT_ID
    assert evento.tipo_evento is TipoEvento.INFO_SISTEMA


async def test_lifespan_publica_un_evento_de_sistema_al_apagar(dobles):
    async with lifespan(FastAPI()):
        pass

    ultimo = dobles["publisher"].publish.call_args_list[-1].args[0]
    assert ultimo.evento_id == "SYS_STOP"
    assert ultimo.tipo_evento is TipoEvento.INFO_SISTEMA


async def test_lifespan_vacia_el_publicador_y_cierra_su_cliente_al_apagar(dobles):
    async with lifespan(FastAPI()):
        dobles["publisher"].stop.assert_not_awaited()
        dobles["analytics_svc"].close.assert_not_awaited()

    dobles["publisher"].stop.assert_awaited_once()
    dobles["analytics_svc"].close.assert_awaited_once()


# ---------- pedidos al cobot ----------


async def test_lifespan_deja_el_servicio_de_pedidos_en_app_state(dobles):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        assert isinstance(app_falsa.state.order_service, OrderService)


# ---------- callback on_change (broadcast_catalog) ----------


async def test_on_change_hace_broadcast_del_catalogo(dobles, monkeypatch):
    mensaje = MagicMock(name="catalog_update")
    construir = MagicMock(return_value=mensaje)
    monkeypatch.setattr(main, "build_catalog_update", construir)
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        app_falsa.state.ws_manager.broadcast = AsyncMock()
        on_change = dobles["watcher_cls"].call_args.kwargs["on_change"]

        await on_change()

        construir.assert_called_once_with(dobles["watcher"])
        app_falsa.state.ws_manager.broadcast.assert_awaited_once_with(mensaje)


async def test_on_change_no_hace_broadcast_si_no_hay_mensaje(dobles, monkeypatch):
    monkeypatch.setattr(main, "build_catalog_update", MagicMock(return_value=None))
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        app_falsa.state.ws_manager.broadcast = AsyncMock()
        on_change = dobles["watcher_cls"].call_args.kwargs["on_change"]

        await on_change()

        app_falsa.state.ws_manager.broadcast.assert_not_awaited()


# ---------- servicio de control por voz ----------


async def test_lifespan_deja_el_servicio_de_voz_en_app_state(dobles):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        assert app_falsa.state.command_listener is dobles["listener"]


async def test_lifespan_crea_el_servicio_de_voz_con_una_accion_ejecutable(dobles):
    async with lifespan(FastAPI()):
        pass

    dobles["listener_cls"].assert_called_once()
    assert callable(dobles["listener_cls"].call_args.kwargs["on_action"])


async def test_lifespan_arranca_el_servicio_de_voz_al_iniciar(dobles):
    async with lifespan(FastAPI()):
        dobles["listener"].start.assert_awaited_once()
        dobles["listener"].stop.assert_not_awaited()


async def test_lifespan_detiene_el_servicio_de_voz_al_apagar(dobles):
    async with lifespan(FastAPI()):
        pass

    dobles["listener"].stop.assert_awaited_once()


async def test_lifespan_apaga_en_orden_publicador_voz_watcher_y_servicios_http(dobles):
    orden = []
    dobles["publisher"].stop.side_effect = lambda: orden.append("publicador")
    dobles["analytics_svc"].close.side_effect = lambda: orden.append("analitica")
    dobles["listener"].stop.side_effect = lambda: orden.append("voz")
    dobles["watcher"].stop.side_effect = lambda: orden.append("watcher")
    dobles["update_svc"].close.side_effect = lambda: orden.append("update_svc")
    dobles["catalog_svc"].close.side_effect = lambda: orden.append("catalog_svc")

    async with lifespan(FastAPI()):
        pass

    assert orden == [
        "publicador",  # vacía la cola antes de cerrar su cliente HTTP
        "analitica",
        "voz",
        "watcher",
        "update_svc",
        "catalog_svc",
    ]


async def test_lifespan_si_no_hay_microfono_la_app_arranca_y_apaga_igual(dobles):
    dobles["listener"].start.return_value = False  # control por voz deshabilitado
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        assert app_falsa.state.catalog_watcher is dobles["watcher"]

    dobles["listener"].stop.assert_awaited_once()
    dobles["watcher"].stop.assert_awaited_once()


# ---------- acción de voz -> mensaje de navegación ----------


@pytest.mark.parametrize("pantalla", list(Screen))
async def test_la_accion_de_navegar_hace_broadcast_del_mensaje_navigate(
    dobles, pantalla
):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        app_falsa.state.ws_manager.broadcast = AsyncMock()
        on_action = dobles["listener_cls"].call_args.kwargs["on_action"]

        await on_action(NavigateAction(pantalla))

        app_falsa.state.ws_manager.broadcast.assert_awaited_once()
        mensaje = app_falsa.state.ws_manager.broadcast.await_args.args[0]
        assert isinstance(mensaje, Navigate)
        assert mensaje.type == "navigate"
        assert mensaje.payload.screen is pantalla


async def test_una_accion_desconocida_no_envia_nada(dobles):
    app_falsa = FastAPI()

    async with lifespan(app_falsa):
        app_falsa.state.ws_manager.broadcast = AsyncMock()
        on_action = dobles["listener_cls"].call_args.kwargs["on_action"]

        await on_action(object())  # no debe lanzar

        app_falsa.state.ws_manager.broadcast.assert_not_awaited()
