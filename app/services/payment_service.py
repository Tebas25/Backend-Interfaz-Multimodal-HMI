import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Awaitable, Callable

from app.models.cobot_menu_item import CobotMenuItem


class PaymentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PaymentSession:
    drink: CobotMenuItem
    price: Decimal
    expires_at: datetime
    id: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    status: PaymentStatus = PaymentStatus.PENDING
    created_at: datetime = field(default_factory=_now)
    timer: asyncio.Task | None = field(default=None, repr=False)

    @property
    def effective_status(self) -> PaymentStatus:
        if self.status is PaymentStatus.PENDING and _now() >= self.expires_at:
            return PaymentStatus.EXPIRED
        return self.status


OnResult = Callable[[PaymentSession], Awaitable[None]]


class PaymentService:
    def __init__(self, base_url: str, on_result: OnResult, ttl_seconds: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._on_result = on_result
        self._ttl = ttl_seconds
        self._sessions: dict[str, PaymentSession] = {}
        self._current: PaymentSession | None = None

    def pay_url(self, session: PaymentSession) -> str:
        return f"{self._base_url}/pay/{session.id}"

    def get(self, payment_id: str) -> PaymentSession | None:
        return self._sessions.get(payment_id)

    def start(self, drink: CobotMenuItem) -> PaymentSession:
        if self._current is not None:
            self._close(self._current, PaymentStatus.CANCELLED)  # sin avisar al front
        session = PaymentSession(
            drink=drink,
            price=drink.precio_item,
            expires_at=_now() + timedelta(seconds=self._ttl),
        )
        session.timer = asyncio.create_task(self._expire_later(session))
        self._sessions[session.id] = session
        self._current = session
        self._prune()
        return session

    def cancel(self, payment_id: str | None = None) -> None:
        session = self._current
        if session is None or (payment_id is not None and payment_id != session.id):
            return
        self._close(session, PaymentStatus.CANCELLED)

    async def approve(self, payment_id: str) -> PaymentSession | None:
        return await self._resolve(payment_id, PaymentStatus.APPROVED)

    async def reject(self, payment_id: str) -> PaymentSession | None:
        return await self._resolve(payment_id, PaymentStatus.REJECTED)

    def close(self) -> None:
        for s in self._sessions.values():
            if s.timer:
                s.timer.cancel()

    async def _resolve(
        self, payment_id: str, status: PaymentStatus
    ) -> PaymentSession | None:
        session = self._sessions.get(payment_id)
        if session is None:
            return None
        if session.status is PaymentStatus.PENDING:
            final = PaymentStatus.EXPIRED if _now() >= session.expires_at else status
            await self._finish(session, final)
        return session

    def _close(self, session: PaymentSession, status: PaymentStatus) -> None:
        if session.status is not PaymentStatus.PENDING:
            return
        session.status = status
        if session.timer and session.timer is not asyncio.current_task():
            session.timer.cancel()

    async def _finish(self, session: PaymentSession, status: PaymentStatus) -> None:
        self._close(session, status)
        try:
            await self._on_result(session)
        except Exception as e:
            print(f"[Pago] Error en on_result: {type(e).__name__}: {e!r}")

    async def _expire_later(self, session: PaymentSession) -> None:
        await asyncio.sleep(self._ttl)
        if session.status is PaymentStatus.PENDING:
            await self._finish(session, PaymentStatus.EXPIRED)

    def _prune(self) -> None:
        limit = _now() - timedelta(minutes=10)
        old = [
            pid
            for pid, s in self._sessions.items()
            if s is not self._current
            and s.status is not PaymentStatus.PENDING
            and s.created_at < limit
        ]
        for pid in old:
            del self._sessions[pid]
