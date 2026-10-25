import asyncio
from typing import TypeVar, Type, Awaitable, Callable

from app.models.cobot_menu_item import CobotMenuItem
from app.schemas.get_catalog_dto import CobotCatalogResponse

T = TypeVar("T")


class CatalogWatcher:
    def __init__(
        self,
        update_service,  # HttpRequestService -> .../check-update/{id_cobot}
        catalog_service,  # HttpRequestService -> endpoint del catálogo completo
        catalog_type: Type[
            CobotCatalogResponse
        ] = CobotCatalogResponse,  # p. ej. list[BebidaSchema]
        interval: float = 5.0,
        on_change: Callable[[], Awaitable[None]] | None = None,
    ):
        self._update_service = update_service
        self._catalog_service = catalog_service
        self._catalog_type = catalog_type
        self._interval = interval
        self._task: asyncio.Task | None = None

        self.ultima_actualizacion: str | None = None
        self.catalogo: CobotCatalogResponse | None = None
        self._on_change = on_change

    @property
    def items_activos(self) -> list[CobotMenuItem]:
        if self.catalogo is None:
            return []
        return [i for i in self.catalogo.items if i.estado]

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="catalog-watcher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        fallos = 0
        while True:
            try:
                await self._tick()
                fallos = 0
                espera = self._interval
            except asyncio.CancelledError:
                raise
            except Exception as e:
                fallos += 1
                print(f"Error al consultar el catálogo: {type(e).__name__}: {e!r}")
                espera = min(self._interval * 2**fallos, 60)
            await asyncio.sleep(espera)

    async def _tick(self) -> None:
        fecha = await self._update_service.get(str)

        if fecha != self.ultima_actualizacion:  # != y no >
            catalogo = await self._catalog_service.get(self._catalog_type)
            self.catalogo = catalogo
            self.ultima_actualizacion = fecha  # solo si la descarga tuvo éxito
            print(f"Catálogo actualizado {fecha}")

            if self._on_change:
                try:
                    await self._on_change()
                except Exception as e:
                    print(f"Error en on_change: {type(e).__name__}: {e!r}")
