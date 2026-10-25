"""Pruebas unitarias de HttpRequestService (versión asíncrona con httpx).

El cliente httpx se reemplaza por un mock: no hay red.
"""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.services.http_request_service import HttpRequestService

URL = "http://localhost:9000/get-events"


class Item(BaseModel):
    id: int
    nombre: str


def respuesta_falsa(json_data=None, error=None):
    """Respuesta de httpx: json() y raise_for_status() son síncronos."""
    resp = MagicMock()
    resp.json.return_value = json_data
    if error:
        resp.raise_for_status.side_effect = error
    return resp


@pytest.fixture
async def servicio():
    svc = HttpRequestService(URL)
    cliente_real = svc.client
    svc.client = MagicMock()
    svc.client.request = AsyncMock()
    svc.client.aclose = AsyncMock()
    yield svc
    await cliente_real.aclose()


class TestInit:
    async def test_guarda_url(self):
        svc = HttpRequestService(URL)
        try:
            assert svc.url == URL
        finally:
            await svc.close()

    async def test_crea_cliente_async(self):
        svc = HttpRequestService(URL)
        try:
            assert isinstance(svc.client, httpx.AsyncClient)
        finally:
            await svc.close()

    async def test_timeout_de_10_segundos(self):
        svc = HttpRequestService(URL)
        try:
            assert svc.client.timeout == httpx.Timeout(10.0)
        finally:
            await svc.close()

    async def test_sin_authkey_no_agrega_header(self):
        svc = HttpRequestService(URL)
        try:
            assert "authkey" not in svc.client.headers
        finally:
            await svc.close()

    async def test_authkey_vacio_no_agrega_header(self):
        svc = HttpRequestService(URL, authkey="")
        try:
            assert "authkey" not in svc.client.headers
        finally:
            await svc.close()

    async def test_con_authkey_agrega_header(self):
        svc = HttpRequestService(URL, authkey="secreto")
        try:
            assert svc.client.headers["authkey"] == "secreto"
        finally:
            await svc.close()


class TestRequest:
    async def test_llama_al_cliente_con_metodo_y_url(self, servicio):
        servicio.client.request.return_value = respuesta_falsa({"id": 1, "nombre": "a"})

        await servicio._request("GET", Item)

        servicio.client.request.assert_awaited_once_with("GET", URL)

    async def test_reenvia_kwargs(self, servicio):
        servicio.client.request.return_value = respuesta_falsa({"id": 1, "nombre": "a"})

        await servicio._request("GET", Item, params={"x": 1}, headers={"h": "v"})

        servicio.client.request.assert_awaited_once_with(
            "GET", URL, params={"x": 1}, headers={"h": "v"}
        )

    async def test_valida_el_status_de_la_respuesta(self, servicio):
        resp = respuesta_falsa({"id": 1, "nombre": "a"})
        servicio.client.request.return_value = resp

        await servicio._request("GET", Item)

        resp.raise_for_status.assert_called_once()

    async def test_deserializa_objeto(self, servicio):
        servicio.client.request.return_value = respuesta_falsa({"id": 1, "nombre": "a"})

        resultado = await servicio._request("GET", Item)

        assert resultado == Item(id=1, nombre="a")

    async def test_deserializa_lista(self, servicio):
        servicio.client.request.return_value = respuesta_falsa(
            [{"id": 1, "nombre": "a"}, {"id": 2, "nombre": "b"}]
        )

        resultado = await servicio._request("GET", list[Item])

        assert [i.id for i in resultado] == [1, 2]

    async def test_deserializa_tipo_simple(self, servicio):
        servicio.client.request.return_value = respuesta_falsa("2026-10-22T10:00:00")

        resultado = await servicio._request("GET", str)

        assert resultado == "2026-10-22T10:00:00"

    async def test_http_error_se_propaga(self, servicio):
        error = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        )
        servicio.client.request.return_value = respuesta_falsa(error=error)

        with pytest.raises(httpx.HTTPStatusError):
            await servicio._request("GET", Item)

    async def test_respuesta_invalida_lanza_validation_error(self, servicio):
        servicio.client.request.return_value = respuesta_falsa({"id": "abc"})

        with pytest.raises(ValidationError):
            await servicio._request("GET", Item)

    async def test_timeout_se_propaga(self, servicio):
        servicio.client.request.side_effect = httpx.ReadTimeout("lento")

        with pytest.raises(httpx.TimeoutException):
            await servicio._request("GET", Item)

    async def test_error_de_conexion_se_propaga(self, servicio):
        servicio.client.request.side_effect = httpx.ConnectError("rechazada")

        with pytest.raises(httpx.ConnectError):
            await servicio._request("GET", Item)


class TestGet:
    async def test_usa_metodo_get(self, servicio):
        servicio._request = AsyncMock(return_value="ok")

        assert await servicio.get(Item, params={"a": 1}) == "ok"

        servicio._request.assert_awaited_once_with("GET", Item, params={"a": 1})


class TestPost:
    async def test_usa_metodo_post_con_json(self, servicio):
        servicio._request = AsyncMock(return_value="ok")
        datos = Item(id=1, nombre="a")

        assert await servicio.post(Item, datos) == "ok"

        servicio._request.assert_awaited_once_with(
            "POST", Item, json={"id": 1, "nombre": "a"}
        )


class TestClose:
    async def test_close_cierra_el_cliente(self, servicio):
        await servicio.close()

        servicio.client.aclose.assert_awaited_once()