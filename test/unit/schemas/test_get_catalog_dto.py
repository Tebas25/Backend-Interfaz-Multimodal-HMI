import pytest
from pydantic import ValidationError

from app.models.cobot_menu_item import CobotMenuItem
from app.schemas.get_catalog_dto import CobotCatalogResponse


def test_respuesta_valida(make_item):
    resp = CobotCatalogResponse(items=[make_item()], total=1)
    assert resp.total == 1
    assert isinstance(resp.items[0], CobotMenuItem)


def test_lista_vacia_es_valida():
    resp = CobotCatalogResponse(items=[], total=0)
    assert resp.items == []
    assert resp.total == 0


def test_items_dict_se_convierte_a_modelo():
    resp = CobotCatalogResponse(
        items=[{"nombre_item": "A", "precio_item": "1", "estado": True,
                "ingredientes": None, "codigo_modbus": None}],
        total=1,
    )
    assert isinstance(resp.items[0], CobotMenuItem)


@pytest.mark.parametrize("data", [
    {"total": 0},
    {"items": []},
    {"items": "no-lista", "total": 0},
    {"items": [], "total": "abc"},
    {"items": [{"nombre_item": "incompleto"}], "total": 1},
])
def test_datos_invalidos(data):
    with pytest.raises(ValidationError):
        CobotCatalogResponse(**data)


def test_total_no_se_valida_contra_len_items(make_item):
    # Documenta el comportamiento actual: el DTO no verifica consistencia.
    resp = CobotCatalogResponse(items=[make_item()], total=99)
    assert resp.total == 99