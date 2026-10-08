"""Integración de HttpRequestService contra un servidor HTTP real local
(sin mocks): se verifican headers, parámetros, JSON y errores."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from pydantic import ValidationError

from app.schemas.events_dto import EventsDTO, EventosResponseDTO, TipoEvento
from app.services.http_request_service import HttpRequestService

AUTHKEY = "clave-de-prueba"
EVENTO = {
    "cobot_id": "cobot-1",
    "fecha": "2026-01-15T10:30:00",
    "evento_id": "ev-1",
    "tipo_evento": "Warning",
    "descripcion": "Temperatura alta",
}


class Handler(BaseHTTPRequestHandler):
    ultima_peticion = {}

    def log_message(self, *args):
        pass

    def _responder(self, codigo, cuerpo):
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _registrar(self, cuerpo=None):
        url = urlparse(self.path)
        Handler.ultima_peticion = {
            "path": url.path,
            "query": parse_qs(url.query),
            "headers": dict(self.headers),
            "body": cuerpo,
        }

    def do_GET(self):
        self._registrar()
        ruta = urlparse(self.path).path
        if self.headers.get("authkey") != AUTHKEY:
            return self._responder(401, {"detail": "no autorizado"})
        if ruta == "/get-events":
            if "cobot_id" not in Handler.ultima_peticion["query"]:
                return self._responder(422, {"detail": "falta cobot_id"})
            return self._responder(200, [EVENTO])
        if ruta == "/invalido":
            return self._responder(200, {"cobot_id": "x"})
        return self._responder(404, {"detail": "no existe"})

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(largo))
        self._registrar(cuerpo)
        if self.headers.get("authkey") != AUTHKEY:
            return self._responder(401, {"detail": "no autorizado"})
        return self._responder(200, {**EVENTO, **{
            k: cuerpo[k] for k in ("cobot_id", "evento_id", "tipo_evento", "descripcion")
        }})


@pytest.fixture(scope="module")
def base_url():
    servidor = HTTPServer(("127.0.0.1", 0), Handler)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{servidor.server_port}"
    servidor.shutdown()
    servidor.server_close()


def test_get_lista_de_eventos(base_url):
    svc = HttpRequestService(f"{base_url}/get-events", authkey=AUTHKEY)
    eventos = svc.get(list[EventosResponseDTO], params={"cobot_id": "cobot-1"})
    assert len(eventos) == 1
    assert isinstance(eventos[0], EventosResponseDTO)
    assert eventos[0].tipo_evento is TipoEvento.WARNING


def test_get_envia_header_authkey_y_params(base_url):
    svc = HttpRequestService(f"{base_url}/get-events", authkey=AUTHKEY)
    svc.get(
        list[EventosResponseDTO],
        params={"cobot_id": "cobot-1", "tipo_evento": ["Warning", "ErrorRobot"]},
    )
    peticion = Handler.ultima_peticion
    assert peticion["headers"]["authkey"] == AUTHKEY
    assert peticion["query"]["cobot_id"] == ["cobot-1"]
    assert peticion["query"]["tipo_evento"] == ["Warning", "ErrorRobot"]


def test_get_sin_authkey_devuelve_401(base_url):
    svc = HttpRequestService(f"{base_url}/get-events")
    with pytest.raises(requests.exceptions.HTTPError) as exc:
        svc.get(list[EventosResponseDTO], params={"cobot_id": "cobot-1"})
    assert exc.value.response.status_code == 401


def test_get_sin_parametro_obligatorio_devuelve_422(base_url):
    svc = HttpRequestService(f"{base_url}/get-events", authkey=AUTHKEY)
    with pytest.raises(requests.exceptions.HTTPError) as exc:
        svc.get(list[EventosResponseDTO])
    assert exc.value.response.status_code == 422


def test_get_ruta_inexistente_devuelve_404(base_url):
    svc = HttpRequestService(f"{base_url}/nada", authkey=AUTHKEY)
    with pytest.raises(requests.exceptions.HTTPError) as exc:
        svc.get(list[EventosResponseDTO])
    assert exc.value.response.status_code == 404


def test_respuesta_con_forma_inesperada_lanza_validation_error(base_url):
    svc = HttpRequestService(f"{base_url}/invalido", authkey=AUTHKEY)
    with pytest.raises(ValidationError):
        svc.get(EventosResponseDTO)


def test_post_envia_json_y_deserializa_respuesta(base_url):
    svc = HttpRequestService(f"{base_url}/events", authkey=AUTHKEY)
    dto = EventsDTO(
        cobot_id="cobot-9",
        evento_id="ev-9",
        tipo_evento=TipoEvento.ERROR_ROBOT,
        descripcion="falla de motor",
    )
    resultado = svc.post(EventosResponseDTO, dto)
    assert Handler.ultima_peticion["body"] == {
        "cobot_id": "cobot-9",
        "evento_id": "ev-9",
        "tipo_evento": "ErrorRobot",
        "descripcion": "falla de motor",
    }
    assert resultado.cobot_id == "cobot-9"
    assert resultado.tipo_evento is TipoEvento.ERROR_ROBOT


def test_post_sin_authkey_devuelve_401(base_url):
    svc = HttpRequestService(f"{base_url}/events")
    dto = EventsDTO(
        cobot_id="c", evento_id="e", tipo_evento=TipoEvento.INFO_ROBOT, descripcion="d"
    )
    with pytest.raises(requests.exceptions.HTTPError):
        svc.post(EventosResponseDTO, dto)


def test_conexion_rechazada():
    svc = HttpRequestService("http://127.0.0.1:1/x")
    with pytest.raises(requests.exceptions.ConnectionError):
        svc.get(EventosResponseDTO)