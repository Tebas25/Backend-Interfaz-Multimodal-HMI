"""Configuración global de pytest."""
import os

os.environ.setdefault("get_catalog_url", "http://fake-kong/catalog/")
os.environ.setdefault("kong_auth_key", "test-key")

from decimal import Decimal

import pytest

from app.models.cobot_menu_item import CobotMenuItem


@pytest.fixture
def make_item():
    def _make(nombre="Mojito", precio="5.50", estado=True,
              ingredientes="Ron, menta", codigo="0x01"):
        return CobotMenuItem(
            nombre_item=nombre,
            precio_item=Decimal(precio),
            estado=estado,
            ingredientes=ingredientes,
            codigo_modbus=codigo,
        )
    return _make