from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.pay_pages import router
from app.services.payment_service import PaymentSession, PaymentStatus

ID = "abc12345_-XYZ"


class ServicioFalso:

    def __init__(self):
        self.sesiones = {}
        self.llamadas = []

    def get(self, payment_id):
        return self.sesiones.get(payment_id)

    async def approve(self, payment_id):
        self.llamadas.append(("approve", payment_id))
        return self.sesiones.get(payment_id)

    async def reject(self, payment_id):
        self.llamadas.append(("reject", payment_id))
        return self.sesiones.get(payment_id)


@pytest.fixture
def servicio():
    return ServicioFalso()


@pytest.fixture
def client(servicio):
    app = FastAPI()
    app.state.payment_service = servicio
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def crear_sesion(servicio, make_item):
    def _crear(
        nombre="Mojito",
        precio="5.50",
        estado=PaymentStatus.PENDING,
        vence_en=120,
        payment_id=ID,
    ):
        s = PaymentSession(
            drink=make_item(nombre=nombre, precio=precio),
            price=Decimal(precio),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=vence_en),
            id=payment_id,
            status=estado,
        )
        servicio.sesiones[payment_id] = s
        return s

    return _crear


# ---------- GET /pay/{id}: pago pendiente ----------


def test_pago_pendiente_muestra_bebida_precio_y_botones(client, crear_sesion):
    crear_sesion(nombre="Mojito", precio="5.5")

    r = client.get(f"/pay/{ID}")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<h1>Mojito</h1>" in r.text
    assert "$5.50" in r.text
    assert "Realizar pago" in r.text
    assert "Rechazar pago" in r.text


@pytest.mark.parametrize(
    "precio, esperado",
    [("5.5", "$5.50"), ("12", "$12.00"), ("0.1", "$0.10"), ("7.999", "$8.00")],
)
def test_el_precio_se_muestra_siempre_con_dos_decimales(
    client, crear_sesion, precio, esperado
):
    crear_sesion(precio=precio)

    assert esperado in client.get(f"/pay/{ID}").text


def test_los_botones_envian_por_post_al_id_correcto(client, crear_sesion):
    crear_sesion()

    html = client.get(f"/pay/{ID}").text

    assert f'<form method="post" action="/pay/{ID}/approve">' in html
    assert f'<form method="post" action="/pay/{ID}/reject">' in html


def test_la_pagina_es_responsive_y_aclara_que_es_una_demostracion(client, crear_sesion):
    crear_sesion()

    html = client.get(f"/pay/{ID}").text

    assert '<html lang="es">' in html
    assert 'name="viewport"' in html
    assert "no se realiza ningún cobro real" in html


def test_el_nombre_de_la_bebida_se_escapa_en_el_html(client, crear_sesion):
    crear_sesion(nombre='<script>alert("x")</script> & Co')

    html = client.get(f"/pay/{ID}").text

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; Co" in html


def test_un_signo_de_dolar_en_el_nombre_no_rompe_la_plantilla(client, crear_sesion):
    crear_sesion(nombre="Mojito $body $price")

    r = client.get(f"/pay/{ID}")

    assert r.status_code == 200
    assert "Mojito $body $price" in r.text


def test_la_pagina_nunca_se_guarda_en_cache(client, crear_sesion):
    crear_sesion()

    assert client.get(f"/pay/{ID}").headers["cache-control"] == "no-store"


def test_pendiente_pero_vencido_se_muestra_como_expirado(client, crear_sesion):
    crear_sesion(vence_en=-1)

    r = client.get(f"/pay/{ID}")

    assert r.status_code == 200
    assert "Código expirado" in r.text
    assert "Realizar pago" not in r.text


# ---------- GET /pay/{id}: estados finales ----------


@pytest.mark.parametrize(
    "estado, titulo, texto",
    [
        (PaymentStatus.APPROVED, "¡Pago realizado!", "Ya puedes volver"),
        (PaymentStatus.REJECTED, "Pago rechazado", "No se realizó ningún cobro"),
        (PaymentStatus.EXPIRED, "Código expirado", "Genera uno nuevo"),
        (PaymentStatus.CANCELLED, "Pedido cancelado", "se canceló en la pantalla"),
    ],
)
def test_estados_finales_muestran_su_mensaje_sin_botones(
    client, crear_sesion, estado, titulo, texto
):
    crear_sesion(estado=estado)

    r = client.get(f"/pay/{ID}")

    assert r.status_code == 200
    assert titulo in r.text
    assert texto in r.text
    assert "<form" not in r.text
    assert "<button" not in r.text
    assert r.headers["cache-control"] == "no-store"


def test_todos_los_estados_finales_tienen_mensaje():
    from app.api.pay_pages import _FINAL

    assert set(_FINAL) == set(PaymentStatus) - {PaymentStatus.PENDING}


# ---------- GET /pay/{id}: enlaces no válidos ----------


def test_id_inexistente_devuelve_404_con_mensaje(client):
    r = client.get(f"/pay/{ID}")

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert "Enlace no válido" in r.text
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "payment_id",
    ["corto", "a" * 7, "a" * 65, "con.punto.1234", "con%20espacio1", "ñandú12345"],
)
def test_id_con_formato_invalido_se_rechaza_con_422(client, servicio, payment_id):
    r = client.get(f"/pay/{payment_id}")

    assert r.status_code == 422


@pytest.mark.parametrize("payment_id", ["a" * 8, "a" * 64, "Ab1_-Zz9"])
def test_ids_en_los_limites_del_formato_se_aceptan(client, payment_id):
    assert client.get(f"/pay/{payment_id}").status_code == 404


# ---------- POST approve / reject ----------


@pytest.mark.parametrize("accion", ["approve", "reject"])
def test_post_delega_en_el_servicio_y_redirige_a_la_pagina(
    client, servicio, crear_sesion, accion
):
    crear_sesion()

    r = client.post(f"/pay/{ID}/{accion}", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == f"/pay/{ID}"
    assert servicio.llamadas == [(accion, ID)]


@pytest.mark.parametrize("accion", ["approve", "reject"])
def test_post_con_id_inexistente_redirige_y_la_pagina_dice_enlace_no_valido(
    client, servicio, accion
):
    r = client.post(f"/pay/{ID}/{accion}", follow_redirects=True)

    assert servicio.llamadas == [(accion, ID)]
    assert r.status_code == 404
    assert "Enlace no válido" in r.text


@pytest.mark.parametrize("accion", ["approve", "reject"])
def test_post_con_id_invalido_no_llega_al_servicio(client, servicio, accion):
    r = client.post(f"/pay/corto/{accion}", follow_redirects=False)

    assert r.status_code == 422
    assert servicio.llamadas == []


@pytest.mark.parametrize("accion", ["approve", "reject"])
def test_aprobar_y_rechazar_no_se_pueden_hacer_con_get(client, accion):
    assert client.get(f"/pay/{ID}/{accion}").status_code == 405


def test_la_pagina_no_se_puede_enviar_por_post(client, crear_sesion):
    crear_sesion()

    assert client.post(f"/pay/{ID}").status_code == 405