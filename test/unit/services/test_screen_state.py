from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.ws_messages import Screen, StatePayload, StateSource
from app.services.screen_state import ScreenState


def payload(screen=Screen.MENU, source=StateSource.TOUCH, ref=None):
    return StatePayload(screen=screen, source=source, ref=ref)


# ---------- estado inicial ----------

def test_estado_inicial_esta_vacio():
    assert ScreenState.current is None
    assert ScreenState.source is None
    assert ScreenState.ref is None
    assert ScreenState.updated_at is None


# ---------- update ----------

def test_update_guarda_pantalla_y_origen():
    ScreenState.update(payload(Screen.MENU, StateSource.TOUCH))

    assert ScreenState.current is Screen.MENU
    assert ScreenState.source is StateSource.TOUCH
    assert ScreenState.ref is None


def test_update_guarda_la_referencia_cuando_el_origen_es_backend():
    ScreenState.update(payload(Screen.WELCOME, StateSource.BACKEND, ref="abc123"))

    assert ScreenState.current is Screen.WELCOME
    assert ScreenState.source is StateSource.BACKEND
    assert ScreenState.ref == "abc123"


def test_update_registra_la_hora_en_utc():
    antes = datetime.now(timezone.utc)

    ScreenState.update(payload())

    despues = datetime.now(timezone.utc)
    assert ScreenState.updated_at.utcoffset() == timedelta(0)
    assert antes <= ScreenState.updated_at <= despues


def test_update_reemplaza_el_estado_anterior():
    ScreenState.update(payload(Screen.WELCOME, StateSource.BACKEND, ref="abc"))

    ScreenState.update(payload(Screen.MENU, StateSource.TOUCH))

    assert ScreenState.current is Screen.MENU
    assert ScreenState.source is StateSource.TOUCH
    assert ScreenState.ref is None   # la referencia anterior no se arrastra


def test_update_actualiza_la_hora_en_cada_cambio():
    ScreenState.update(payload())
    primera = ScreenState.updated_at

    ScreenState.update(payload(Screen.WELCOME, StateSource.INIT))

    assert ScreenState.updated_at >= primera


def test_update_imprime_pantalla_y_origen(capsys):
    ScreenState.update(payload(Screen.MENU, StateSource.TOUCH))

    assert "[Estado] pantalla=menu origen=touch" in capsys.readouterr().out


@pytest.mark.parametrize("screen", list(Screen))
@pytest.mark.parametrize("source", [StateSource.TOUCH, StateSource.INIT])
def test_update_acepta_cualquier_pantalla_y_origen_sin_referencia(screen, source):
    ScreenState.update(payload(screen, source))

    assert ScreenState.current is screen
    assert ScreenState.source is source


# ---------- reset ----------

def test_reset_deja_todo_en_none():
    ScreenState.update(payload(Screen.WELCOME, StateSource.BACKEND, ref="abc"))

    ScreenState.reset()

    assert ScreenState.current is None
    assert ScreenState.source is None
    assert ScreenState.ref is None
    assert ScreenState.updated_at is None


def test_reset_sobre_estado_vacio_no_falla():
    ScreenState.reset()

    assert ScreenState.current is None


# ---------- naturaleza estática ----------

def test_el_estado_es_compartido_por_toda_la_aplicacion():
    ScreenState.update(payload(Screen.MENU, StateSource.TOUCH))

    instancia = ScreenState()

    assert instancia.current is Screen.MENU   # se lee desde la clase, no por instancia