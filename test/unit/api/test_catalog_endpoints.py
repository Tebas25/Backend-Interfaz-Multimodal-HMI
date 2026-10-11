import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

EP = "app.api.endpoints"

import importlib

ep = importlib.import_module(EP)

from app.schemas.get_catalog_dto import CobotCatalogResponse


@pytest.fixture
def http_cls():
    with patch(f"{EP}.HttpRequestService") as cls:
        yield cls


def run():
    return asyncio.run(ep.get_catalog_items())


def test_construye_url_y_llama_al_servicio(http_cls, monkeypatch, make_item):
    monkeypatch.setattr(ep.settings, "get_catalog_url", "http://kong/catalog/")
    monkeypatch.setattr(ep.settings, "kong_auth_key", "KEY")
    monkeypatch.setattr(ep.core_constants, "COBOT_ID", "cobot-7")
    http_cls.return_value.get.return_value = CobotCatalogResponse(
        items=[make_item()], total=1)

    run()

    http_cls.assert_called_once_with("http://kong/catalog/cobot-7", "KEY")
    http_cls.return_value.get.assert_called_once_with(CobotCatalogResponse)


def test_catalogo_none_lanza_404(http_cls):
    http_cls.return_value.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        run()
    assert exc.value.status_code == 404
    assert exc.value.detail == "Error al obtener catalogo"


def test_filtra_items_inactivos(http_cls, make_item):
    http_cls.return_value.get.return_value = CobotCatalogResponse(
        items=[make_item("A", estado=True), make_item("B", estado=False),
               make_item("C", estado=True)],
        total=3)
    res = run()
    assert [i.nombre_item for i in res.items] == ["A", "C"]
    assert res.total == 2


def test_todos_inactivos_devuelve_vacio(http_cls, make_item):
    http_cls.return_value.get.return_value = CobotCatalogResponse(
        items=[make_item(estado=False)], total=1)
    res = run()
    assert res.items == [] and res.total == 0


def test_catalogo_vacio(http_cls):
    http_cls.return_value.get.return_value = CobotCatalogResponse(items=[], total=0)
    res = run()
    assert res.items == [] and res.total == 0


def test_total_se_recalcula_no_se_copia(http_cls, make_item):
    http_cls.return_value.get.return_value = CobotCatalogResponse(
        items=[make_item()], total=500)
    assert run().total == 1


def test_excepcion_del_servicio_se_propaga(http_cls):
    http_cls.return_value.get.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        run()


def test_router_configuracion():
    assert ep.catalog_router.prefix == "/catalog"
    assert "catalog" in ep.catalog_router.tags
    paths = {r.path for r in ep.catalog_router.routes}
    assert "/catalog/get-items" in paths