import httpx
from pydantic import BaseModel, TypeAdapter
from typing import Type, TypeVar

T = TypeVar("T")


class HttpRequestService:
    def __init__(self, url: str, authkey: str | None = None):
        self.url = url
        headers = {"authkey": authkey} if authkey else {}
        self.client = httpx.AsyncClient(headers=headers, timeout=10.0)

    async def _request(self, method: str, type: Type[T], **kwargs) -> T:
        response = await self.client.request(method, self.url, **kwargs)
        response.raise_for_status()
        return TypeAdapter(type).validate_python(response.json())

    async def get(self, type: Type[T], **kwargs) -> T:
        return await self._request("GET", type, **kwargs)

    async def post(self, type: Type[T], datos: BaseModel) -> T:
        return await self._request("POST", type, json=datos.model_dump())

    async def close(self) -> None:
        await self.client.aclose()
