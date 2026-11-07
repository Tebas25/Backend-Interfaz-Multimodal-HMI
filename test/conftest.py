import os
import threading
from unittest.mock import MagicMock

ENV_DE_PRUEBA = {
    "get_catalog_url": "http://fake-kong/catalog/get",
    "micro_url": "http://fake-kong/catalog",
    "kong_auth_key": "test-key",
    "cobot_host": "127.0.0.1",
    "cobot_port": "5020",
    "cobot_slave_id": "1",
    "modbus_timeout": "2.0",
    "modbus_retries": "3",
    "polling_interval": "0.2",
    "order_timeout": "120",
    "analytics_events_url": "http://fake-kong/api/v1/analytics/events",
    "PUBLIC_BASE_URL": "http://192.168.0.10:8888",
    "PAYMENT_TTL_SECONDS": "120",
    "analytics_transactions_url": "http://fake-kong/api/v1/analytics/transactions",
}
os.environ.update(ENV_DE_PRUEBA)

from decimal import Decimal

import pytest
import speech_recognition as sr

from app.models.cobot_menu_item import CobotMenuItem
from app.services.screen_state import ScreenState


@pytest.fixture
def make_item():
    def _make(
        nombre="Mojito",
        precio="5.50",
        estado=True,
        ingredientes="Ron, menta",
        codigo=1,
        imagen="https://example.com",
    ):
        return CobotMenuItem(
            nombre_item=nombre,
            precio_item=Decimal(precio),
            estado=estado,
            ingredientes=ingredientes,
            codigo_modbus=codigo,
            imagen=imagen,
        )

    return _make


@pytest.fixture(autouse=True)
def reset_screen_state():
    ScreenState.reset()
    yield
    ScreenState.reset()


@pytest.fixture(autouse=True)
def sin_microfono_real(monkeypatch):
    """Ninguna prueba debe abrir el micrófono real ni depender de PyAudio.

    Cualquier `sr.Microphone()` falla como si no hubiera micrófono; las pruebas que
    necesitan uno usan sus propios dobles (monkeypatch posterior sobre sr.Microphone).
    """

    class _SinMicrofono:
        def __init__(self, *args, **kwargs):
            raise OSError("Micrófono deshabilitado en las pruebas")

    monkeypatch.setattr(sr, "Microphone", _SinMicrofono)


class FakeMicrophone:
    """Reemplaza a sr.Microphone: no necesita PyAudio ni hardware."""

    def __enter__(self):
        return "fuente-de-audio"

    def __exit__(self, *exc):
        return False


class FakeRecognizer:
    """Reemplaza a sr.Recognizer: no toca audio ni red.

    `results` asocia cada "audio" (un texto cualquiera) con lo que reconocería Google:
    un texto, o una excepción que se lanza (sr.UnknownValueError, sr.RequestError...).
    """

    def __init__(self):
        self.ambient_calls = []
        self.background_calls = []
        self.background_callback = None
        self.stop_listening = MagicMock(name="stop_listening")
        self.results = {}
        self.recognize_calls = []
        self.threads = {}  # en qué hilo se ejecutó cada llamada

    def adjust_for_ambient_noise(self, source, duration=1):
        self.threads["ambient"] = threading.current_thread()
        self.ambient_calls.append((source, duration))

    def listen_in_background(self, mic, callback, phrase_time_limit=None):
        self.background_calls.append((mic, phrase_time_limit))
        self.background_callback = callback
        return self.stop_listening

    def recognize_google(self, audio, language=None):
        self.threads["recognize"] = threading.current_thread()
        self.recognize_calls.append((audio, language))
        resultado = self.results[audio]
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    def hablar(self, audio, texto):
        """Simula que el micrófono captó `audio` (lo llama speech_recognition desde su hilo)."""
        self.results[audio] = texto
        self.background_callback(self, audio)


@pytest.fixture
def microfono_falso(monkeypatch):
    """Sustituye sr.Microphone y sr.Recognizer por dobles y devuelve el reconocedor falso."""
    reconocedor = FakeRecognizer()
    monkeypatch.setattr(sr, "Microphone", FakeMicrophone)
    monkeypatch.setattr(sr, "Recognizer", lambda: reconocedor)
    return reconocedor
