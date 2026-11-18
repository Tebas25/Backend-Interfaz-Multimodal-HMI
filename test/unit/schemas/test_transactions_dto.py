import pytest
from pydantic import ValidationError

from app.schemas.transactions_dto import TransactionsDTO


def datos(**cambios):
    base = {
        "cobot_id": "CBT000T",
        "evento_id": "EVT-001",
        "item": "Cuba Libre",
        "ingreso": 6.4,
    }
    base.update(cambios)
    return base


def test_creacion_valida():
    dto = TransactionsDTO(**datos())
    assert dto.item == "Cuba Libre"
    assert dto.ingreso == 6.4


@pytest.mark.parametrize("campo", ["cobot_id", "evento_id", "item", "ingreso"])
def test_campo_obligatorio_faltante(campo):
    d = datos()
    del d[campo]
    with pytest.raises(ValidationError):
        TransactionsDTO(**d)


@pytest.mark.parametrize("item", ["ab", ""])
def test_item_demasiado_corto(item):
    with pytest.raises(ValidationError):
        TransactionsDTO(**datos(item=item))


def test_item_limites_validos():
    assert TransactionsDTO(**datos(item="abc")).item == "abc"
    assert TransactionsDTO(**datos(item="a" * 50)).item == "a" * 50


def test_item_demasiado_largo():
    with pytest.raises(ValidationError):
        TransactionsDTO(**datos(item="a" * 51))


def test_ingreso_negativo_rechazado():
    with pytest.raises(ValidationError):
        TransactionsDTO(**datos(ingreso=-0.01))


def test_ingreso_cero_permitido():
    assert TransactionsDTO(**datos(ingreso=0)).ingreso == 0


def test_model_dump_envia_ingreso_como_numero():
    dump = TransactionsDTO(**datos()).model_dump(mode="json")
    assert dump == datos()
    assert isinstance(dump["ingreso"], float)
