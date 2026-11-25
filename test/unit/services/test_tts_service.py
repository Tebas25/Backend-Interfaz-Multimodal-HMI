from unittest.mock import MagicMock, patch

import pytest

from app.core.voice_response import VoiceEvent
from app.services.tts_service import TTSService

COMMUNICATE_PATH = "app.services.tts_service.edge_tts.Communicate"


def make_communicate(chunks):
    """Crea un mock de edge_tts.Communicate cuyo stream() emite `chunks`."""

    async def fake_stream():
        for chunk in chunks:
            yield chunk

    instance = MagicMock()
    instance.stream = fake_stream
    return MagicMock(return_value=instance)


class TestInit:
    def test_default_voice(self):
        assert TTSService().voice == "es-EC-LuisNeural"

    def test_custom_voice(self):
        assert TTSService(voice="es-ES-AlvaroNeural").voice == "es-ES-AlvaroNeural"


@pytest.mark.asyncio
class TestSynthesize:
    async def test_concatenates_audio_chunks(self):
        chunks = [
            {"type": "audio", "data": b"abc"},
            {"type": "audio", "data": b"def"},
        ]
        with patch(COMMUNICATE_PATH, make_communicate(chunks)):
            result = await TTSService().synthesize(VoiceEvent.PAYMENT)

        assert result == b"abcdef"

    async def test_ignores_non_audio_chunks(self):
        chunks = [
            {"type": "WordBoundary", "offset": 0, "text": "hola"},
            {"type": "audio", "data": b"xyz"},
            {"type": "SentenceBoundary", "text": "hola"},
        ]
        with patch(COMMUNICATE_PATH, make_communicate(chunks)):
            result = await TTSService().synthesize(VoiceEvent.PAYMENT)

        assert result == b"xyz"

    async def test_returns_none_when_no_audio(self):
        chunks = [{"type": "WordBoundary", "text": "hola"}]
        with patch(COMMUNICATE_PATH, make_communicate(chunks)):
            result = await TTSService().synthesize(VoiceEvent.PAYMENT)

        assert result is None

    async def test_returns_none_when_stream_is_empty(self):
        with patch(COMMUNICATE_PATH, make_communicate([])):
            result = await TTSService().synthesize(VoiceEvent.PAYMENT)

        assert result is None

    async def test_passes_message_and_voice_to_edge_tts(self):
        communicate = make_communicate([{"type": "audio", "data": b"a"}])
        with patch(COMMUNICATE_PATH, communicate):
            await TTSService(voice="es-ES-AlvaroNeural").synthesize(VoiceEvent.PAYMENT)

        communicate.assert_called_once_with(
            VoiceEvent.PAYMENT.value, voice="es-ES-AlvaroNeural"
        )

    async def test_formats_message_with_kwargs(self):
        communicate = make_communicate([{"type": "audio", "data": b"a"}])
        with patch(COMMUNICATE_PATH, communicate):
            await TTSService().synthesize(VoiceEvent.PREPARING_DRINK, drink="Mocha")

        message = communicate.call_args.args[0]
        assert message == "En estos momentos estoy preparando tu Mocha"

    async def test_missing_kwargs_synthesizes_not_understood(self):
        communicate = make_communicate([{"type": "audio", "data": b"a"}])
        with patch(COMMUNICATE_PATH, communicate):
            await TTSService().synthesize(VoiceEvent.PREPARING_DRINK)

        assert communicate.call_args.args[0] == VoiceEvent.NOT_UNDERSTOOD.value

    async def test_propagates_edge_tts_errors(self):
        async def failing_stream():
            raise ConnectionError("sin red")
            yield  # pragma: no cover

        instance = MagicMock()
        instance.stream = failing_stream
        with patch(COMMUNICATE_PATH, MagicMock(return_value=instance)):
            with pytest.raises(ConnectionError):
                await TTSService().synthesize(VoiceEvent.PAYMENT)
