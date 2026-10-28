from datetime import datetime, timezone

from app.schemas.ws_messages import Screen, StatePayload, StateSource


class ScreenState:

    current: Screen | None = None
    source: StateSource | None = None
    ref: str | None = None
    updated_at: datetime | None = None

    @classmethod
    def update(cls, payload: StatePayload) -> None:
        cls.current = payload.screen
        cls.source = payload.source
        cls.ref = payload.ref
        cls.updated_at = datetime.now(timezone.utc)
        print(f"[Estado] pantalla={payload.screen.value} origen={payload.source.value}")

    @classmethod
    def reset(cls) -> None:
        cls.current = cls.source = cls.ref = cls.updated_at = None
