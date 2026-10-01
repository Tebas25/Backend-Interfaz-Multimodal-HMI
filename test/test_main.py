from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_root_endpoint():
    """
    Prueba de Sanidad: Verifica que la API levanta correctamente
    y responde el mensaje base.
    """
    response = client.get("/")

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok",
        "message": "Estructura base configurada y en línea.",
    }


def test_project_config():
    """Prueba que las variables de entorno/configuración se carguen bien"""
    assert settings.PROJECT_NAME == "Bartender Multimodal HMI"
    assert settings.PROJECT_VERSION == "1.0.0"
