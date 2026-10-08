from unittest.mock import MagicMock

import pytest
import requests
from pydantic import BaseModel, ValidationError

from app.services.http_request_service import HttpRequestService

URL = "http://localhost:9000/get-events"


class Item(BaseModel):
    id: int
    nombre: str


def respuesta_falsa(json_data=None, error=None):
    resp = MagicMock()
    resp.json.return_value = json_data
    if error:
        resp.raise_for_status.side_effect = error
    return resp


@pytest.fixture
def servicio():
    svc = HttpRequestService(URL)
    svc.session = MagicMock()
    return svc


class TestInit:
    def test_guarda_url(self):
        assert HttpRequestService(URL).url == URL

    def test_crea_session(self):
        assert isinstance(HttpRequestService(URL).session, requests.Session)

    def test_sin_authkey_no_agrega_header(self):
        svc = HttpRequestService(URL)
        assert "authkey" not in svc.session.headers

    def test_con_authkey_agrega_header(self):
        svc = HttpRequestService(URL, authkey="secreto")
        assert svc.session.headers["authkey"] == "secreto"


class TestRequest:
    def test_llama_session_con_metodo_url_y_timeout(self, servicio):
        servicio.session.request.return_value = respuesta_falsa({"id": 1, "nombre": "a"})
        servicio._request("GET", Item)
        servicio.session.request.assert_called_once_with("GET", URL, timeout=10)

    def test_reenvia_kwargs(self, servicio):
        servicio.session.request.return_value = respuesta_falsa({"id": 1, "nombre": "a"})
        servicio._request("GET", Item, params={"x": 1}, headers={"h": "v"})
        servicio.session.request.assert_called_once_with(
            "GET", URL, timeout=10, params={"x": 1}, headers={"h": "v"}
        )

    def test_deserializa_objeto(self, servicio):
        servicio.session.request.return_value = respuesta_falsa({"id": 1, "nombre": "a"})
        resultado = servicio._request("GET", Item)
        assert resultado == Item(id=1, nombre="a")

    def test_deserializa_lista(self, servicio):
        servicio.session.request.return_value = respuesta_falsa(
            [{"id": 1, "nombre": "a"}, {"id": 2, "nombre": "b"}]
        )
        resultado = servicio._request("GET", list[Item])
        assert [i.id for i in resultado] == [1, 2]

    def test_http_error_se_propaga(self, servicio):
        servicio.session.request.return_value = respuesta_falsa(
            error=requests.exceptions.HTTPError("500")
        )
        with pytest.raises(requests.exceptions.HTTPError):
            servicio._request("GET", Item)

    def test_respuesta_invalida_lanza_validation_error(self, servicio):
        servicio.session.request.return_value = respuesta_falsa({"id": "abc"})
        with pytest.raises(ValidationError):
            servicio._request("GET", Item)

    def test_timeout_se_propaga(self, servicio):
        servicio.session.request.side_effect = requests.exceptions.Timeout()
        with pytest.raises(requests.exceptions.Timeout):
            servicio._request("GET", Item)


class TestGet:
    def test_usa_metodo_get(self, servicio):
        servicio._request = MagicMock(return_value="ok")
        assert servicio.get(Item, params={"a": 1}) == "ok"
        servicio._request.assert_called_once_with("GET", Item, params={"a": 1})


class TestPost:
    def test_usa_metodo_post_con_json(self, servicio):
        servicio._request = MagicMock(return_value="ok")
        datos = Item(id=1, nombre="a")
        assert servicio.post(Item, datos) == "ok"
        servicio._request.assert_called_once_with(
            "POST", Item, json={"id": 1, "nombre": "a"}
        )