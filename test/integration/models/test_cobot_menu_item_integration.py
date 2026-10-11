"""Integración del modelo con objetos tipo ORM, JSON y FastAPI."""
import json
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.cobot_menu_item import CobotMenuItem


def test_from_attributes_con_objeto_orm():
    orm_obj = SimpleNamespace(nombre_item="Margarita", precio_item=Decimal("7.25"),
                              estado=False, ingredientes=None, codigo_modbus="0x02")
    item = CobotMenuItem.model_validate(orm_obj)
    assert item.nombre_item == "Margarita"
    assert item.precio_item == Decimal("7.25")
    assert item.ingredientes is None


def test_roundtrip_json(make_item):
    original = make_item()
    restored = CobotMenuItem.model_validate_json(original.model_dump_json())
    assert restored == original


def test_decimal_se_serializa_sin_perder_precision(make_item):
    data = json.loads(make_item(precio="12.50").model_dump_json())
    assert Decimal(str(data["precio_item"])) == Decimal("12.50")


def test_funciona_como_response_model_en_fastapi(make_item):
    app = FastAPI()

    @app.get("/item", response_model=CobotMenuItem)
    def item():
        return make_item()

    res = TestClient(app).get("/item")
    assert res.status_code == 200
    body = res.json()
    assert body["nombre_item"] == "Mojito"
    assert Decimal(str(body["precio_item"])) == Decimal("5.50")


def test_funciona_como_body_en_fastapi():
    app = FastAPI()

    @app.post("/item")
    def crear(item: CobotMenuItem):
        return {"nombre": item.nombre_item}

    client = TestClient(app)
    ok = client.post("/item", json={"nombre_item": "X", "precio_item": "1.0",
                                    "estado": True, "ingredientes": None,
                                    "codigo_modbus": None})
    bad = client.post("/item", json={"nombre_item": "X"})
    assert ok.status_code == 200
    assert bad.status_code == 422