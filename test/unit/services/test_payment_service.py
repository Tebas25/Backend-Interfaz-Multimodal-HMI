import asyncio
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.services import payment_service
from app.services.payment_service import (
    PaymentService,
    PaymentSession,
    PaymentStatus,
)

BASE_URL = "http://192.168.0.10:8888"
INICIO = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class Reloj:
    def __init__(self):
        self.ahora = INICIO

    def avanzar(self, segundos):
        self.ahora += timedelta(seconds=segundos)

    def __call__(self):
        return self.ahora


@pytest.fixture
def reloj(monkeypatch):
    r = Reloj()
    monkeypatch.setattr(payment_service, "_now", r)
    return r


@pytest.fixture
def on_result():
    return AsyncMock(name="on_result")


@pytest.fixture
async def servicio(on_result, reloj):
    svc = PaymentService(BASE_URL, on_result, ttl_seconds=120)
    yield svc
    svc.close()  # no deja temporizadores vivos entre pruebas


@pytest.fixture
def mojito(make_item):
    return make_item(nombre="Mojito", precio="5.50", codigo=3)


# ---------- PaymentStatus / PaymentSession ----------


def test_los_estados_tienen_los_valores_que_viajan_por_el_websocket():
    assert {s.name: s.value for s in PaymentStatus} == {
        "PENDING": "pending",
        "APPROVED": "approved",
        "REJECTED": "rejected",
        "EXPIRED": "expired",
        "CANCELLED": "cancelled",
    }


def test_una_sesion_nueva_esta_pendiente_y_sin_temporizador(mojito):
    s = PaymentSession(
        drink=mojito, price=mojito.precio_item, expires_at=INICIO + timedelta(seconds=5)
    )

    assert s.status is PaymentStatus.PENDING
    assert s.timer is None
    assert s.created_at.tzinfo is not None


def test_el_id_de_la_sesion_es_valido_para_la_ruta_de_pago(mojito):
    ids = {
        PaymentSession(drink=mojito, price=Decimal("1"), expires_at=INICIO).id
        for _ in range(200)
    }

    assert len(ids) == 200  # no se repiten
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{8,64}", i) for i in ids)


def test_effective_status_pendiente_antes_de_expirar(reloj, mojito):
    s = PaymentSession(
        drink=mojito,
        price=mojito.precio_item,
        expires_at=INICIO + timedelta(seconds=10),
    )

    reloj.avanzar(9.9)

    assert s.effective_status is PaymentStatus.PENDING


@pytest.mark.parametrize("segundos", [10, 10.1, 3600])
def test_effective_status_es_expirado_desde_el_instante_de_expiracion(
    reloj, mojito, segundos
):
    s = PaymentSession(
        drink=mojito,
        price=mojito.precio_item,
        expires_at=INICIO + timedelta(seconds=10),
    )

    reloj.avanzar(segundos)

    assert s.effective_status is PaymentStatus.EXPIRED
    assert s.status is PaymentStatus.PENDING


@pytest.mark.parametrize(
    "estado",
    [PaymentStatus.APPROVED, PaymentStatus.REJECTED, PaymentStatus.CANCELLED],
)
def test_effective_status_respeta_un_estado_final_aunque_haya_pasado_el_tiempo(
    reloj, mojito, estado
):
    s = PaymentSession(
        drink=mojito,
        price=mojito.precio_item,
        expires_at=INICIO + timedelta(seconds=10),
        status=estado,
    )

    reloj.avanzar(1000)

    assert s.effective_status is estado


# ---------- construcción y pay_url ----------


@pytest.mark.parametrize("base", [BASE_URL, BASE_URL + "/", BASE_URL + "///"])
def test_pay_url_no_duplica_las_barras(base, on_result, mojito, reloj):
    svc = PaymentService(base, on_result)
    s = PaymentSession(
        drink=mojito, price=Decimal("1"), expires_at=INICIO, id="abc12345"
    )

    assert svc.pay_url(s) == f"{BASE_URL}/pay/abc12345"


def test_get_devuelve_none_si_no_existe(servicio):
    assert servicio.get("inexistente") is None


# ---------- start ----------


async def test_start_crea_una_sesion_pendiente_con_el_precio_de_la_bebida(
    servicio, mojito, reloj
):
    s = servicio.start(mojito)

    assert s.drink is mojito
    assert s.price == Decimal("5.50")
    assert s.status is PaymentStatus.PENDING
    assert s.expires_at == INICIO + timedelta(seconds=120)


async def test_start_registra_la_sesion_y_la_hace_consultable(servicio, mojito):
    s = servicio.start(mojito)

    assert servicio.get(s.id) is s


async def test_start_arranca_el_temporizador_de_expiracion(servicio, mojito):
    s = servicio.start(mojito)

    assert isinstance(s.timer, asyncio.Task)
    assert not s.timer.done()


async def test_cada_start_genera_un_id_distinto(servicio, mojito):
    ids = {servicio.start(mojito).id for _ in range(5)}

    assert len(ids) == 5


async def test_el_ttl_configurado_define_la_expiracion(on_result, mojito, reloj):
    svc = PaymentService(BASE_URL, on_result, ttl_seconds=30)
    try:
        s = svc.start(mojito)
    finally:
        svc.close()

    assert s.expires_at == INICIO + timedelta(seconds=30)


async def test_un_nuevo_start_cancela_el_pago_anterior_sin_avisar(
    servicio, on_result, make_item
):
    primero = servicio.start(make_item(nombre="Mojito"))
    segundo = servicio.start(make_item(nombre="Daiquiri"))
    await asyncio.sleep(0)

    assert primero.status is PaymentStatus.CANCELLED
    assert segundo.status is PaymentStatus.PENDING
    assert primero.timer.cancelled()
    on_result.assert_not_awaited()


async def test_el_pago_cancelado_por_un_nuevo_start_sigue_consultable(
    servicio, make_item
):
    primero = servicio.start(make_item(nombre="Mojito"))
    servicio.start(make_item(nombre="Daiquiri"))

    assert servicio.get(primero.id) is primero


async def test_start_despues_de_un_pago_terminado_no_toca_el_anterior(
    servicio, make_item
):
    primero = servicio.start(make_item(nombre="Mojito"))
    await servicio.approve(primero.id)

    servicio.start(make_item(nombre="Daiquiri"))

    assert primero.status is PaymentStatus.APPROVED


# ---------- cancel ----------


async def test_cancel_sin_pago_en_curso_no_hace_nada(servicio, on_result):
    servicio.cancel()
    servicio.cancel("lo-que-sea")

    on_result.assert_not_awaited()


async def test_cancel_sin_id_cancela_el_pago_en_curso(servicio, mojito, on_result):
    s = servicio.start(mojito)

    servicio.cancel()
    await asyncio.sleep(0)

    assert s.status is PaymentStatus.CANCELLED
    assert s.timer.cancelled()
    on_result.assert_not_awaited()


async def test_cancel_con_el_id_correcto_cancela(servicio, mojito):
    s = servicio.start(mojito)

    servicio.cancel(s.id)

    assert s.status is PaymentStatus.CANCELLED


async def test_cancel_con_otro_id_se_ignora(servicio, mojito):
    s = servicio.start(mojito)

    servicio.cancel("id-de-otro-pago")

    assert s.status is PaymentStatus.PENDING
    assert not s.timer.done()


async def test_cancel_dos_veces_es_inocuo(servicio, mojito):
    s = servicio.start(mojito)

    servicio.cancel(s.id)
    servicio.cancel(s.id)

    assert s.status is PaymentStatus.CANCELLED


async def test_cancel_no_pisa_un_pago_ya_aprobado(servicio, mojito):
    s = servicio.start(mojito)
    await servicio.approve(s.id)

    servicio.cancel(s.id)

    assert s.status is PaymentStatus.APPROVED


# ---------- approve / reject ----------


async def test_approve_marca_aprobado_y_notifica_una_vez(servicio, mojito, on_result):
    s = servicio.start(mojito)

    resultado = await servicio.approve(s.id)

    assert resultado is s
    assert s.status is PaymentStatus.APPROVED
    on_result.assert_awaited_once_with(s)


async def test_reject_marca_rechazado_y_notifica_una_vez(servicio, mojito, on_result):
    s = servicio.start(mojito)

    resultado = await servicio.reject(s.id)

    assert resultado is s
    assert s.status is PaymentStatus.REJECTED
    on_result.assert_awaited_once_with(s)


@pytest.mark.parametrize("accion", ["approve", "reject"])
async def test_id_desconocido_devuelve_none_y_no_notifica(servicio, on_result, accion):
    resultado = await getattr(servicio, accion)("no-existe")

    assert resultado is None
    on_result.assert_not_awaited()


@pytest.mark.parametrize("accion", ["approve", "reject"])
async def test_al_resolver_se_detiene_el_temporizador(servicio, mojito, accion):
    s = servicio.start(mojito)

    await getattr(servicio, accion)(s.id)
    await asyncio.sleep(0)

    assert s.timer.cancelled()


async def test_aprobar_dos_veces_notifica_una_sola_vez(servicio, mojito, on_result):
    s = servicio.start(mojito)

    primero = await servicio.approve(s.id)
    segundo = await servicio.approve(s.id)

    assert primero is segundo is s
    on_result.assert_awaited_once()


async def test_el_primer_resultado_gana(servicio, mojito, on_result):
    s = servicio.start(mojito)

    await servicio.reject(s.id)
    await servicio.approve(s.id)

    assert s.status is PaymentStatus.REJECTED
    on_result.assert_awaited_once()


async def test_aprobar_un_pago_cancelado_no_lo_aprueba_ni_notifica(
    servicio, mojito, on_result
):
    s = servicio.start(mojito)
    servicio.cancel(s.id)

    resultado = await servicio.approve(s.id)

    assert (
        resultado is s
    )
    assert s.status is PaymentStatus.CANCELLED
    on_result.assert_not_awaited()


@pytest.mark.parametrize("accion", ["approve", "reject"])
async def test_resolver_despues_del_tiempo_limite_deja_el_pago_expirado(
    servicio, mojito, on_result, reloj, accion
):
    s = servicio.start(mojito)
    reloj.avanzar(120)

    await getattr(servicio, accion)(s.id)

    assert s.status is PaymentStatus.EXPIRED
    on_result.assert_awaited_once_with(s)


async def test_resolver_justo_antes_del_limite_si_aprueba(servicio, mojito, reloj):
    s = servicio.start(mojito)
    reloj.avanzar(119.9)

    await servicio.approve(s.id)

    assert s.status is PaymentStatus.APPROVED


async def test_un_error_en_on_result_no_rompe_el_pago(mojito, reloj, capsys):
    fallido = AsyncMock(side_effect=RuntimeError("front caído"))
    svc = PaymentService(BASE_URL, fallido)
    try:
        s = svc.start(mojito)

        resultado = await svc.approve(s.id)
    finally:
        svc.close()

    assert resultado is s
    assert s.status is PaymentStatus.APPROVED
    fallido.assert_awaited_once()
    salida = capsys.readouterr().out
    assert "Error en on_result" in salida
    assert "RuntimeError" in salida


# ---------- expiración por temporizador ----------


async def test_al_vencer_el_ttl_el_pago_expira_y_se_notifica(mojito):
    avisado = asyncio.Event()

    async def on_result(session):
        avisado.set()

    svc = PaymentService(BASE_URL, on_result, ttl_seconds=0.05)
    try:
        s = svc.start(mojito)

        await asyncio.wait_for(avisado.wait(), timeout=2)

        assert s.status is PaymentStatus.EXPIRED
    finally:
        svc.close()


async def test_la_expiracion_notifica_exactamente_una_vez(mojito):
    on_result = AsyncMock()
    svc = PaymentService(BASE_URL, on_result, ttl_seconds=0.05)
    try:
        svc.start(mojito)

        await asyncio.sleep(0.3)

        on_result.assert_awaited_once()
        assert on_result.await_args.args[0].status is PaymentStatus.EXPIRED
    finally:
        svc.close()


async def test_un_pago_aprobado_no_vuelve_a_notificar_al_vencer_el_ttl(mojito):
    on_result = AsyncMock()
    svc = PaymentService(BASE_URL, on_result, ttl_seconds=0.1)
    try:
        s = svc.start(mojito)
        await svc.approve(s.id)

        await asyncio.sleep(0.3)

        on_result.assert_awaited_once()
        assert s.status is PaymentStatus.APPROVED
    finally:
        svc.close()


async def test_un_pago_cancelado_no_notifica_al_vencer_el_ttl(mojito):
    on_result = AsyncMock()
    svc = PaymentService(BASE_URL, on_result, ttl_seconds=0.1)
    try:
        s = svc.start(mojito)
        svc.cancel(s.id)

        await asyncio.sleep(0.3)

        on_result.assert_not_awaited()
        assert s.status is PaymentStatus.CANCELLED
    finally:
        svc.close()


async def test_solo_expira_el_pago_en_curso_no_el_cancelado_por_un_nuevo_start(
    make_item,
):
    on_result = AsyncMock()
    svc = PaymentService(BASE_URL, on_result, ttl_seconds=0.1)
    try:
        primero = svc.start(make_item(nombre="Mojito"))
        segundo = svc.start(make_item(nombre="Daiquiri"))

        await asyncio.sleep(0.3)

        on_result.assert_awaited_once_with(segundo)
        assert primero.status is PaymentStatus.CANCELLED
    finally:
        svc.close()


# ---------- close ----------


async def test_close_cancela_todos_los_temporizadores(on_result, make_item, reloj):
    svc = PaymentService(BASE_URL, on_result)
    a = svc.start(make_item(nombre="Mojito"))
    b = svc.start(make_item(nombre="Daiquiri"))

    svc.close()
    await asyncio.sleep(0)

    assert a.timer.cancelled()
    assert b.timer.cancelled()
    on_result.assert_not_awaited()


def test_close_sin_sesiones_no_falla(on_result):
    PaymentService(BASE_URL, on_result).close()


# ---------- limpieza de sesiones antiguas ----------


async def test_start_elimina_las_sesiones_terminadas_de_hace_mas_de_10_minutos(
    servicio, make_item, reloj
):
    vieja = servicio.start(make_item(nombre="Mojito"))
    await servicio.approve(vieja.id)
    vieja.created_at = reloj.ahora - timedelta(minutes=11)

    servicio.start(make_item(nombre="Daiquiri"))

    assert servicio.get(vieja.id) is None


async def test_start_conserva_las_sesiones_terminadas_recientes(
    servicio, make_item, reloj
):
    reciente = servicio.start(make_item(nombre="Mojito"))
    await servicio.approve(reciente.id)
    reciente.created_at = reloj.ahora - timedelta(minutes=9)

    servicio.start(make_item(nombre="Daiquiri"))

    assert servicio.get(reciente.id) is reciente


async def test_la_limpieza_incluye_pagos_cancelados_antiguos(
    servicio, make_item, reloj
):
    vieja = servicio.start(make_item(nombre="Mojito"))
    servicio.start(make_item(nombre="Daiquiri"))  # cancela a la primera
    vieja.created_at = reloj.ahora - timedelta(minutes=30)

    servicio.start(make_item(nombre="Piña colada"))

    assert servicio.get(vieja.id) is None


async def test_la_limpieza_nunca_borra_el_pago_en_curso(servicio, make_item, reloj):
    actual = servicio.start(make_item(nombre="Mojito"))
    actual.created_at = reloj.ahora - timedelta(hours=1)

    nuevo = servicio.start(make_item(nombre="Daiquiri"))

    assert servicio.get(nuevo.id) is nuevo