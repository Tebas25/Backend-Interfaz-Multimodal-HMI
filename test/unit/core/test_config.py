import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("get_catalog_url", "micro_url", "kong_auth_key", "PROJECT_NAME", "PROJECT_VERSION"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


REQUERIDAS = {
    "get_catalog_url": "http://x/",
    "micro_url": "http://micro/",
    "kong_auth_key": "k",
}


def test_valores_por_defecto(clean_env):
    for k, v in REQUERIDAS.items():
        clean_env.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.PROJECT_NAME == "Bartender Multimodal HMI"
    assert s.PROJECT_VERSION == "1.0.0"


def test_lee_variables_de_entorno(clean_env):
    clean_env.setenv("get_catalog_url", "http://api/catalog/")
    clean_env.setenv("micro_url", "http://api/micro/")
    clean_env.setenv("kong_auth_key", "secreto")
    s = Settings(_env_file=None)
    assert s.get_catalog_url == "http://api/catalog/"
    assert s.micro_url == "http://api/micro/"
    assert s.kong_auth_key == "secreto"


def test_variables_de_entorno_sobrescriben_defaults(clean_env):
    for k, v in REQUERIDAS.items():
        clean_env.setenv(k, v)
    clean_env.setenv("PROJECT_NAME", "Otro")
    assert Settings(_env_file=None).PROJECT_NAME == "Otro"


@pytest.mark.parametrize("faltante", ["get_catalog_url", "micro_url", "kong_auth_key"])
def test_campos_requeridos(clean_env, faltante):
    otros = dict(REQUERIDAS)
    otros.pop(faltante)
    for k, v in otros.items():
        clean_env.setenv(k, v)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert faltante in str(exc.value)


def test_model_config_apunta_a_dot_env():
    assert Settings.model_config["env_file"] == ".env"


def test_instancia_global_es_settings():
    assert isinstance(settings, Settings)