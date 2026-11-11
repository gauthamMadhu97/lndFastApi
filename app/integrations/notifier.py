"""Notifies the external system when an asset is assigned or returned (section 5).

The real downstream doesn't exist for this assessment, so StubNotifier waits a bit
and keeps a record of what it was sent.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal, Protocol

logger = logging.getLogger("assetdesk.notifier")


@dataclass(frozen=True)
class AssetEvent:
    event: Literal["asset.assigned", "asset.returned"]
    asset_id: int
    asset_tag: str
    employee_id: int | None
    on: date
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class NotificationError(Exception):
    pass


class Notifier(Protocol):
    async def send(self, event: AssetEvent) -> None: ...


class StubNotifier:
    def __init__(self, delay: float = 0.5, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.calls: list[AssetEvent] = []

    async def send(self, event: AssetEvent) -> None:
        await asyncio.sleep(self.delay)
        if self.fail:
            raise NotificationError("downstream system unavailable")
        self.calls.append(event)
        logger.info(
            "notification delivered", extra={"fields": {"event": event.event, "asset_id": event.asset_id}}
        )


async def deliver(notifier: Notifier, event: AssetEvent) -> None:
    """Runs as a background task once the response has gone. A failure here is logged
    and nothing more: the assignment/return is already committed (5.3)."""
    try:
        await notifier.send(event)
    except Exception:
        logger.exception(
            "notification failed",
            extra={"fields": {"event": event.event, "asset_id": event.asset_id}},
        )
