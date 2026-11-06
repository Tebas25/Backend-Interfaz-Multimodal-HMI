import pytest
from pydantic import ValidationError

from app.core.config import Settings

OBLIGATORIAS = {
    "get_catalog_url": "http://kong/catalog",
    "micro_url": "http://kong/micro/",
    "kong_auth_key": "k",
    "cobot_host": "127.0.0.1",
    "cobot_port": "502",
    "cobot_slave_id": "1",
    "modbus_timeout": "1",
    "modbus_retries": "1",
    "polling_interval": "0.1",
    "order_timeout": "1",
    "analytics_events_url": "http://kong/events",
    "PUBLIC_BASE_URL": "http://192.168.0.10:8888",
    "PAYMENT_TTL_SECONDS": "120",
}


@pytest.fixture
def entorno(monkeypatch):

    for k, v in OBLIGATORIAS.items():
        monkeypatch.setenv(k, v)
    return monkeypatch


def test_lee_la_url_publica_y_el_ttl_del_entorno(entorno):
    entorno.setenv("PUBLIC_BASE_URL", "http://10.0.0.5:9000")
    entorno.setenv("PAYMENT_TTL_SECONDS", "45")

    s = Settings(_env_file=None)

    assert s.PUBLIC_BASE_URL == "http://10.0.0.5:9000"
    assert s.PAYMENT_TTL_SECONDS == 45
    assert isinstance(s.PAYMENT_TTL_SECONDS, int)


@pytest.mark.parametrize("faltante", ["PUBLIC_BASE_URL", "PAYMENT_TTL_SECONDS"])
def test_son_obligatorias(entorno, faltante):
    entorno.delenv(faltante)

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    assert faltante in str(exc.value)


@pytest.mark.parametrize("valor", ["abc", "", "1.5x"])
def test_el_ttl_debe_ser_numerico(entorno, valor):
    entorno.setenv("PAYMENT_TTL_SECONDS", valor)

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    assert "PAYMENT_TTL_SECONDS" in str(exc.value)


def test_la_configuracion_global_expone_los_ajustes_de_pago():
    from app.core.config import settings

    assert isinstance(settings.PUBLIC_BASE_URL, str) and settings.PUBLIC_BASE_URL
    assert isinstance(settings.PAYMENT_TTL_SECONDS, int)