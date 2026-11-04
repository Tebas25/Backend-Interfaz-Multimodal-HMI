import dataclasses
import typing
from decimal import Decimal

import pytest

from app.models.cobot_menu_item import CobotMenuItem
from app.schemas.ws_messages import Screen
from app.services.command_processor import (
    CLOSE_WORDS,
    HANDLERS,
    INGREDIENT_WORDS,
    ORDER_WORDS,
    WAKE_WORDS,
    CloseIngredientsAction,
    NavigateAction,
    SelectDrinkAction,
    ShowIngredientsAction,
    VoiceAction,
    extract_command,
    find_drink,
    handle_menu,
    handle_welcome,
    normalize,
    process_text,
)


def bebida(nombre: str, estado: bool = True) -> CobotMenuItem:
    return CobotMenuItem(
        nombre_item=nombre,
        ingredientes="Ron, menta",
        imagen=None,
        codigo_modbus=1,
        estado=estado,
        precio_item=Decimal("5.50"),
    )


MOJITO = bebida("Mojito")
DAIQUIRI = bebida("Daiquiri")
PINA = bebida("Piña colada")
MENU_DE_PRUEBA = (MOJITO, DAIQUIRI, PINA)

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
        ("hola, mundo", "hola  mundo"),
        ("¿Qué hay?", " que hay "),
        ("tres bebidas 3", "tres bebidas 3"),
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
    assert normalize(palabra).strip() == palabra


@pytest.mark.parametrize("palabra", sorted(ORDER_WORDS))
def test_cada_palabra_de_pedido_ya_esta_normalizada(palabra):
    assert normalize(palabra).strip() == palabra


# =====================  extract_command  =====================


@pytest.mark.parametrize("palabra", sorted(INGREDIENT_WORDS))
def test_cada_palabra_de_ingredientes_ya_esta_normalizada(palabra):
    assert normalize(palabra).strip() == palabra


@pytest.mark.parametrize("palabra", sorted(CLOSE_WORDS))
def test_cada_palabra_de_cierre_ya_esta_normalizada(palabra):
    assert normalize(palabra).strip() == palabra


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
        ("quiero tomar algo Rony", "quiero tomar algo"),
        ("oye Rony quiero tomar algo", "oye quiero tomar algo"),
        ("Rony Rony quiero tomar", "quiero tomar"),
        ("Rony y Roni dame el menu", "y dame el menu"),
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
    assert resultado is not None


@pytest.mark.parametrize(
    "texto",
    [
        "quiero tomar algo",
        "",
        "   ",
        "hola mundo",
        "ronyx quiero tomar",
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
        setattr(accion, "screen", Screen.WELCOME)

    assert accion.screen is Screen.MENU


def test_navigate_action_se_compara_por_valor_y_se_puede_hashear():
    assert NavigateAction(Screen.MENU) == NavigateAction(Screen.MENU)
    assert NavigateAction(Screen.MENU) != NavigateAction(Screen.WELCOME)
    assert len({NavigateAction(Screen.MENU), NavigateAction(Screen.MENU)}) == 1


def test_voice_action_agrupa_todas_las_acciones():
    assert set(typing.get_args(VoiceAction)) == {
        NavigateAction,
        SelectDrinkAction,
        ShowIngredientsAction,
        CloseIngredientsAction,
    }


# =====================  acciones de bebida  =====================


@pytest.mark.parametrize("clase", [SelectDrinkAction, ShowIngredientsAction])
def test_las_acciones_de_bebida_guardan_el_nombre(clase):
    assert clase("Mojito").name == "Mojito"


@pytest.mark.parametrize("clase", [SelectDrinkAction, ShowIngredientsAction])
def test_las_acciones_de_bebida_son_inmutables(clase):
    accion = clase("Mojito")

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(accion, "name", "Otro")

    assert accion.name == "Mojito"


@pytest.mark.parametrize("clase", [SelectDrinkAction, ShowIngredientsAction])
def test_las_acciones_de_bebida_se_comparan_por_valor(clase):
    assert clase("Mojito") == clase("Mojito")
    assert clase("Mojito") != clase("Daiquiri")
    assert len({clase("Mojito"), clase("Mojito")}) == 1


def test_seleccionar_y_mostrar_ingredientes_son_acciones_distintas():
    assert SelectDrinkAction("Mojito") != ShowIngredientsAction("Mojito")


def test_close_ingredients_action_no_tiene_datos_y_es_inmutable():
    assert CloseIngredientsAction() == CloseIngredientsAction()
    assert CloseIngredientsAction() != NavigateAction(Screen.MENU)
    assert dataclasses.fields(CloseIngredientsAction) == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(CloseIngredientsAction(), "x", 1)


# =====================  handle_welcome  =====================


@pytest.mark.parametrize("palabra", sorted(ORDER_WORDS))
def test_welcome_cada_palabra_de_pedido_navega_al_menu(palabra):
    assert handle_welcome(palabra, ()) == NavigateAction(Screen.MENU)


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
    assert handle_welcome(comando, ()) == NavigateAction(Screen.MENU)


@pytest.mark.parametrize(
    "comando", ["", "hola", "que hora es", "cuentame un chiste", "gracias"]
)
def test_welcome_sin_palabra_de_pedido_no_hace_nada(comando):
    assert handle_welcome(comando, ()) is None


def test_welcome_compara_palabras_completas_no_fragmentos():
    assert (
        handle_welcome("ordenarlo", ()) is None
    )  # contiene "ordenar" pero no es la palabra
    assert handle_welcome("sinmenu", ()) is None


# =====================  handle_menu  =====================


def test_welcome_ignora_las_bebidas_del_menu():
    assert handle_welcome("quiero un mojito", MENU_DE_PRUEBA) is None
    assert handle_welcome("tomar un mojito", MENU_DE_PRUEBA) == NavigateAction(
        Screen.MENU
    )


# =====================  find_drink  =====================


def test_find_drink_sin_bebidas_devuelve_none():
    assert find_drink("quiero un mojito", ()) is None


def test_find_drink_encuentra_la_bebida_nombrada():
    assert find_drink("quiero un mojito", MENU_DE_PRUEBA) is MOJITO


def test_find_drink_ignora_tildes_y_mayusculas_del_nombre_en_el_catalogo():
    assert find_drink("quiero una pina colada", MENU_DE_PRUEBA) is PINA


def test_find_drink_nombre_de_varias_palabras_debe_estar_completo():
    assert find_drink("una pina", (PINA,)) is None
    assert find_drink("una pina colada bien fria", (PINA,)) is PINA


def test_find_drink_acepta_el_nombre_dicho_sin_espacios():
    assert find_drink("dame pinacolada", (PINA,)) is PINA


def test_find_drink_entre_varias_coincidencias_gana_el_nombre_mas_largo():
    corto = bebida("Mojito")
    largo = bebida("Mojito de fresa")

    assert find_drink("quiero un mojito de fresa", (corto, largo)) is largo
    assert find_drink("quiero un mojito de fresa", (largo, corto)) is largo
    assert find_drink("quiero un mojito", (corto, largo)) is corto


def test_find_drink_acepta_el_plural_por_coincidencia_aproximada():
    assert find_drink("dame dos mojitos", (MOJITO,)) is MOJITO


@pytest.mark.parametrize("dicho", ["mohito", "mojita", "moxito"])
def test_find_drink_tolera_pequenos_errores_de_reconocimiento(dicho):
    assert find_drink(f"quiero un {dicho}", MENU_DE_PRUEBA) is MOJITO


def test_find_drink_la_coincidencia_aproximada_funciona_con_nombres_largos():
    assert find_drink("dame una pina colda", (PINA,)) is PINA


@pytest.mark.parametrize("comando", ["quiero algo", "hola", "tequila sunrise", ""])
def test_find_drink_sin_parecido_suficiente_devuelve_none(comando):
    assert find_drink(comando, MENU_DE_PRUEBA) is None


def test_find_drink_elige_la_mas_parecida_si_hay_varias_aproximadas():
    margarita = bebida("Margarita")

    assert find_drink("una margarta", (MOJITO, margarita)) is margarita


def test_find_drink_ignora_bebidas_sin_nombre_utilizable():
    sin_nombre = bebida("")
    solo_signos = bebida("¿?")

    assert find_drink("quiero un mojito", (sin_nombre, solo_signos)) is None
    assert find_drink("quiero un mojito", (sin_nombre, MOJITO)) is MOJITO


def test_find_drink_no_modifica_el_orden_ni_el_contenido_de_las_bebidas():
    items = [MOJITO, DAIQUIRI]

    find_drink("un daiquiri", items)

    assert items == [MOJITO, DAIQUIRI]
    assert MOJITO.nombre_item == "Mojito"


# =====================  handle_menu  =====================


def test_menu_nombrar_una_bebida_la_selecciona():
    assert handle_menu("quiero un mojito", MENU_DE_PRUEBA) == SelectDrinkAction(
        "Mojito"
    )


def test_menu_la_accion_usa_el_nombre_original_del_catalogo():
    assert handle_menu("dame la pina colada", MENU_DE_PRUEBA) == SelectDrinkAction(
        "Piña colada"
    )


@pytest.mark.parametrize("palabra", sorted(INGREDIENT_WORDS))
def test_menu_pedir_ingredientes_de_una_bebida_los_muestra(palabra):
    assert handle_menu(f"{palabra} mojito", MENU_DE_PRUEBA) == ShowIngredientsAction(
        "Mojito"
    )


@pytest.mark.parametrize(
    "comando",
    [
        "que ingredientes tiene el daiquiri",
        "de que esta hecho el daiquiri",
        "que lleva el daiquiri",
        "daiquiri receta",
    ],
)
def test_menu_frases_naturales_de_ingredientes(comando):
    assert handle_menu(comando, MENU_DE_PRUEBA) == ShowIngredientsAction("Daiquiri")


@pytest.mark.parametrize("palabra", sorted(CLOSE_WORDS))
def test_menu_cada_palabra_de_cierre_cierra_los_ingredientes(palabra):
    assert handle_menu(palabra, MENU_DE_PRUEBA) == CloseIngredientsAction()


def test_menu_cerrar_funciona_aunque_no_haya_bebidas():
    assert handle_menu("cerrar", ()) == CloseIngredientsAction()


def test_menu_cerrar_tiene_prioridad_sobre_la_bebida_nombrada():
    assert handle_menu("cierra el mojito", MENU_DE_PRUEBA) == CloseIngredientsAction()


def test_menu_ingredientes_tienen_prioridad_sobre_seleccionar():
    accion = handle_menu("ingredientes del mojito", MENU_DE_PRUEBA)

    assert isinstance(accion, ShowIngredientsAction)


@pytest.mark.parametrize(
    "comando", ["", "hola", "ingredientes", "que lleva", "quiero tomar algo", "tequila"]
)
def test_menu_sin_una_bebida_conocida_no_hace_nada(comando):
    assert handle_menu(comando, MENU_DE_PRUEBA) is None


def test_menu_sin_bebidas_cargadas_no_selecciona_nada():
    assert handle_menu("quiero un mojito", ()) is None


def test_menu_no_navega_con_las_palabras_de_pedido():
    assert handle_menu("quiero tomar algo", MENU_DE_PRUEBA) is None


# =====================  HANDLERS  =====================


def test_todos_los_handlers_registrados_son_de_pantallas_validas():
    assert set(HANDLERS) <= set(Screen)
    assert {Screen.WELCOME, Screen.MENU} <= set(HANDLERS)


@pytest.mark.parametrize("pantalla", sorted(set(Screen) - set(HANDLERS)))
def test_una_pantalla_sin_handler_no_genera_acciones(pantalla):
    for frase in ("Rony quiero tomar algo", "Rony un mojito", "Rony cierra"):
        assert process_text(frase, pantalla, MENU_DE_PRUEBA) is None


def test_los_handlers_registrados_son_los_de_cada_pantalla():
    assert HANDLERS[Screen.WELCOME] is handle_welcome
    assert HANDLERS[Screen.MENU] is handle_menu




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
        "quiero tomar algo",
        "dame el menu por favor",
        "Rony",
        "Rony hola",
        "",
    ],
)
def test_sin_palabra_clave_o_sin_orden_no_hay_accion(texto):
    assert process_text(texto, Screen.WELCOME) is None


def test_desde_la_pantalla_menu_la_misma_orden_no_hace_nada():
    assert process_text("Rony quiero tomar algo", Screen.MENU, MENU_DE_PRUEBA) is None


def test_process_text_en_menu_selecciona_la_bebida_nombrada():
    accion = process_text("Rony, quiero un Mojito", Screen.MENU, MENU_DE_PRUEBA)

    assert accion == SelectDrinkAction("Mojito")


def test_process_text_en_menu_muestra_los_ingredientes():
    accion = process_text("Rony, ¿qué lleva el Daiquirí?", Screen.MENU, MENU_DE_PRUEBA)

    assert accion == ShowIngredientsAction("Daiquiri")


def test_process_text_en_menu_cierra_los_ingredientes():
    assert process_text("Rony, cierra eso", Screen.MENU, MENU_DE_PRUEBA) == (
        CloseIngredientsAction()
    )


def test_process_text_en_menu_sin_la_palabra_clave_no_hace_nada():
    assert process_text("quiero un mojito", Screen.MENU, MENU_DE_PRUEBA) is None


def test_process_text_en_welcome_no_selecciona_bebidas():
    assert process_text("Rony quiero un mojito", Screen.WELCOME, MENU_DE_PRUEBA) is None


def test_process_text_sin_bebidas_por_defecto_no_selecciona_nada():
    assert process_text("Rony quiero un mojito", Screen.MENU) is None


def test_process_text_las_bebidas_se_leen_en_cada_llamada():
    assert process_text("Rony un mojito", Screen.MENU, ()) is None
    assert process_text("Rony un mojito", Screen.MENU, (MOJITO,)) == (
        SelectDrinkAction("Mojito")
    )


def test_sin_pantalla_conocida_no_hay_accion():
    assert process_text("Rony quiero tomar algo", None) is None


def test_con_una_pantalla_sin_handler_no_hay_accion():
    assert process_text("Rony quiero tomar algo", "otra_pantalla") is None


def test_usa_el_handler_de_la_pantalla_actual(monkeypatch):
    recibido = []
    monkeypatch.setitem(
        HANDLERS,
        Screen.MENU,
        lambda comando, items: recibido.append((comando, items)) or "ACCION",
    )

    resultado = process_text("Rony elige el mojito", Screen.MENU, MENU_DE_PRUEBA)

    assert resultado == "ACCION"
    assert recibido == [("elige el mojito", MENU_DE_PRUEBA)]