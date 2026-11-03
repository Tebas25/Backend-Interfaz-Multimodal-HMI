import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings

REQUERIDAS = {
    "get_catalog_url": "http://x/",
    "micro_url": "http://micro/",
    "kong_auth_key": "k",
    "cobot_host": "127.0.0.1",
    "cobot_port": "502",
    "cobot_slave_id": "1",
    "modbus_timeout": "2.0",
    "modbus_retries": "3",
    "polling_interval": "0.2",
    "order_timeout": "120",
    "analytics_events_url": "http://x/analytics/events",
}


@pytest.fixture
def clean_env(monkeypatch):
    for k in (*REQUERIDAS, "PROJECT_NAME", "PROJECT_VERSION"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.fixture
def env_completo(clean_env):
    for k, v in REQUERIDAS.items():
        clean_env.setenv(k, v)
    return clean_env


def test_valores_por_defecto(env_completo):
    s = Settings(_env_file=None)
    assert s.PROJECT_NAME == "Bartender Multimodal HMI"
    assert s.PROJECT_VERSION == "1.0.0"


def test_lee_variables_de_entorno(env_completo):
    env_completo.setenv("get_catalog_url", "http://api/catalog/")
    env_completo.setenv("micro_url", "http://api/micro/")
    env_completo.setenv("kong_auth_key", "secreto")
    s = Settings(_env_file=None)
    assert s.get_catalog_url == "http://api/catalog/"
    assert s.micro_url == "http://api/micro/"
    assert s.kong_auth_key == "secreto"


def test_lee_la_configuracion_del_cobot_con_sus_tipos(env_completo):
    s = Settings(_env_file=None)
    assert s.cobot_host == "127.0.0.1"
    assert s.cobot_port == 502
    assert s.cobot_slave_id == 1
    assert s.modbus_timeout == 2.0
    assert s.modbus_retries == 3
    assert s.polling_interval == 0.2
    assert s.order_timeout == 120.0
    assert s.analytics_events_url == "http://x/analytics/events"


def test_variables_de_entorno_sobrescriben_defaults(env_completo):
    env_completo.setenv("PROJECT_NAME", "Otro")
    assert Settings(_env_file=None).PROJECT_NAME == "Otro"


@pytest.mark.parametrize("faltante", list(REQUERIDAS))
def test_campos_requeridos(clean_env, faltante):
    for k, v in REQUERIDAS.items():
        if k != faltante:
            clean_env.setenv(k, v)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert faltante in str(exc.value)


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("cobot_port", "no-es-numero"),
        ("modbus_timeout", "rapido"),
        ("order_timeout", "mucho"),
    ],
)
def test_valores_con_tipo_invalido_son_rechazados(env_completo, campo, valor):
    env_completo.setenv(campo, valor)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_model_config_apunta_a_dot_env():
    assert Settings.model_config["env_file"] == ".env"


def test_instancia_global_es_settings():
    assert isinstance(settings, Settings)
