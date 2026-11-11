"""Warranty lookup against an external source (section 6). Stubbed for the assessment."""

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class WarrantyInfo:
    warranty_expiry: date
    in_warranty: bool
    days_remaining: int


class WarrantyLookupError(Exception):
    pass


class WarrantyClient(Protocol):
    async def check(self, asset_tag: str, warranty_expiry: date) -> WarrantyInfo: ...


class StubWarrantyClient:
    """Takes `delay` seconds per asset. Tags listed in `failing_tags` raise, to test 6.3."""

    def __init__(self, delay: float = 0.5, failing_tags: set[str] | None = None) -> None:
        self.delay = delay
        self.failing_tags = failing_tags or set()

    async def check(self, asset_tag: str, warranty_expiry: date) -> WarrantyInfo:
        await asyncio.sleep(self.delay)
        if asset_tag in self.failing_tags:
            raise WarrantyLookupError("warranty provider returned an error")
        remaining = (warranty_expiry - date.today()).days
        return WarrantyInfo(
            warranty_expiry=warranty_expiry,
            in_warranty=remaining >= 0,
            days_remaining=max(remaining, 0),
        )
