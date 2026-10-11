import pytest

from app.core.config import Settings


@pytest.fixture
def sin_env(monkeypatch):
    for k in ("get_catalog_url", "kong_auth_key", "PROJECT_NAME"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_carga_desde_archivo_env(sin_env, tmp_path):
    env = tmp_path / ".env"
    env.write_text("get_catalog_url=http://desde-env/\nkong_auth_key=abc123\n")
    s = Settings(_env_file=env)
    assert s.get_catalog_url == "http://desde-env/"
    assert s.kong_auth_key == "abc123"


def test_env_del_sistema_tiene_prioridad_sobre_archivo(sin_env, tmp_path):
    env = tmp_path / ".env"
    env.write_text("get_catalog_url=http://archivo/\nkong_auth_key=archivo\n")
    sin_env.setenv("kong_auth_key", "sistema")
    s = Settings(_env_file=env)
    assert s.kong_auth_key == "sistema"
    assert s.get_catalog_url == "http://archivo/"


def test_dot_env_en_directorio_actual(sin_env, tmp_path):
    (tmp_path / ".env").write_text("get_catalog_url=http://cwd/\nkong_auth_key=cwd\n")
    sin_env.chdir(tmp_path)
    s = Settings()  # usa model_config["env_file"] == ".env"
    assert s.get_catalog_url == "http://cwd/"


def test_variables_extra_en_env_son_rechazadas_o_ignoradas(sin_env, tmp_path):
    """Documenta el comportamiento ante claves desconocidas en .env.
    En pydantic-settings v2 por defecto extra='forbid' para dotenv."""
    from pydantic import ValidationError
    env = tmp_path / ".env"
    env.write_text("get_catalog_url=u\nkong_auth_key=k\nOTRA_VAR=1\n")
    try:
        s = Settings(_env_file=env)
        assert not hasattr(s, "OTRA_VAR")
    except ValidationError as e:
        assert "OTRA_VAR".lower() in str(e).lower()


def test_name_personalizado_desde_env(sin_env, tmp_path):
    env = tmp_path / ".env"
    env.write_text("get_catalog_url=u\nkong_auth_key=k\nPROJECT_NAME=Barra\n")
    assert Settings(_env_file=env).PROJECT_NAME == "Barra"