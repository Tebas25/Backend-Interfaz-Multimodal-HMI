import importlib
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.get_catalog_dto import CobotCatalogResponse

EP = "app.api.endpoints"
ep = importlib.import_module(EP)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ep.catalog_router)
    return TestClient(app)


@pytest.fixture
def servicio():
    with patch(f"{EP}.HttpRequestService") as cls:
        yield cls


def test_get_items_200_filtra_inactivos(client, servicio, make_item):
    servicio.return_value.get.return_value = CobotCatalogResponse(
        items=[make_item("Mojito"), make_item("Viejo", estado=False)], total=2)

    res = client.get("/catalog/get-items")

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["nombre_item"] == "Mojito"
    assert Decimal(str(body["items"][0]["precio_item"])) == Decimal("5.50")


def test_get_items_404_si_servicio_devuelve_none(client, servicio):
    servicio.return_value.get.return_value = None
    res = client.get("/catalog/get-items")
    assert res.status_code == 404
    assert res.json() == {"detail": "Error al obtener catalogo"}


def test_usa_settings_y_cobot_id_reales(client, servicio, make_item):
    servicio.return_value.get.return_value = CobotCatalogResponse(items=[], total=0)
    client.get("/catalog/get-items")
    url, key = servicio.call_args.args
    assert url == f"{ep.settings.get_catalog_url}{ep.core_constants.COBOT_ID}"
    assert key == ep.settings.kong_auth_key


def test_catalogo_vacio_200(client, servicio):
    servicio.return_value.get.return_value = CobotCatalogResponse(items=[], total=0)
    res = client.get("/catalog/get-items")
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}


def test_metodo_no_permitido(client):
    assert client.post("/catalog/get-items").status_code == 405


def test_ruta_inexistente(client):
    assert client.get("/catalog/otra").status_code == 404


def test_error_inesperado_del_servicio_da_500(servicio):
    servicio.return_value.get.side_effect = RuntimeError("red caída")
    app = FastAPI()
    app.include_router(ep.catalog_router)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/catalog/get-items").status_code == 500


def test_openapi_expone_la_ruta(client):
    spec = client.get("/openapi.json").json()
    assert "/catalog/get-items" in spec["paths"]
    assert "get" in spec["paths"]["/catalog/get-items"]