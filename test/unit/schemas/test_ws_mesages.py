"""Pruebas unitarias de los modelos de mensajes del websocket."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.events_dto import TipoEvento
from app.schemas.get_catalog_dto import CobotCatalogResponse
from app.schemas.ws_messages import (
    CatalogUpdate,
    CatalogUpdatePayload,
    CloseIngredients,
    CobotStatus,
    CobotStatusPayload,
    DrinkRefPayload,
    EmptyPayload,
    ErrorMessage,
    ErrorPayload,
    FrontState,
    Navigate,
    NavigatePayload,
    Screen,
    SelectDrink,
    ServerMessage,
    ShowIngredients,
    StatePayload,
    StateSource,
    build_catalog_update,
    client_adapter,
)

server_adapter = TypeAdapter(ServerMessage)


@pytest.fixture
def catalogo(make_item):
    items = [make_item(nombre="Mojito"), make_item(nombre="Daiquiri")]
    return CobotCatalogResponse(items=items, total=len(items))


# ---------- Envelope ----------


def test_envelope_genera_id_unico_en_hex():
    a = Navigate(payload=NavigatePayload(screen=Screen.MENU))
    b = Navigate(payload=NavigatePayload(screen=Screen.MENU))

    assert a.id != b.id
    assert len(a.id) == 32
    int(a.id, 16)  # es hexadecimal


def test_envelope_ts_es_aware_y_en_utc():
    msg = Navigate(payload=NavigatePayload(screen=Screen.MENU))

    assert msg.ts.tzinfo is not None
    assert msg.ts.utcoffset() == timedelta(0)


def test_extra_forbid_rechaza_campos_desconocidos():
    with pytest.raises(ValidationError):
        NavigatePayload(screen="menu", campo_extra=1)


def test_screen_invalida_es_rechazada():
    with pytest.raises(ValidationError):
        NavigatePayload(screen="no_existe")


# ---------- StatePayload ----------


def test_state_backend_con_ref_es_valido():
    p = StatePayload(screen=Screen.MENU, source=StateSource.BACKEND, ref="abc")

    assert p.ref == "abc"


def test_state_backend_sin_ref_es_invalido():
    with pytest.raises(ValidationError, match="ref es obligatorio"):
        StatePayload(screen=Screen.MENU, source=StateSource.BACKEND)


def test_state_backend_con_ref_vacio_es_invalido():
    with pytest.raises(ValidationError, match="ref es obligatorio"):
        StatePayload(screen=Screen.MENU, source=StateSource.BACKEND, ref="")


@pytest.mark.parametrize("source", [StateSource.TOUCH, StateSource.INIT])
def test_state_sin_ref_es_valido_para_touch_e_init(source):
    p = StatePayload(screen=Screen.MENU, source=source)

    assert p.ref is None


@pytest.mark.parametrize("source", [StateSource.TOUCH, StateSource.INIT])
def test_state_con_ref_es_invalido_para_touch_e_init(source):
    with pytest.raises(ValidationError, match="ref solo se permite"):
        StatePayload(screen=Screen.MENU, source=source, ref="abc")


# ---------- client_adapter (Front -> Backend) ----------


def test_client_adapter_parsea_un_state_valido():
    raw = '{"type":"state","payload":{"screen":"menu","source":"touch"}}'

    msg = client_adapter.validate_json(raw)

    assert isinstance(msg, FrontState)
    assert msg.payload.screen is Screen.MENU
    assert msg.payload.source is StateSource.TOUCH


def test_client_adapter_rechaza_type_desconocido():
    raw = '{"type":"otro","payload":{"screen":"menu","source":"touch"}}'

    with pytest.raises(ValidationError):
        client_adapter.validate_json(raw)


def test_client_adapter_rechaza_payload_incompleto():
    with pytest.raises(ValidationError):
        client_adapter.validate_json('{"type":"state","payload":{}}')


def test_client_adapter_rechaza_json_malformado():
    with pytest.raises(ValidationError):
        client_adapter.validate_json("no es json")


# ---------- ServerMessage (Backend -> Front) ----------


def test_server_message_discrimina_navigate():
    msg = server_adapter.validate_python(
        {"type": "navigate", "payload": {"screen": "menu"}}
    )

    assert isinstance(msg, Navigate)


def test_server_message_discrimina_error():
    msg = server_adapter.validate_python(
        {"type": "error", "payload": {"detail": [{"loc": ["x"], "msg": "mal"}]}}
    )

    assert isinstance(msg, ErrorMessage)
    assert msg.payload.detail[0]["msg"] == "mal"


def test_server_message_discrimina_catalog_update(catalogo):
    original = CatalogUpdate(
        payload=CatalogUpdatePayload(ultima_actualizacion="f1", catalogo=catalogo)
    )

    msg = server_adapter.validate_python(original.model_dump(mode="json"))

    assert isinstance(msg, CatalogUpdate)
    assert msg.payload.catalogo.total == 2


def test_server_message_rechaza_type_desconocido():
    with pytest.raises(ValidationError):
        server_adapter.validate_python({"type": "xyz", "payload": {}})


def test_catalog_update_ida_y_vuelta_json(catalogo):
    original = CatalogUpdate(
        payload=CatalogUpdatePayload(ultima_actualizacion="f1", catalogo=catalogo)
    )

    recuperado = server_adapter.validate_json(original.model_dump_json())

    assert recuperado == original


def test_error_message_se_construye_con_detalle():
    msg = ErrorMessage(payload=ErrorPayload(detail=[{"msg": "inválido"}]))

    assert msg.type == "error"


# ---------- build_catalog_update ----------


def _watcher(catalogo, fecha, activos):
    return SimpleNamespace(
        catalogo=catalogo, ultima_actualizacion=fecha, items_activos=activos
    )


def test_build_catalog_update_sin_catalogo_devuelve_none():
    assert build_catalog_update(_watcher(None, "f1", [])) is None


def test_build_catalog_update_sin_fecha_devuelve_none(catalogo):
    assert build_catalog_update(_watcher(catalogo, None, [])) is None


def test_build_catalog_update_incluye_solo_items_activos(make_item, catalogo):
    activo = make_item(nombre="Mojito", estado=True)

    msg = build_catalog_update(_watcher(catalogo, "f1", [activo]))

    assert isinstance(msg, CatalogUpdate)
    assert msg.payload.ultima_actualizacion == "f1"
    assert msg.payload.catalogo.items == [activo]
    assert msg.payload.catalogo.total == 1


def test_build_catalog_update_con_cero_activos_envia_catalogo_vacio(catalogo):
    msg = build_catalog_update(_watcher(catalogo, "f1", []))

    assert msg.payload.catalogo.items == []
    assert msg.payload.catalogo.total == 0


# ---------- nombres de pantalla (contrato con el frontend WPF) ----------


def test_screen_tiene_exactamente_los_nombres_que_usa_el_frontend():
    assert {s.value for s in Screen} == {
        "menu",
        "welcome",
        "payment",
        "payment_result",
    }


@pytest.mark.parametrize("pantalla", ["menu", "welcome", "payment"])
def test_navigate_acepta_las_pantallas_del_frontend(pantalla):
    msg = server_adapter.validate_python(
        {"type": "navigate", "payload": {"screen": pantalla}}
    )

    assert msg.payload.screen.value == pantalla


@pytest.mark.parametrize("pantalla", ["menu", "welcome", "payment"])
def test_state_acepta_las_pantallas_del_frontend(pantalla):
    raw = f'{{"type":"state","payload":{{"screen":"{pantalla}","source":"touch"}}}}'

    msg = client_adapter.validate_json(raw)

    assert msg.payload.screen.value == pantalla


def test_state_rechaza_el_nombre_antiguo_con_error_tipografico():
    raw = '{"type":"state","payload":{"screen":"welome","source":"touch"}}'

    with pytest.raises(ValidationError):
        client_adapter.validate_json(raw)


# ---------- Mensajes de voz: select_drink / show_ingredients / close_ingredients


@pytest.mark.parametrize(
    "clase, tipo",
    [(SelectDrink, "select_drink"), (ShowIngredients, "show_ingredients")],
)
def test_mensajes_de_bebida_llevan_su_tipo_y_el_nombre(clase, tipo):
    msg = clase(payload=DrinkRefPayload(name="Piña colada"))

    datos = msg.model_dump(mode="json")

    assert datos["type"] == tipo
    assert datos["payload"] == {"name": "Piña colada"}


@pytest.mark.parametrize("clase", [SelectDrink, ShowIngredients])
def test_mensajes_de_bebida_tienen_id_y_fecha_como_todo_sobre(clase):
    msg = clase(payload=DrinkRefPayload(name="Mojito"))

    assert len(msg.id) == 32
    assert msg.ts.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("clase", [SelectDrink, ShowIngredients])
def test_mensajes_de_bebida_exigen_el_nombre(clase):
    with pytest.raises(ValidationError):
        clase.model_validate({"payload": {}})
    with pytest.raises(ValidationError):
        clase.model_validate({})


@pytest.mark.parametrize("clase", [SelectDrink, ShowIngredients])
def test_mensajes_de_bebida_rechazan_campos_extra(clase):
    with pytest.raises(ValidationError):
        clase.model_validate({"payload": {"name": "Mojito", "precio": 5}})


@pytest.mark.parametrize("clase", [SelectDrink, ShowIngredients])
def test_mensajes_de_bebida_ida_y_vuelta_json(clase):
    original = clase(payload=DrinkRefPayload(name="Mojito"))

    copia = clase.model_validate_json(original.model_dump_json())

    assert copia == original


def test_el_tipo_de_un_mensaje_de_bebida_no_se_puede_cambiar_por_otro():
    with pytest.raises(ValidationError):
        SelectDrink.model_validate(
            {"type": "show_ingredients", "payload": {"name": "Mojito"}}
        )


def test_close_ingredients_no_necesita_datos():
    msg = CloseIngredients()

    datos = msg.model_dump(mode="json")

    assert datos["type"] == "close_ingredients"
    assert datos["payload"] == {}
    assert isinstance(msg.payload, EmptyPayload)


def test_close_ingredients_acepta_payload_vacio_y_rechaza_datos():
    assert CloseIngredients.model_validate({"payload": {}}).payload == EmptyPayload()
    with pytest.raises(ValidationError):
        CloseIngredients.model_validate({"payload": {"name": "Mojito"}})


def test_empty_payload_rechaza_campos_extra():
    with pytest.raises(ValidationError):
        EmptyPayload.model_validate({"x": 1})


def test_cada_mensaje_nuevo_genera_su_propio_id():
    assert CloseIngredients().id != CloseIngredients().id


@pytest.mark.parametrize(
    "mensaje",
    [
        {"type": "select_drink", "payload": {"name": "Mojito"}},
        {"type": "show_ingredients", "payload": {"name": "Mojito"}},
        {"type": "close_ingredients", "payload": {}},
    ],
)
def test_server_message_incluye_los_mensajes_de_bebida(mensaje):
    assert server_adapter.validate_python(mensaje).type == mensaje["type"]


def test_server_message_incluye_cobot_status():
    original = CobotStatus(
        payload=CobotStatusPayload(
            codigo=1,
            tipo_evento=next(iter(TipoEvento)),
            descripcion="ok",
        )
    )

    recibido = server_adapter.validate_python(original.model_dump(mode="json"))

    assert isinstance(recibido, CobotStatus)
    assert recibido == original