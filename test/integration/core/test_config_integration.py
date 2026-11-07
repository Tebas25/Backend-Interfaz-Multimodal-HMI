import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {
    "get_catalog_url": "http://desde-env/",
    "micro_url": "http://micro-env/",
    "kong_auth_key": "abc123",
    "cobot_host": "127.0.0.1",
    "cobot_port": "502",
    "cobot_slave_id": "1",
    "modbus_timeout": "2.0",
    "modbus_retries": "3",
    "polling_interval": "0.2",
    "order_timeout": "120",
    "analytics_events_url": "http://analitica-env/events",
    "analytics_transactions_url": "http://analitica-env/transactions",
}


def contenido_env(**cambios) -> str:
    return "".join(f"{k}={v}\n" for k, v in {**BASE, **cambios}.items())


@pytest.fixture
def sin_env(monkeypatch):
    for k in (*BASE, "PROJECT_NAME"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_carga_desde_archivo_env(sin_env, tmp_path):
    env = tmp_path / ".env"
    env.write_text(contenido_env())
    s = Settings(_env_file=env)
    assert s.get_catalog_url == "http://desde-env/"
    assert s.micro_url == "http://micro-env/"
    assert s.kong_auth_key == "abc123"
    assert s.cobot_port == 502
    assert s.polling_interval == 0.2
    assert s.analytics_events_url == "http://analitica-env/events"
    assert s.analytics_transactions_url == "http://analitica-env/transactions"


def test_env_del_sistema_tiene_prioridad_sobre_archivo(sin_env, tmp_path):
    env = tmp_path / ".env"
    env.write_text(contenido_env(kong_auth_key="archivo"))
    sin_env.setenv("kong_auth_key", "sistema")
    s = Settings(_env_file=env)
    assert s.kong_auth_key == "sistema"
    assert s.get_catalog_url == "http://desde-env/"


def test_dot_env_en_directorio_actual(sin_env, tmp_path):
    (tmp_path / ".env").write_text(
        contenido_env(get_catalog_url="http://cwd/", micro_url="http://micro-cwd/")
    )
    sin_env.chdir(tmp_path)
    s = Settings()  # usa model_config["env_file"] == ".env"
    assert s.get_catalog_url == "http://cwd/"
    assert s.micro_url == "http://micro-cwd/"


def test_variables_extra_en_env_son_rechazadas_o_ignoradas(sin_env, tmp_path):
    """Documenta el comportamiento ante claves desconocidas en .env.
    En pydantic-settings v2 por defecto extra='forbid' para dotenv."""
    env = tmp_path / ".env"
    env.write_text(contenido_env() + "OTRA_VAR=1\n")
    try:
        s = Settings(_env_file=env)
        assert not hasattr(s, "OTRA_VAR")
    except ValidationError as e:
        assert "OTRA_VAR".lower() in str(e).lower()


def test_name_personalizado_desde_env(sin_env, tmp_path):
    env = tmp_path / ".env"
    env.write_text(contenido_env() + "PROJECT_NAME=Barra\n")
    assert Settings(_env_file=env).PROJECT_NAME == "Barra"


def test_un_env_incompleto_falla_nombrando_lo_que_falta(sin_env, tmp_path):
    env = tmp_path / ".env"
    env.write_text("get_catalog_url=u\nmicro_url=m\nkong_auth_key=k\n")
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=env)
    for campo in (
        "cobot_host",
        "order_timeout",
        "analytics_events_url",
        "analytics_transactions_url",
    ):
        assert campo in str(exc.value)
