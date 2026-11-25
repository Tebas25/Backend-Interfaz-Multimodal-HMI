from enum import Enum


class VoiceEvent(str, Enum):
    INITIAL_WELCOME = (
        "¡Hola, me llamo Rony! Pídeme una bebida o utiliza mi pantalla para ordenar"
    )
    VISUALIZE_MENU = "Explora en nuestro menú y pídeme la bebida que desees"
    PAYMENT = "Por favor, escanea el código QR para realizar el pago"
    PAYMENT_CONFIRM = "¡Muchas gracias por tu pago!"
    PREPARING_DRINK = "En estos momentos estoy preparando tu {drink}"
    PREPARING_COMPLETE = "Aquí tienes tu {drink}, ¡Disfruta y muchas gracias por utilizar nuestro sistema!"
    NOT_UNDERSTOOD = (
        "Lo lamento no he entendido a qué te refieres, ¿puedes volver a repetirlo?"
    )
    DRINK_NOT_IN_MENU = "Lo lamento, la bebida ordenada no está dentro de nuestro menú, explora nuevamente y pídeme una existente"
    SHOW_INGREDIENTS = "Aqui tienes los ingredientes de {drink}"


def build_voice_message(event: VoiceEvent, **kwargs) -> str:
    try:
        return event.value.format(**kwargs)
    except KeyError:
        return VoiceEvent.NOT_UNDERSTOOD.value
