from pydantic import BaseModel


class AnalyticsMessage(BaseModel):
    evento_id: str
    cobot_id: str
