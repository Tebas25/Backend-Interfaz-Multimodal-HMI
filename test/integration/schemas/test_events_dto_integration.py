"""Integración del DTO con Pydantic (JSON real) y con TypeAdapter,
tal como lo usa HttpRequestService."""
import json
from datetime import datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.events_dto import EventsDTO, EventosResponseDTO, TipoEvento


def payload_evento(i=1, tipo="ErrorRobot"):
    return {
        "cobot_id": "cobot-1",
        "fecha": f"2026-02-0{i}T12:00:00",
        "evento_id": f"ev-{i}",
        "tipo_evento": tipo,
        "descripcion": f"Evento {i}",
    }


def test_ida_y_vuelta_json_de_events_dto():
    original = EventsDTO(
        cobot_id="c1",
        evento_id="e1",
        tipo_evento=TipoEvento.ERROR_SISTEMA,
        descripcion="falla",
    )
    texto = json.dumps(original.model_dump(mode="json"))
    reconstruido = EventsDTO.model_validate_json(texto)
    assert reconstruido == original


def test_ida_y_vuelta_json_de_response_dto():
    original = EventosResponseDTO(**payload_evento())
    texto = original.model_dump_json()
    reconstruido = EventosResponseDTO.model_validate_json(texto)
    assert reconstruido == original
    assert isinstance(reconstruido.fecha, datetime)


def test_lista_de_response_dto_con_type_adapter():
    datos = [payload_evento(1), payload_evento(2, "Warning")]
    lista = TypeAdapter(list[EventosResponseDTO]).validate_python(datos)
    assert len(lista) == 2
    assert lista[1].tipo_evento is TipoEvento.WARNING


def test_lista_vacia():
    assert TypeAdapter(list[EventosResponseDTO]).validate_python([]) == []


def test_lista_con_un_elemento_invalido_falla():
    datos = [payload_evento(1), {"cobot_id": "x"}]
    with pytest.raises(ValidationError):
        TypeAdapter(list[EventosResponseDTO]).validate_python(datos)


def test_serializacion_de_lista_a_json_valido():
    lista = TypeAdapter(list[EventosResponseDTO]).validate_python(
        [payload_evento(1), payload_evento(2)]
    )
    texto = TypeAdapter(list[EventosResponseDTO]).dump_json(lista)
    assert [e["evento_id"] for e in json.loads(texto)] == ["ev-1", "ev-2"]


@pytest.mark.parametrize("tipo", [t.value for t in TipoEvento])
def test_todos_los_tipos_de_evento_viajan_por_json(tipo):
    dto = EventosResponseDTO.model_validate_json(json.dumps(payload_evento(1, tipo)))
    assert dto.tipo_evento.value == tipo