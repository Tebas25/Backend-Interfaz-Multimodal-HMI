from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app import main
from app.schemas.ws_messages import (
    ErrorMessage,
    PaymentResult,
    PaymentStarted,
    StartPayment,
    StartPaymentPayload,
    CancelPayment,
    CancelPaymentPayload,
    ServerMessage,
)

BASE = "http://10.0.0.5:9000"
server_adapter = TypeAdapter(ServerMessage)


class WatcherFalso:
    catalogo = None
    ultima_actualizacion = None

    def __init__(self, items):
        self.items_activos = items
        self.stop = AsyncMock()

    def start(self):
        pass


def _http_falso():
    s = MagicMock()
    s.close = AsyncMock()
    return s


def _levantar(monkeypatch, make_item, ttl_segundos):
    watcher = WatcherFalso(
        [
            make_item(nombre="Mojito", precio="5.50"),
            make_item(nombre="Daiquiri", precio="6"),
        ]
    )
    publisher = MagicMock()
    publisher.stop = AsyncMock()
    listener = MagicMock()
    listener.start = AsyncMock(return_value=True)
    listener.stop = AsyncMock()
    orden = MagicMock()
    orden.stop = AsyncMock()

    monkeypatch.setattr(
        main, "HttpRequestService", MagicMock(side_effect=lambda *a, **k: _http_falso())
    )
    monkeypatch.setattr(main, "CatalogWatcher", MagicMock(return_value=watcher))
    monkeypatch.setattr(
        main, "CommandListenerService", MagicMock(return_value=listener)
    )
    monkeypatch.setattr(main, "OrderService", MagicMock(return_value=orden))
    monkeypatch.setattr(main, "modbus_connection", MagicMock())
    monkeypatch.setattr(main.settings, "PUBLIC_BASE_URL", BASE)
    monkeypatch.setattr(main.settings, "PAYMENT_TTL_SECONDS", ttl_segundos)

    client = TestClient(main.app)
    client.watcher = watcher
    client.order_service = orden
    return client


@pytest.fixture
def servidor(monkeypatch, make_item):
    with _levantar(monkeypatch, make_item, 120) as client:
        yield client


@pytest.fixture
def servidor_rapido(monkeypatch, make_item):
    with _levantar(monkeypatch, make_item, 0.2) as client:
        yield client


def recibir(ws):
    return server_adapter.validate_python(ws.receive_json())


def pedir_pago(ws, bebida="Mojito"):
    ws.send_text(
        StartPayment(payload=StartPaymentPayload(drink=bebida)).model_dump_json()
    )
    return recibir(ws)


def ruta(pay_url):
    assert pay_url.startswith(BASE)
    return pay_url.removeprefix(BASE)


def sondear(ws):
    ws.send_text("no es json")
    return recibir(ws)


# ---------- flujo feliz ----------


def test_pagar_de_principio_a_fin(servidor):
    with servidor.websocket_connect("/ws") as ws:
        iniciado = pedir_pago(ws)

        assert isinstance(iniciado, PaymentStarted)
        assert iniciado.payload.drink_name == "Mojito"
        assert str(iniciado.payload.price) == "5.50"
        url = ruta(iniciado.payload.pay_url)
        assert url == f"/pay/{iniciado.payload.payment_id}"

        pagina = servidor.get(url)
        assert pagina.status_code == 200
        assert "Mojito" in pagina.text and "$5.50" in pagina.text

        final = servidor.post(f"{url}/approve")
        assert final.status_code == 200
        assert "¡Pago realizado!" in final.text

        resultado = recibir(ws)
        assert isinstance(resultado, PaymentResult)
        assert resultado.payload.status == "approved"
        assert resultado.payload.payment_id == iniciado.payload.payment_id


def test_rechazar_el_pago_notifica_al_front(servidor):
    with servidor.websocket_connect("/ws") as ws:
        iniciado = pedir_pago(ws)
        url = ruta(iniciado.payload.pay_url)

        final = servidor.post(f"{url}/reject")

        assert "Pago rechazado" in final.text
        resultado = recibir(ws)
        assert resultado.payload.status == "rejected"
        assert resultado.payload.payment_id == iniciado.payload.payment_id


def test_el_resultado_llega_a_todos_los_clientes_conectados(servidor):
    with (
        servidor.websocket_connect("/ws") as pantalla,
        servidor.websocket_connect("/ws") as otra,
    ):
        iniciado = pedir_pago(pantalla)

        servidor.post(f"{ruta(iniciado.payload.pay_url)}/approve")

        assert recibir(pantalla).payload.status == "approved"
        assert recibir(otra).payload.status == "approved"


def test_payment_started_solo_llega_a_quien_pidio_el_pago(servidor):
    with (
        servidor.websocket_connect("/ws") as pantalla,
        servidor.websocket_connect("/ws") as otra,
    ):
        pedir_pago(pantalla)

        assert isinstance(sondear(otra), ErrorMessage)


def test_aprobar_un_pago_ordena_la_bebida_al_cobot(servidor):
    with servidor.websocket_connect("/ws") as ws:
        iniciado = pedir_pago(ws)

        servidor.post(f"{ruta(iniciado.payload.pay_url)}/approve")
        recibir(ws)

    servidor.order_service.request_order.assert_called_once()


# ---------- bebida no disponible / mensajes inválidos ----------


def test_pedir_pago_de_una_bebida_que_no_esta_activa_responde_error(servidor):
    with servidor.websocket_connect("/ws") as ws:
        msg = pedir_pago(ws, "Margarita")

    assert isinstance(msg, PaymentResult)
    assert msg.payload.status == "error"
    assert msg.payload.reason == "drink_unavailable"
    assert msg.payload.payment_id is None


def test_la_bebida_desactivada_mientras_se_elegia_no_se_cobra(servidor):
    servidor.watcher.items_activos = []

    with servidor.websocket_connect("/ws") as ws:
        msg = pedir_pago(ws, "Mojito")

    assert msg.payload.reason == "drink_unavailable"


def test_el_nombre_de_la_bebida_no_distingue_mayusculas(servidor):
    with servidor.websocket_connect("/ws") as ws:
        msg = pedir_pago(ws, "daiquiri")

    assert isinstance(msg, PaymentStarted)
    assert msg.payload.drink_name == "Daiquiri"


@pytest.mark.parametrize(
    "raw",
    [
        '{"type":"start_payment","payload":{}}',
        '{"type":"start_payment","payload":{"drink":""}}',
        '{"type":"start_payment","payload":{"drink":"Mojito","extra":1}}',
    ],
)
def test_start_payment_invalido_responde_error_y_no_crea_pago(servidor, raw):
    with servidor.websocket_connect("/ws") as ws:
        ws.send_text(raw)
        msg = recibir(ws)

        assert isinstance(msg, ErrorMessage)
        assert msg.payload.detail[0]["loc"][0] in {"start_payment", "payload"}
        assert isinstance(sondear(ws), ErrorMessage)


# ---------- cancelación y reemplazo ----------


def test_cancelar_desde_el_front_invalida_el_enlace_sin_notificar(servidor):
    with servidor.websocket_connect("/ws") as ws:
        iniciado = pedir_pago(ws)
        url = ruta(iniciado.payload.pay_url)

        ws.send_text(
            CancelPayment(
                payload=CancelPaymentPayload(payment_id=iniciado.payload.payment_id)
            ).model_dump_json()
        )
        for _ in range(50):
            if "Pedido cancelado" in servidor.get(url).text:
                break
        assert "Pedido cancelado" in servidor.get(url).text
        final = servidor.post(f"{url}/approve")

        assert "Pedido cancelado" in final.text
        assert isinstance(sondear(ws), ErrorMessage)


def test_cancelar_sin_id_cancela_el_pago_en_curso(servidor):
    with servidor.websocket_connect("/ws") as ws:
        iniciado = pedir_pago(ws)
        url = ruta(iniciado.payload.pay_url)

        ws.send_text(CancelPayment(payload=CancelPaymentPayload()).model_dump_json())
        sondear(ws)

        assert "Pedido cancelado" in servidor.get(url).text


def test_cancelar_con_el_id_de_otro_pago_no_cancela_el_actual(servidor):
    with servidor.websocket_connect("/ws") as ws:
        iniciado = pedir_pago(ws)
        url = ruta(iniciado.payload.pay_url)

        ws.send_text(
            CancelPayment(
                payload=CancelPaymentPayload(payment_id="otro-pago-viejo")
            ).model_dump_json()
        )
        sondear(ws)

        assert "Realizar pago" in servidor.get(url).text


def test_un_segundo_pago_cancela_el_primero(servidor):
    with servidor.websocket_connect("/ws") as ws:
        primero = pedir_pago(ws, "Mojito")
        segundo = pedir_pago(ws, "Daiquiri")

        assert primero.payload.payment_id != segundo.payload.payment_id
        assert "Pedido cancelado" in servidor.get(ruta(primero.payload.pay_url)).text
        assert "Realizar pago" in servidor.get(ruta(segundo.payload.pay_url)).text

        servidor.post(f"{ruta(primero.payload.pay_url)}/approve")
        assert isinstance(sondear(ws), ErrorMessage)

        servidor.post(f"{ruta(segundo.payload.pay_url)}/approve")
        resultado = recibir(ws)
        assert resultado.payload.payment_id == segundo.payload.payment_id


# ---------- idempotencia ----------


def test_aprobar_dos_veces_notifica_una_sola_vez(servidor):
    with servidor.websocket_connect("/ws") as ws:
        iniciado = pedir_pago(ws)
        url = ruta(iniciado.payload.pay_url)

        servidor.post(f"{url}/approve")
        servidor.post(f"{url}/approve")
        servidor.post(f"{url}/reject")

        assert recibir(ws).payload.status == "approved"
        assert isinstance(sondear(ws), ErrorMessage)
        assert "¡Pago realizado!" in servidor.get(url).text


def test_pagar_con_un_id_desconocido_muestra_enlace_no_valido(servidor):
    r = servidor.post("/pay/id-que-no-existe/approve")

    assert r.status_code == 404
    assert "Enlace no válido" in r.text


# ---------- expiración ----------


def test_el_pago_expira_y_se_notifica_al_front(servidor_rapido):
    servidor = servidor_rapido
    with servidor.websocket_connect("/ws") as ws:
        iniciado = pedir_pago(ws)
        url = ruta(iniciado.payload.pay_url)

        resultado = recibir(ws)

        assert resultado.payload.status == "expired"
        assert resultado.payload.payment_id == iniciado.payload.payment_id
        assert "Código expirado" in servidor.get(url).text
        assert "Código expirado" in servidor.post(f"{url}/approve").text
        assert isinstance(sondear(ws), ErrorMessage)
