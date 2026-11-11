import asyncio
import logging
from collections.abc import Sequence
from datetime import date

from app.integrations.warranty_client import WarrantyClient, WarrantyInfo
from app.schemas.warranty import WarrantyCheckResponse, WarrantyResult

logger = logging.getLogger("assetdesk.warranty")


async def check_many(
    client: WarrantyClient,
    tags: Sequence[str],
    known: dict[str, date],
    per_lookup_limit: float,
) -> WarrantyCheckResponse:
    """Run all lookups at once. One failing lookup doesn't stop the others (6.2, 6.3).

    `known` maps asset tag -> warranty expiry for the tags that exist in our database.
    `per_lookup_limit` is in seconds and applies to each lookup separately.
    """
    to_check = [tag for tag in tags if tag in known]
    outcomes = await asyncio.gather(
        *(asyncio.wait_for(client.check(tag, known[tag]), per_lookup_limit) for tag in to_check),
        return_exceptions=True,
    )
    by_tag: dict[str, WarrantyInfo | BaseException] = dict(zip(to_check, outcomes, strict=True))

    results = []
    for tag in tags:
        if tag not in known:
            results.append(WarrantyResult(asset_tag=tag, ok=False, error="asset not found"))
            continue
        outcome = by_tag[tag]
        if isinstance(outcome, BaseException):
            reason = (
                "timed out" if isinstance(outcome, TimeoutError) else str(outcome) or type(outcome).__name__
            )
            logger.warning("warranty check failed", extra={"fields": {"asset_tag": tag, "reason": reason}})
            results.append(WarrantyResult(asset_tag=tag, ok=False, error=f"warranty lookup failed: {reason}"))
        else:
            results.append(
                WarrantyResult(
                    asset_tag=tag,
                    ok=True,
                    in_warranty=outcome.in_warranty,
                    warranty_expiry=outcome.warranty_expiry,
                    days_remaining=outcome.days_remaining,
                )
            )

    succeeded = sum(r.ok for r in results)
    return WarrantyCheckResponse(results=results, succeeded=succeeded, failed=len(results) - succeeded)
