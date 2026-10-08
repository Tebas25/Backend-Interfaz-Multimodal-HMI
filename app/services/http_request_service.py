import requests
from pydantic import BaseModel, TypeAdapter
from typing import Type, TypeVar

T = TypeVar("T")


class HttpRequestService:
    def __init__(self, url, authkey=None):
        self.url = url
        self.session = requests.Session()
        if authkey:
            self.session.headers["authkey"] = authkey

    def _request(self, method: str, type: Type[T], **kwargs) -> T:
        response = self.session.request(method, self.url, timeout=10, **kwargs)
        response.raise_for_status()
        return TypeAdapter(type).validate_python(response.json())

    def get(self, type: Type[T], **kwargs) -> T:
        return self._request("GET", type, **kwargs)

    def post(self, type: Type[T], datos: BaseModel) -> T:
        return self._request("POST", type, json=datos.model_dump())
