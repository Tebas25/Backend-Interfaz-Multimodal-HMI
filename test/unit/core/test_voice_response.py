import pytest

from app.core.voice_response import VoiceEvent, build_voice_message


class TestVoiceEvent:
    def test_is_str_enum(self):
        assert isinstance(VoiceEvent.PAYMENT, str)
        assert VoiceEvent.PAYMENT.value == (
            "Por favor, escanea el código QR para realizar el pago"
        )

    def test_has_expected_events(self):
        assert {e.name for e in VoiceEvent} == {
            "INITIAL_WELCOME",
            "VISUALIZE_MENU",
            "PAYMENT",
            "PAYMENT_CONFIRM",
            "PREPARING_DRINK",
            "PREPARING_COMPLETE",
            "NOT_UNDERSTOOD",
            "DRINK_NOT_IN_MENU",
            "SHOW_INGREDIENTS",
        }


class TestBuildVoiceMessage:
    @pytest.mark.parametrize(
        "event",
        [
            VoiceEvent.INITIAL_WELCOME,
            VoiceEvent.VISUALIZE_MENU,
            VoiceEvent.PAYMENT,
            VoiceEvent.PAYMENT_CONFIRM,
            VoiceEvent.NOT_UNDERSTOOD,
            VoiceEvent.DRINK_NOT_IN_MENU,
        ],
    )
    def test_event_without_placeholders_returns_plain_text(self, event):
        assert build_voice_message(event) == event.value

    @pytest.mark.parametrize(
        "event, expected",
        [
            (
                VoiceEvent.PREPARING_DRINK,
                "En estos momentos estoy preparando tu Capuchino",
            ),
            (
                VoiceEvent.PREPARING_COMPLETE,
                "Aquí tienes tu Capuchino, ¡Disfruta y muchas gracias por utilizar nuestro sistema!",
            ),
            (VoiceEvent.SHOW_INGREDIENTS, "Aqui tienes los ingredientes de Capuchino"),
        ],
    )
    def test_event_with_placeholder_is_formatted(self, event, expected):
        assert build_voice_message(event, drink="Capuchino") == expected

    @pytest.mark.parametrize(
        "event",
        [
            VoiceEvent.PREPARING_DRINK,
            VoiceEvent.PREPARING_COMPLETE,
            VoiceEvent.SHOW_INGREDIENTS,
        ],
    )
    def test_missing_placeholder_falls_back_to_not_understood(self, event):
        assert build_voice_message(event) == VoiceEvent.NOT_UNDERSTOOD.value

    def test_wrong_kwarg_name_falls_back_to_not_understood(self):
        result = build_voice_message(VoiceEvent.PREPARING_DRINK, bebida="Mocha")
        assert result == VoiceEvent.NOT_UNDERSTOOD.value

    def test_extra_kwargs_are_ignored(self):
        result = build_voice_message(VoiceEvent.PAYMENT, drink="Mocha", extra=1)
        assert result == VoiceEvent.PAYMENT.value

    def test_returns_str(self):
        assert type(build_voice_message(VoiceEvent.PAYMENT)) is str
