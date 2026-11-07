from app.schemas.events_dto import EventsDTO, TipoEvento

COBOT_ID = "CBT000T"
DEFAULT_EVENT_ID = "EVT-001"
ORDER_REGISTER = 0
STATUS_REGISTER = 1
DEFAULT_VALUE = 0
CONNECTION_LOST_CODE = 999
MAX_REGISTER_VALUE = 65535
STATE_IDLE = 0
STATE_PREPARING = 102
STATE_DELIVERED = 200
CRITICAL_STATES = {404, 500, 501, 503, CONNECTION_LOST_CODE}


def _evento(codigo: int, tipo: TipoEvento, descripcion: str) -> EventsDTO:
    return EventsDTO(
        cobot_id=COBOT_ID,
        evento_id=DEFAULT_EVENT_ID,
        codigo=codigo,
        tipo_evento=tipo,
        descripcion=descripcion,
    )


cobot_logs: dict[int, EventsDTO] = {
    100: _evento(
        100, TipoEvento.INFO_ROBOT, "El cobot a iniciado y esta listo para trabajar"
    ),
    101: _evento(101, TipoEvento.INFO_ROBOT, "Orden recibida y validada por el cobot"),
    102: _evento(102, TipoEvento.INFO_ROBOT, "El cobot está preparando la bebida"),
    200: _evento(200, TipoEvento.INFO_ROBOT, "El cobot ha entregado la bebida"),
    301: _evento(
        301, TipoEvento.WARNING, "El cobot no ha comprendido el tipo de bebida"
    ),
    306: _evento(
        306,
        TipoEvento.WARNING,
        "El cobot se ha detenido parcialmente por riesgo a colisión",
    ),
    307: _evento(
        307, TipoEvento.WARNING, "Obstáculos presentes al momento de entregar la bebida"
    ),
    404: _evento(
        404,
        TipoEvento.ERROR_ROBOT,
        "Falta de vaso o botella/insumo agotado en la estación",
    ),
    500: _evento(
        500, TipoEvento.ERROR_ROBOT, "El cobot no ha podido preparar la bebida"
    ),
    501: _evento(
        501, TipoEvento.ERROR_ROBOT, "Parada de emergencia por colisión física"
    ),
    503: _evento(503, TipoEvento.ERROR_ROBOT, "Pérdida de comunicación con el cobot"),
    CONNECTION_LOST_CODE: _evento(
        CONNECTION_LOST_CODE, TipoEvento.ERROR_SISTEMA, "Sin conexión con el cobot"
    ),
}
