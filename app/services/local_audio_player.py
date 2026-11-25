import pygame
import time
import io
import asyncio


class LocalAudioPlayer:
    def __init__(self) -> None:
        pygame.init()
        pygame.mixer.init()

    def _play_mp3_bytes(self, audio_bytes: bytes):
        audio_stream = io.BytesIO(audio_bytes)
        audio_stream.seek(0)
        pygame.mixer_music.load(audio_stream, namehint="mp3")
        pygame.mixer_music.play()

        while pygame.mixer_music.get_busy():
            time.sleep(0.05)

    async def play(self, audio_bytes: bytes):
        await asyncio.to_thread(self._play_mp3_bytes, audio_bytes)

    def close(self) -> None:
        if pygame.mixer.get_init():
            pygame.mixer.quit()
