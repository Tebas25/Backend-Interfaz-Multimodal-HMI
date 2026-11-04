import asyncio
from typing import Awaitable, Callable, Sequence

import speech_recognition as sr

from app.models.cobot_menu_item import CobotMenuItem
from app.services.command_processor import VoiceAction, process_text
from app.services.screen_state import ScreenState


class CommandListenerService:
    def __init__(
        self,
        on_action: Callable[[VoiceAction], Awaitable[None]],
        get_items: Callable[[], Sequence[CobotMenuItem]] = lambda: (),
        language: str = "es-EC",
        phrase_time_limit: float = 6.0,
    ):
        self._on_action = on_action
        self._get_items = get_items
        self._language = language
        self._phrase_time_limit = phrase_time_limit
        self._recognizer = sr.Recognizer()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=5)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_listening = None
        self._task: asyncio.Task | None = None

    async def start(self) -> bool:
        self._loop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(self._start_microphone)
        except Exception as e:
            print(f"[Voz] Control por voz deshabilitado: {type(e).__name__}: {e}")
            return False
        self._task = asyncio.create_task(self._run(), name="command-listener")
        print("[Voz] Escuchando...")
        return True

    async def stop(self) -> None:
        if self._stop_listening:
            self._stop_listening(wait_for_stop=False)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _start_microphone(self) -> None:
        mic = sr.Microphone()
        with mic as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=1)
        self._stop_listening = self._recognizer.listen_in_background(
            mic, self._on_audio, phrase_time_limit=self._phrase_time_limit
        )

    def _on_audio(self, _recognizer, audio) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._enqueue, audio)

    def _enqueue(self, audio) -> None:
        try:
            self._queue.put_nowait(audio)
        except asyncio.QueueFull:
            print("[Voz] Cola llena, se descarta un audio")

    async def _run(self) -> None:
        while True:
            audio = await self._queue.get()
            try:
                text = await asyncio.to_thread(
                    self._recognizer.recognize_google, audio, language=self._language
                )
            except sr.UnknownValueError:
                continue
            except sr.RequestError as e:
                print(f"[Voz] Error del servicio de reconocimiento: {e}")
                continue
            except Exception as e:
                print(f"[Voz] Error inesperado: {type(e).__name__}: {e}")
                continue
            await self.handle_text(text)

    async def handle_text(self, text: str) -> None:
        print(f"[Voz] Escuché: {text!r}")
        action = process_text(text, ScreenState.current, self._get_items())
        if action is None:
            return
        print(f"[Voz] Acción: {action}")
        try:
            await self._on_action(action)
        except Exception as e:
            print(f"[Voz] Error ejecutando la acción: {type(e).__name__}: {e}")
