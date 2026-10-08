from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.events_dto import EventsDTO, EventosResponseDTO, TipoEvento


class TestTipoEvento:
    def test_valores_del_enum(self):
        assert TipoEvento.INFO_ROBOT.value == "InfoRobot"
        assert TipoEvento.INFO_SISTEMA.value == "InfoSistema"
        assert TipoEvento.WARNING.value == "Warning"
        assert TipoEvento.ERROR_ROBOT.value == "ErrorRobot"
        assert TipoEvento.ERROR_SISTEMA.value == "ErrorSistema"

    def test_es_subclase_de_str(self):
        assert isinstance(TipoEvento.WARNING, str)
        assert TipoEvento.WARNING == "Warning"

    def test_construir_desde_valor(self):
        assert TipoEvento("ErrorRobot") is TipoEvento.ERROR_ROBOT

    def test_valor_invalido(self):
        with pytest.raises(ValueError):
            TipoEvento("NoExiste")


class TestEventsDTO:
    def datos(self, **cambios):
        base = {
            "cobot_id": "cobot-1",
            "evento_id": "ev-1",
            "tipo_evento": "Warning",
            "descripcion": "Temperatura alta",
        }
        base.update(cambios)
        return base

    def test_creacion_valida(self):
        dto = EventsDTO(**self.datos())
        assert dto.cobot_id == "cobot-1"
        assert dto.evento_id == "ev-1"
        assert dto.tipo_evento is TipoEvento.WARNING
        assert dto.descripcion == "Temperatura alta"

    def test_acepta_enum_directamente(self):
        dto = EventsDTO(**self.datos(tipo_evento=TipoEvento.ERROR_SISTEMA))
        assert dto.tipo_evento is TipoEvento.ERROR_SISTEMA

    @pytest.mark.parametrize(
        "campo", ["cobot_id", "evento_id", "tipo_evento", "descripcion"]
    )
    def test_campo_obligatorio_faltante(self, campo):
        datos = self.datos()
        del datos[campo]
        with pytest.raises(ValidationError):
            EventsDTO(**datos)

    def test_tipo_evento_invalido(self):
        with pytest.raises(ValidationError):
            EventsDTO(**self.datos(tipo_evento="Otro"))

    def test_model_dump_modo_json(self):
        dump = EventsDTO(**self.datos()).model_dump(mode="json")
        assert dump["tipo_evento"] == "Warning"


class TestEventosResponseDTO:
    def datos(self, **cambios):
        base = {
            "cobot_id": "cobot-1",
            "fecha": "2026-01-15T10:30:00",
            "evento_id": "ev-1",
            "tipo_evento": "InfoRobot",
            "descripcion": "Inicio de ciclo",
        }
        base.update(cambios)
        return base

    def test_creacion_valida_y_parseo_de_fecha(self):
        dto = EventosResponseDTO(**self.datos())
        assert dto.fecha == datetime(2026, 1, 15, 10, 30, 0)
        assert dto.tipo_evento is TipoEvento.INFO_ROBOT

    def test_acepta_datetime_directamente(self):
        fecha = datetime(2026, 5, 1, 8, 0)
        assert EventosResponseDTO(**self.datos(fecha=fecha)).fecha == fecha

    @pytest.mark.parametrize(
        "campo",
        ["cobot_id", "fecha", "evento_id", "tipo_evento", "descripcion"],
    )
    def test_campo_obligatorio_faltante(self, campo):
        datos = self.datos()
        del datos[campo]
        with pytest.raises(ValidationError):
            EventosResponseDTO(**datos)

    def test_fecha_invalida(self):
        with pytest.raises(ValidationError):
            EventosResponseDTO(**self.datos(fecha="no-es-fecha"))

    def test_tipo_evento_invalido(self):
        with pytest.raises(ValidationError):
            EventosResponseDTO(**self.datos(tipo_evento="Otro"))