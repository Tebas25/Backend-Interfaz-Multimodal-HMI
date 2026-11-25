import edge_tts
import io
from app.core.voice_response import VoiceEvent, build_voice_message


class TTSService:
    def __init__(self, voice: str = "es-EC-LuisNeural"):
        self.voice = voice

    async def synthesize(self, evento: VoiceEvent, **kwargs) -> bytes | None:
        message = build_voice_message(evento, **kwargs)
        communicate = edge_tts.Communicate(message, voice=self.voice)
        with io.BytesIO() as audio_buffer:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.write(chunk["data"])

            if audio_buffer.tell() > 0:
                return audio_buffer.getvalue()
        return None
