"""GG.Deals price fetcher using their /api/prices/by-steam-app-id/ endpoint."""

import logging
import os
from dataclasses import dataclass

import cloudscraper

logger = logging.getLogger(__name__)

GGDEALS_API_URL = "https://api.gg.deals/v1/prices/by-steam-app-id/"
_scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)
BATCH_SIZE = 100  # max permitted by the GG.Deals API


@dataclass
class GGDealPrice:
    appid: int
    name: str
    price_usd: float
    channel: str   # "retail" or "keyshop"
    store_url: str


def fetch_prices(appids: list[int]) -> dict[str, "GGDealPrice"]:
    """
    Fetch retail and keyshop prices for each appid from GG.Deals.

    Returns a dict keyed by "<appid>_retail" and "<appid>_keyshop" so both
    channels are tracked independently in the price history.
    """
    results: dict[str, GGDealPrice] = {}
    api_key = os.environ.get("GGDEALS_API_KEY", "")

    for i in range(0, len(appids), BATCH_SIZE):
        batch = appids[i : i + BATCH_SIZE]
        ids_param = ",".join(str(a) for a in batch)
        url = f"{GGDEALS_API_URL}?ids={ids_param}&key={api_key}"

        try:
            resp = _scraper.get(url, headers={"Accept": "application/json"}, timeout=20)
            if not resp.ok:
                logger.error(
                    "GG.Deals %d for batch starting %s: %s",
                    resp.status_code, batch[0], resp.text[:300],
                )
                resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("GG.Deals API error for batch starting %s: %s", batch[0], exc)
            continue

        entries = data.get("data", {})
        for appid_str, info in entries.items():
            try:
                appid = int(appid_str)
            except ValueError:
                continue

            name = info.get("title", f"App {appid}")
            store_url = info.get("url") or f"https://gg.deals/steam/app/{appid}/"
            prices = info.get("prices", {})

            for channel, key in (("retail", "currentRetail"), ("keyshop", "currentKeyshops")):
                raw = prices.get(key)
                if raw is None:
                    continue
                try:
                    val = float(raw)
                except (ValueError, TypeError):
                    continue
                if val <= 0:
                    continue
                results[f"{appid}_{channel}"] = GGDealPrice(
                    appid=appid,
                    name=name,
                    price_usd=val,
                    channel=channel,
                    store_url=store_url,
                )

    logger.info(
        "GG.Deals: got %d price entries across %d games.",
        len(results), len(appids),
    )
    return results
