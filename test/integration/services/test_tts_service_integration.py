"""
Integración TTSService + build_voice_message + LocalAudioPlayer.

Solo se simulan las fronteras externas (red de edge_tts y el dispositivo de
audio de pygame); el resto del flujo es real.

Para probar contra el servicio real de Microsoft:
    RUN_NETWORK_TESTS=1 pytest test/integration/services/test_tts_service_integration.py
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from app.core.voice_response import VoiceEvent, build_voice_message
from app.services.local_audio_player import LocalAudioPlayer
from app.services.tts_service import TTSService

COMMUNICATE_PATH = "app.services.tts_service.edge_tts.Communicate"
PYGAME_PATH = "app.services.local_audio_player.pygame"


class FakeCommunicate:
    """Reemplazo de edge_tts.Communicate que 'sintetiza' el texto recibido."""

    last_instance = None

    def __init__(self, text, voice):
        self.text = text
        self.voice = voice
        FakeCommunicate.last_instance = self

    async def stream(self):
        yield {"type": "WordBoundary", "text": self.text}
        yield {"type": "audio", "data": self.text.encode("utf-8")}


@pytest.fixture
def fake_edge_tts():
    with patch(COMMUNICATE_PATH, FakeCommunicate):
        yield FakeCommunicate


@pytest.mark.asyncio
class TestSynthesizeFlow:
    @pytest.mark.parametrize("event", list(VoiceEvent))
    async def test_every_event_without_args_produces_audio(self, fake_edge_tts, event):
        audio = await TTSService().synthesize(event, drink="Capuchino")

        expected = build_voice_message(event, drink="Capuchino")
        assert audio == expected.encode("utf-8")

    async def test_drink_is_spoken_in_preparing_message(self, fake_edge_tts):
        audio = await TTSService().synthesize(
            VoiceEvent.PREPARING_DRINK, drink="Té helado"
        )

        assert "Té helado" in audio.decode("utf-8")

    async def test_voice_is_forwarded_to_engine(self, fake_edge_tts):
        await TTSService(voice="es-MX-JorgeNeural").synthesize(VoiceEvent.PAYMENT)

        assert fake_edge_tts.last_instance.voice == "es-MX-JorgeNeural"

    async def test_missing_drink_speaks_not_understood(self, fake_edge_tts):
        audio = await TTSService().synthesize(VoiceEvent.PREPARING_COMPLETE)

        assert audio.decode("utf-8") == VoiceEvent.NOT_UNDERSTOOD.value


@pytest.mark.asyncio
class TestSynthesizeAndPlay:
    async def test_synthesized_audio_reaches_player(self, fake_edge_tts):
        with patch(PYGAME_PATH) as pg:
            pg.mixer_music.get_busy.side_effect = [True, False]
            player = LocalAudioPlayer()
            audio = await TTSService().synthesize(VoiceEvent.PAYMENT_CONFIRM)

            with patch("app.services.local_audio_player.time.sleep"):
                await player.play(audio)

            loaded = pg.mixer_music.load.call_args.args[0]
            assert loaded.getvalue() == VoiceEvent.PAYMENT_CONFIRM.value.encode()
            pg.mixer_music.play.assert_called_once()

            player.close()
            pg.mixer.quit.assert_called_once()


@pytest.mark.skipif(
    not os.getenv("RUN_NETWORK_TESTS"),
    reason="Requiere conexión a internet (definir RUN_NETWORK_TESTS=1)",
)
@pytest.mark.asyncio
async def test_real_edge_tts_returns_mp3_bytes():
    audio = await TTSService().synthesize(VoiceEvent.INITIAL_WELCOME)

    assert audio is not None
    assert len(audio) > 1000
