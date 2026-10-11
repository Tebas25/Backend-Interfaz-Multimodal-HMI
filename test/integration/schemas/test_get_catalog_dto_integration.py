"""Integración del DTO: (de)serialización anidada y uso en FastAPI."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.get_catalog_dto import CobotCatalogResponse


def test_roundtrip_json_anidado(make_item):
    original = CobotCatalogResponse(items=[make_item(), make_item(nombre="Daiquiri")],
                                    total=2)
    restored = CobotCatalogResponse.model_validate_json(original.model_dump_json())
    assert restored == original
    assert [i.nombre_item for i in restored.items] == ["Mojito", "Daiquiri"]


def test_parseo_de_payload_externo_tipo_kong():
    payload = {
        "items": [
            {"nombre_item": "Mojito", "precio_item": 5.5, "estado": True,
             "ingredientes": "Ron", "codigo_modbus": "0x01"},
            {"nombre_item": "Agua", "precio_item": "1.00", "estado": False,
             "ingredientes": None, "codigo_modbus": None},
        ],
        "total": 2,
    }
    resp = CobotCatalogResponse.model_validate(payload)
    assert resp.total == 2
    assert resp.items[1].estado is False


def test_como_response_model_filtra_y_valida(make_item):
    app = FastAPI()

    @app.get("/c", response_model=CobotCatalogResponse)
    def c():
        return CobotCatalogResponse(items=[make_item()], total=1)

    res = TestClient(app).get("/c")
    assert res.status_code == 200
    assert set(res.json()) == {"items", "total"}
    assert res.json()["items"][0]["nombre_item"] == "Mojito"


def test_esquema_openapi_referencia_el_item():
    app = FastAPI()

    @app.get("/c", response_model=CobotCatalogResponse)
    def c(): ...

    schemas = app.openapi()["components"]["schemas"]
    assert "CobotCatalogResponse" in schemas
    assert "CobotMenuItem" in schemas