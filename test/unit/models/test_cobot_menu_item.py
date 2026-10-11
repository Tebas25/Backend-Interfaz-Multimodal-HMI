from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.cobot_menu_item import CobotMenuItem

VALID = {
    "nombre_item": "Mojito",
    "precio_item": "5.50",
    "estado": True,
    "ingredientes": "Ron, menta",
    "codigo_modbus": "0x01",
}


def test_crea_item_valido():
    item = CobotMenuItem(**VALID)
    assert item.nombre_item == "Mojito"
    assert item.estado is True


def test_precio_se_convierte_a_decimal():
    item = CobotMenuItem(**VALID)
    assert isinstance(item.precio_item, Decimal)
    assert item.precio_item == Decimal("5.50")


@pytest.mark.parametrize("campo", ["ingredientes", "codigo_modbus"])
def test_campos_opcionales_aceptan_none(campo):
    item = CobotMenuItem(**{**VALID, campo: None})
    assert getattr(item, campo) is None


@pytest.mark.parametrize("campo", ["nombre_item", "precio_item", "estado",
                                   "ingredientes", "codigo_modbus"])
def test_todos_los_campos_son_requeridos(campo):
    # `str | None` sin default sigue siendo requerido en pydantic v2
    data = {k: v for k, v in VALID.items() if k != campo}
    with pytest.raises(ValidationError):
        CobotMenuItem(**data)


@pytest.mark.parametrize("campo,valor", [
    ("precio_item", "abc"),
    ("estado", "no-es-bool"),
    ("nombre_item", None),
])
def test_tipos_invalidos_lanzan_error(campo, valor):
    with pytest.raises(ValidationError):
        CobotMenuItem(**{**VALID, campo: valor})


def test_model_config_from_attributes():
    assert CobotMenuItem.model_config.get("from_attributes") is True