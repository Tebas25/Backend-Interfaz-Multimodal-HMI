"""Pruebas unitarias del procesador de comandos de voz (lógica pura, sin audio)."""

import dataclasses

import pytest

from app.schemas.ws_messages import Screen
from app.services.command_processor import (
    HANDLERS,
    ORDER_WORDS,
    WAKE_WORDS,
    NavigateAction,
    VoiceAction,
    extract_command,
    handle_menu,
    handle_welcome,
    normalize,
    process_text,
)

# =====================  normalize  =====================


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("HOLA", "hola"),
        ("Quiero un trago", "quiero un trago"),
        ("menú", "menu"),
        ("Piña colada", "pina colada"),
        ("ÁÉÍÓÚ áéíóú", "aeiou aeiou"),
        ("canción", "cancion"),
        ("hola, mundo", "hola  mundo"),  # la puntuación se vuelve un espacio
        ("¿Qué hay?", " que hay "),
        ("tres bebidas 3", "tres bebidas 3"),  # los dígitos se conservan
        ("", ""),
        ("¿?!", "   "),
    ],
)
def test_normalize(texto, esperado):
    assert normalize(texto) == esperado


def test_normalize_solo_deja_letras_ascii_digitos_y_espacios():
    resultado = normalize("Ñandú, ¡Rony! #1 (menú) — café/té")

    assert all(c.isascii() and (c.isalnum() or c.isspace()) for c in resultado)


def test_normalize_es_idempotente():
    una_vez = normalize("¿Qué MENÚ tienes, Rony?")

    assert normalize(una_vez) == una_vez


# =====================  WAKE_WORDS / ORDER_WORDS  =====================


def test_wake_words_son_un_frozenset_con_las_variantes_de_rony():
    assert isinstance(WAKE_WORDS, frozenset)
    assert {"rony", "roni", "ronny", "ronnie", "ronni"} <= WAKE_WORDS


@pytest.mark.parametrize("palabra", sorted(WAKE_WORDS))
def test_cada_wake_word_ya_esta_normalizada(palabra):
    """Se comparan contra texto normalizado: deben estar en minúsculas y sin tildes."""
    assert normalize(palabra).strip() == palabra


@pytest.mark.parametrize("palabra", sorted(ORDER_WORDS))
def test_cada_palabra_de_pedido_ya_esta_normalizada(palabra):
    assert normalize(palabra).strip() == palabra


# =====================  extract_command  =====================


@pytest.mark.parametrize("variante", sorted(WAKE_WORDS))
def test_reconoce_todas_las_variantes_de_la_palabra_clave(variante):
    assert extract_command(f"{variante} quiero tomar algo") == "quiero tomar algo"


@pytest.mark.parametrize(
    "texto",
    [
        "Rony quiero tomar algo",
        "RONY quiero tomar algo",
        "rony, quiero tomar algo.",
        "¡Rony! quiero tomar algo",
    ],
)
def test_ignora_mayusculas_y_puntuacion_en_la_palabra_clave(texto):
    assert extract_command(texto) == "quiero tomar algo"


def test_devuelve_el_resto_de_la_frase_normalizado():
    assert extract_command("Rony, ¿me das el menú?") == "me das el menu"


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("quiero tomar algo Rony", "quiero tomar algo"),  # al final
        ("oye Rony quiero tomar algo", "oye quiero tomar algo"),  # en medio
        ("Rony Rony quiero tomar", "quiero tomar"),  # repetida
        ("Rony y Roni dame el menu", "y dame el menu"),  # dos variantes distintas
    ],
)
def test_la_palabra_clave_puede_estar_en_cualquier_posicion_y_se_quita_toda(
    texto, esperado
):
    assert extract_command(texto) == esperado


@pytest.mark.parametrize("texto", ["Rony", "rony.", "  RONY  ", "¡Rony!"])
def test_solo_la_palabra_clave_devuelve_cadena_vacia(texto):
    resultado = extract_command(texto)

    assert resultado == ""
    assert resultado is not None  # se distingue de "no se dijo la palabra clave"


@pytest.mark.parametrize(
    "texto",
    [
        "quiero tomar algo",
        "",
        "   ",
        "hola mundo",
        "ronyx quiero tomar",  # contiene "rony" pero no es la palabra
        "pirony menu",
        "ron y menta",
    ],
)
def test_sin_palabra_clave_devuelve_none(texto):
    assert extract_command(texto) is None


# =====================  NavigateAction  =====================


def test_navigate_action_guarda_la_pantalla():
    assert NavigateAction(Screen.MENU).screen is Screen.MENU


def test_navigate_action_es_inmutable():
    accion = NavigateAction(Screen.MENU)

    with pytest.raises(dataclasses.FrozenInstanceError):
        accion.screen = Screen.WELCOME


def test_navigate_action_se_compara_por_valor_y_se_puede_hashear():
    assert NavigateAction(Screen.MENU) == NavigateAction(Screen.MENU)
    assert NavigateAction(Screen.MENU) != NavigateAction(Screen.WELCOME)
    assert len({NavigateAction(Screen.MENU), NavigateAction(Screen.MENU)}) == 1


def test_voice_action_es_por_ahora_navigate_action():
    assert VoiceAction is NavigateAction


# =====================  handle_welcome  =====================


@pytest.mark.parametrize("palabra", sorted(ORDER_WORDS))
def test_welcome_cada_palabra_de_pedido_navega_al_menu(palabra):
    assert handle_welcome(palabra) == NavigateAction(Screen.MENU)


@pytest.mark.parametrize(
    "comando",
    [
        "quiero tomar algo",
        "dame una bebida",
        "me gustaria ver la carta",
        "puedo pedir un trago",
        "pasame el menu por favor",
    ],
)
def test_welcome_navega_al_menu_si_la_frase_contiene_una_palabra_de_pedido(comando):
    assert handle_welcome(comando) == NavigateAction(Screen.MENU)


@pytest.mark.parametrize(
    "comando", ["", "hola", "que hora es", "cuentame un chiste", "gracias"]
)
def test_welcome_sin_palabra_de_pedido_no_hace_nada(comando):
    assert handle_welcome(comando) is None


def test_welcome_compara_palabras_completas_no_fragmentos():
    assert (
        handle_welcome("ordenarlo") is None
    )  # contiene "ordenar" pero no es la palabra
    assert handle_welcome("sinmenu") is None


# =====================  handle_menu  =====================


@pytest.mark.parametrize("comando", ["", "pedir", "quiero un mojito", "volver", "menu"])
def test_menu_todavia_no_interpreta_comandos(comando):
    """Pendiente (TODO en el código): elegir bebida, confirmar, cancelar/volver.
    Cuando se implemente, esta prueba debe sustituirse por las de cada comando."""
    assert handle_menu(comando) is None


# =====================  HANDLERS  =====================


def test_cada_pantalla_tiene_su_handler():
    """Si se añade una pantalla a Screen sin handler, esta prueba obliga a definirlo."""
    assert set(HANDLERS) == set(Screen)


def test_los_handlers_registrados_son_los_de_cada_pantalla():
    assert HANDLERS[Screen.WELCOME] is handle_welcome
    assert HANDLERS[Screen.MENU] is handle_menu


# =====================  process_text  =====================


def test_desde_welcome_la_orden_de_pedir_navega_al_menu():
    assert process_text("Rony quiero tomar algo", Screen.WELCOME) == NavigateAction(
        Screen.MENU
    )


@pytest.mark.parametrize(
    "texto",
    [
        "Rony, quiero un trago",
        "RONY quiero ver la carta",
        "Roni dame el menú",
        "ronnie puedo pedir algo",
        "¿Rony, me das una bebida?",
        "quiero tomar algo, Rony",
    ],
)
def test_frases_con_la_palabra_clave_y_una_orden_de_pedido_navegan_al_menu(texto):
    assert process_text(texto, Screen.WELCOME) == NavigateAction(Screen.MENU)


@pytest.mark.parametrize(
    "texto",
    [
        "quiero tomar algo",  # sin la palabra clave
        "dame el menu por favor",
        "Rony",  # solo la palabra clave, sin orden
        "Rony hola",  # con palabra clave pero sin orden reconocida
        "",
    ],
)
def test_sin_palabra_clave_o_sin_orden_no_hay_accion(texto):
    assert process_text(texto, Screen.WELCOME) is None


def test_desde_la_pantalla_menu_la_misma_orden_no_hace_nada():
    assert process_text("Rony quiero tomar algo", Screen.MENU) is None


def test_sin_pantalla_conocida_no_hay_accion():
    assert process_text("Rony quiero tomar algo", None) is None


def test_con_una_pantalla_sin_handler_no_hay_accion():
    assert process_text("Rony quiero tomar algo", "otra_pantalla") is None


def test_usa_el_handler_de_la_pantalla_actual(monkeypatch):
    recibido = []
    monkeypatch.setitem(
        HANDLERS, Screen.MENU, lambda comando: recibido.append(comando) or "ACCION"
    )

    resultado = process_text("Rony elige el mojito", Screen.MENU)

    assert resultado == "ACCION"
    assert recibido == [
        "elige el mojito"
    ]