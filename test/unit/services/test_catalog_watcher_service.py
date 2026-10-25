"""Pruebas unitarias de CatalogWatcher.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.services.catalog_watcher_service import CatalogWatcher


@pytest.fixture
def make_catalog(make_item):
    def _make(*items):
        return CobotCatalogResponse(items=list(items), total=len(items))
    return _make


@pytest.fixture
def update_service():
    return AsyncMock()


@pytest.fixture
def catalog_service():
    return AsyncMock()


@pytest.fixture
def watcher(update_service, catalog_service):
    return CatalogWatcher(update_service, catalog_service, interval=5.0)


# ---------- estado inicial / items_activos ----------

def test_estado_inicial(watcher):
    assert watcher.catalogo is None
    assert watcher.ultima_actualizacion is None


def test_items_activos_sin_catalogo_devuelve_lista_vacia(watcher):
    assert watcher.items_activos == []


def test_items_activos_filtra_los_inactivos(watcher, make_catalog, make_item):
    activo = make_item(nombre="Mojito", estado=True)
    inactivo = make_item(nombre="Margarita", estado=False)
    watcher.catalogo = make_catalog(activo, inactivo)

    assert watcher.items_activos == [activo]


def test_items_activos_todos_inactivos(watcher, make_catalog, make_item):
    watcher.catalogo = make_catalog(make_item(estado=False))

    assert watcher.items_activos == []


# ---------- _tick ----------

async def test_tick_primera_vez_descarga_y_guarda_catalogo(
    watcher, update_service, catalog_service, make_catalog, make_item
):
    catalogo = make_catalog(make_item())
    update_service.get.return_value = "2026-10-22T10:00:00"
    catalog_service.get.return_value = catalogo

    await watcher._tick()

    update_service.get.assert_awaited_once_with(str)
    catalog_service.get.assert_awaited_once_with(CobotCatalogResponse)
    assert watcher.catalogo is catalogo
    assert watcher.ultima_actualizacion == "2026-10-22T10:00:00"


async def test_tick_misma_fecha_no_vuelve_a_descargar(
    watcher, update_service, catalog_service, make_catalog, make_item
):
    update_service.get.return_value = "f1"
    catalog_service.get.return_value = make_catalog(make_item())

    await watcher._tick()
    await watcher._tick()

    assert catalog_service.get.await_count == 1


async def test_tick_fecha_distinta_descarga_de_nuevo(
    watcher, update_service, catalog_service, make_catalog, make_item
):
    nuevo = make_catalog(make_item(nombre="Daiquiri"))
    update_service.get.side_effect = ["f1", "f2"]
    catalog_service.get.side_effect = [make_catalog(make_item()), nuevo]

    await watcher._tick()
    await watcher._tick()

    assert catalog_service.get.await_count == 2
    assert watcher.catalogo is nuevo
    assert watcher.ultima_actualizacion == "f2"


async def test_tick_usa_catalog_type_personalizado(
    update_service, catalog_service
):
    class OtroTipo:
        pass

    watcher = CatalogWatcher(update_service, catalog_service, catalog_type=OtroTipo)
    update_service.get.return_value = "f1"

    await watcher._tick()

    catalog_service.get.assert_awaited_once_with(OtroTipo)


async def test_tick_si_falla_la_descarga_no_guarda_la_fecha(
    watcher, update_service, catalog_service
):
    """Si la descarga falla, debe reintentarse en el siguiente ciclo."""
    update_service.get.return_value = "f1"
    catalog_service.get.side_effect = RuntimeError("micro caído")

    with pytest.raises(RuntimeError):
        await watcher._tick()

    assert watcher.ultima_actualizacion is None
    assert watcher.catalogo is None


async def test_tick_si_falla_consultar_la_fecha_propaga_el_error(
    watcher, update_service, catalog_service
):
    update_service.get.side_effect = ConnectionError("sin red")

    with pytest.raises(ConnectionError):
        await watcher._tick()

    catalog_service.get.assert_not_awaited()


# ---------- _tick: callback on_change ----------

async def test_tick_llama_on_change_cuando_hay_cambio(
    update_service, catalog_service, make_catalog, make_item
):
    on_change = AsyncMock()
    watcher = CatalogWatcher(update_service, catalog_service, on_change=on_change)
    update_service.get.return_value = "f1"
    catalog_service.get.return_value = make_catalog(make_item())

    await watcher._tick()

    on_change.assert_awaited_once()


async def test_tick_no_llama_on_change_si_no_hay_cambio(
    update_service, catalog_service, make_catalog, make_item
):
    on_change = AsyncMock()
    watcher = CatalogWatcher(update_service, catalog_service, on_change=on_change)
    update_service.get.return_value = "f1"
    catalog_service.get.return_value = make_catalog(make_item())

    await watcher._tick()
    await watcher._tick()

    assert on_change.await_count == 1


async def test_tick_error_en_on_change_no_rompe_el_ciclo(
    update_service, catalog_service, make_catalog, make_item, capsys
):
    on_change = AsyncMock(side_effect=ValueError("falló el envío"))
    watcher = CatalogWatcher(update_service, catalog_service, on_change=on_change)
    update_service.get.return_value = "f1"
    catalog_service.get.return_value = make_catalog(make_item())

    await watcher._tick()  # no debe lanzar

    assert watcher.ultima_actualizacion == "f1"
    assert "Error en on_change" in capsys.readouterr().out


async def test_tick_sin_on_change_funciona(
    watcher, update_service, catalog_service, make_catalog, make_item
):
    update_service.get.return_value = "f1"
    catalog_service.get.return_value = make_catalog(make_item())

    await watcher._tick()

    assert watcher.ultima_actualizacion == "f1"


# ---------- _run: backoff y cancelación ----------

@pytest.fixture
def sleeps(monkeypatch):
    """Reemplaza asyncio.sleep: registra la espera pedida y corta el bucle
    con CancelledError después de `limite` ciclos."""
    real_sleep = asyncio.sleep
    registro = {"esperas": [], "limite": 6}

    async def fake_sleep(segundos):
        registro["esperas"].append(segundos)
        if len(registro["esperas"]) >= registro["limite"]:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(
        "app.services.catalog_watcher_service.asyncio.sleep", fake_sleep
    )
    return registro


async def test_run_backoff_exponencial_con_tope_de_60s(
    watcher, update_service, sleeps
):
    update_service.get.side_effect = RuntimeError("caído")
    sleeps["limite"] = 5

    with pytest.raises(asyncio.CancelledError):
        await watcher._run()

    # interval=5 -> 5*2, 5*4, 5*8, tope 60, tope 60
    assert sleeps["esperas"] == [10.0, 20.0, 40.0, 60, 60]


async def test_run_se_recupera_y_vuelve_al_intervalo_normal(
    watcher, update_service, catalog_service, make_catalog, make_item, sleeps
):
    update_service.get.side_effect = [RuntimeError("caído"), "f1", "f1"]
    catalog_service.get.return_value = make_catalog(make_item())
    sleeps["limite"] = 3

    with pytest.raises(asyncio.CancelledError):
        await watcher._run()

    # 1 fallo (10s) -> éxito: contador de fallos a cero -> intervalo base
    assert sleeps["esperas"] == [10.0, 5.0, 5.0]


async def test_run_imprime_el_error_de_consulta(
    watcher, update_service, sleeps, capsys
):
    update_service.get.side_effect = RuntimeError("caído")
    sleeps["limite"] = 1

    with pytest.raises(asyncio.CancelledError):
        await watcher._run()

    assert "Error al consultar el catálogo" in capsys.readouterr().out


async def test_run_propaga_cancelacion_ocurrida_dentro_de_tick(
    watcher, update_service
):
    update_service.get.side_effect = asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await watcher._run()


# ---------- start / stop ----------

async def test_start_y_stop_ciclo_de_vida(
    update_service, catalog_service, make_catalog, make_item
):
    update_service.get.return_value = "f1"
    catalog_service.get.return_value = make_catalog(make_item())
    watcher = CatalogWatcher(update_service, catalog_service, interval=0.01)

    watcher.start()
    assert watcher._task is not None
    assert watcher._task.get_name() == "catalog-watcher"

    for _ in range(100):
        if watcher.catalogo is not None:
            break
        await asyncio.sleep(0)
    assert watcher.catalogo is not None

    await watcher.stop()

    assert watcher._task.cancelled()


async def test_stop_sin_start_no_hace_nada(watcher):
    await watcher.stop()  # no debe lanzar

    assert watcher._task is None