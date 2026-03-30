"""
Discount detection logic.

A deal is flagged when:
  - NEW LOW:  current price < all-time stored minimum (first observation always qualifies if
              fewer than MIN_SNAPSHOTS exist, to bootstrap history without spamming)
  - GOOD DEAL: current price <= 90-day average × discount_threshold (e.g. 0.80)

Notifications are suppressed if the same (appid, source) was already notified within
cooldown_hours to avoid repeated pings for a long-running sale.
"""

import logging
from dataclasses import dataclass, field

from . import database as db

logger = logging.getLogger(__name__)

MIN_SNAPSHOTS = 3  # require at least this many historical points before flagging "good deal"


@dataclass
class Deal:
    appid: int
    name: str
    source: str
    current_price: float
    historical_min: float | None
    historical_avg: float | None
    store_url: str
    reasons: list[str] = field(default_factory=list)

    @property
    def is_new_low(self) -> bool:
        return "new low" in self.reasons

    @property
    def discount_vs_avg(self) -> float | None:
        if self.historical_avg and self.historical_avg > 0:
            return 1.0 - (self.current_price / self.historical_avg)
        return None


def check_prices(
    prices: dict,  # {appid: Price object with .price_usd, .store_url, .name}
    source: str,
    discount_threshold: float,
    history_days: int,
    cooldown_hours: int,
) -> list[Deal]:
    """
    Compare freshly fetched prices against stored history.
    Saves new snapshots and returns a list of Deal objects worth notifying.
    """
    deals: list[Deal] = []

    for appid, price_obj in prices.items():
        price_usd = price_obj.price_usd
        store_url = price_obj.store_url
        name = price_obj.name

        # Save snapshot first (before checking stats, so history is up-to-date)
        db.save_snapshot(appid, source, price_usd, "USD", store_url)

        if db.was_recently_notified(appid, source, cooldown_hours):
            logger.debug("Skipping %s (%s) — recently notified.", name, source)
            continue

        alltime_min = db.get_alltime_min(appid, source)
        stats = db.get_price_stats(appid, source, history_days)

        reasons: list[str] = []

        # New all-time low
        # Note: alltime_min reflects the snapshot we JUST saved, so price_usd <= alltime_min
        # means it matched or beat the previous minimum.
        if alltime_min is not None and price_usd <= alltime_min:
            # Only flag if we have at least one prior data point (the one before today)
            prior_count = (stats["snapshot_count"] if stats else 0) - 1  # subtract current
            if prior_count >= 1:
                reasons.append("new low")

        # Good deal vs. historical average
        if stats and stats["snapshot_count"] >= MIN_SNAPSHOTS and stats["avg_price"]:
            if price_usd <= stats["avg_price"] * discount_threshold:
                reasons.append(f"{round((1 - price_usd / stats['avg_price']) * 100)}% below avg")

        if reasons:
            deals.append(
                Deal(
                    appid=appid,
                    name=name,
                    source=source,
                    current_price=price_usd,
                    historical_min=alltime_min,
                    historical_avg=stats["avg_price"] if stats else None,
                    store_url=store_url,
                    reasons=reasons,
                )
            )

    return deals
