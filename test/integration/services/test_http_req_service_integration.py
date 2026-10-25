"""Integración de HttpRequestService contra un servidor HTTP real local
(sin mocks): se verifican headers, parámetros, JSON y errores.

El servidor corre en un hilo; el cliente es httpx.AsyncClient."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
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


@pytest.fixture
async def crear_servicio():
    """Fábrica de servicios que garantiza cerrar cada cliente httpx."""
    creados = []

    def _crear(url, authkey=None):
        svc = HttpRequestService(url, authkey=authkey)
        creados.append(svc)
        return svc

    yield _crear
    for svc in creados:
        await svc.close()


async def test_get_lista_de_eventos(base_url, crear_servicio):
    svc = crear_servicio(f"{base_url}/get-events", AUTHKEY)

    eventos = await svc.get(list[EventosResponseDTO], params={"cobot_id": "cobot-1"})

    assert len(eventos) == 1
    assert isinstance(eventos[0], EventosResponseDTO)
    assert eventos[0].tipo_evento is TipoEvento.WARNING


async def test_get_envia_header_authkey_y_params(base_url, crear_servicio):
    svc = crear_servicio(f"{base_url}/get-events", AUTHKEY)

    await svc.get(
        list[EventosResponseDTO],
        params={"cobot_id": "cobot-1", "tipo_evento": ["Warning", "ErrorRobot"]},
    )

    peticion = Handler.ultima_peticion
    assert peticion["headers"]["authkey"] == AUTHKEY
    assert peticion["query"]["cobot_id"] == ["cobot-1"]
    assert peticion["query"]["tipo_evento"] == ["Warning", "ErrorRobot"]


async def test_get_sin_authkey_devuelve_401(base_url, crear_servicio):
    svc = crear_servicio(f"{base_url}/get-events")

    with pytest.raises(httpx.HTTPStatusError) as exc:
        await svc.get(list[EventosResponseDTO], params={"cobot_id": "cobot-1"})

    assert exc.value.response.status_code == 401


async def test_get_sin_parametro_obligatorio_devuelve_422(base_url, crear_servicio):
    svc = crear_servicio(f"{base_url}/get-events", AUTHKEY)

    with pytest.raises(httpx.HTTPStatusError) as exc:
        await svc.get(list[EventosResponseDTO])

    assert exc.value.response.status_code == 422


async def test_get_ruta_inexistente_devuelve_404(base_url, crear_servicio):
    svc = crear_servicio(f"{base_url}/nada", AUTHKEY)

    with pytest.raises(httpx.HTTPStatusError) as exc:
        await svc.get(list[EventosResponseDTO])

    assert exc.value.response.status_code == 404


async def test_respuesta_con_forma_inesperada_lanza_validation_error(
    base_url, crear_servicio
):
    svc = crear_servicio(f"{base_url}/invalido", AUTHKEY)

    with pytest.raises(ValidationError):
        await svc.get(EventosResponseDTO)


async def test_post_envia_json_y_deserializa_respuesta(base_url, crear_servicio):
    svc = crear_servicio(f"{base_url}/events", AUTHKEY)
    dto = EventsDTO(
        cobot_id="cobot-9",
        evento_id="ev-9",
        tipo_evento=TipoEvento.ERROR_ROBOT,
        descripcion="falla de motor",
    )

    resultado = await svc.post(EventosResponseDTO, dto)

    assert Handler.ultima_peticion["body"] == {
        "cobot_id": "cobot-9",
        "evento_id": "ev-9",
        "tipo_evento": "ErrorRobot",
        "descripcion": "falla de motor",
    }
    assert resultado.cobot_id == "cobot-9"
    assert resultado.tipo_evento is TipoEvento.ERROR_ROBOT


async def test_post_sin_authkey_devuelve_401(base_url, crear_servicio):
    svc = crear_servicio(f"{base_url}/events")
    dto = EventsDTO(
        cobot_id="c", evento_id="e", tipo_evento=TipoEvento.INFO_ROBOT, descripcion="d"
    )

    with pytest.raises(httpx.HTTPStatusError) as exc:
        await svc.post(EventosResponseDTO, dto)

    assert exc.value.response.status_code == 401


async def test_conexion_rechazada(crear_servicio):
    svc = crear_servicio("http://127.0.0.1:1/x")

    with pytest.raises(httpx.ConnectError):
        await svc.get(EventosResponseDTO)