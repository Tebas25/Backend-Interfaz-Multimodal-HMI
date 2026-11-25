import io
from unittest.mock import MagicMock, patch

import pytest

from app.services.local_audio_player import LocalAudioPlayer

MODULE = "app.services.local_audio_player"


@pytest.fixture
def mock_pygame():
    with patch(f"{MODULE}.pygame") as pg:
        yield pg


class TestInit:
    def test_initializes_pygame_and_mixer(self, mock_pygame):
        LocalAudioPlayer()

        mock_pygame.init.assert_called_once()
        mock_pygame.mixer.init.assert_called_once()


class TestPlayMp3Bytes:
    def test_loads_and_plays_audio(self, mock_pygame):
        mock_pygame.mixer_music.get_busy.return_value = False
        player = LocalAudioPlayer()

        player._play_mp3_bytes(b"fake-mp3")

        mock_pygame.mixer_music.load.assert_called_once()
        loaded_stream = mock_pygame.mixer_music.load.call_args.args[0]
        assert isinstance(loaded_stream, io.BytesIO)
        assert loaded_stream.getvalue() == b"fake-mp3"
        assert loaded_stream.tell() == 0
        assert mock_pygame.mixer_music.load.call_args.kwargs == {"namehint": "mp3"}
        mock_pygame.mixer_music.play.assert_called_once()

    def test_waits_while_music_is_busy(self, mock_pygame):
        mock_pygame.mixer_music.get_busy.side_effect = [True, True, False]
        player = LocalAudioPlayer()

        with patch(f"{MODULE}.time.sleep") as sleep:
            player._play_mp3_bytes(b"fake-mp3")

        assert mock_pygame.mixer_music.get_busy.call_count == 3
        assert sleep.call_count == 2
        sleep.assert_called_with(0.05)

    def test_does_not_sleep_if_audio_finishes_immediately(self, mock_pygame):
        mock_pygame.mixer_music.get_busy.return_value = False
        player = LocalAudioPlayer()

        with patch(f"{MODULE}.time.sleep") as sleep:
            player._play_mp3_bytes(b"fake-mp3")

        sleep.assert_not_called()

    def test_load_error_is_propagated(self, mock_pygame):
        mock_pygame.mixer_music.load.side_effect = RuntimeError("formato inválido")
        player = LocalAudioPlayer()

        with pytest.raises(RuntimeError):
            player._play_mp3_bytes(b"basura")
        mock_pygame.mixer_music.play.assert_not_called()


@pytest.mark.asyncio
class TestPlay:
    async def test_runs_playback_in_thread(self, mock_pygame):
        player = LocalAudioPlayer()

        with patch.object(player, "_play_mp3_bytes", MagicMock()) as play_bytes:
            await player.play(b"audio")

        play_bytes.assert_called_once_with(b"audio")

    async def test_propagates_errors_from_thread(self, mock_pygame):
        player = LocalAudioPlayer()

        with patch.object(
            player, "_play_mp3_bytes", MagicMock(side_effect=RuntimeError("boom"))
        ):
            with pytest.raises(RuntimeError):
                await player.play(b"audio")


class TestClose:
    def test_quits_mixer_when_initialized(self, mock_pygame):
        mock_pygame.mixer.get_init.return_value = (44100, -16, 2)
        player = LocalAudioPlayer()

        player.close()

        mock_pygame.mixer.quit.assert_called_once()

    def test_does_not_quit_when_not_initialized(self, mock_pygame):
        mock_pygame.mixer.get_init.return_value = None
        player = LocalAudioPlayer()

        player.close()

        mock_pygame.mixer.quit.assert_not_called()
