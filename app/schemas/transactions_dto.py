from pydantic import BaseModel, Field

from app.schemas.analytics_message_dto import AnalyticsMessage


class TransactionsDTO(AnalyticsMessage):
    item: str = Field(min_length=3, max_length=50)
    ingreso: float = Field(ge=0)
