"""
AllKeyShop price fetcher via their internal CatalogV2 API.

The API endpoint is embedded in the page JS and versioned by build date
(e.g. v2-1-250304). We auto-detect the current version on first use by
scanning the homepage for the pattern; falls back to a hardcoded value.
"""

import difflib
import logging
import re
import time
from dataclasses import dataclass

import cloudscraper

logger = logging.getLogger(__name__)

AKS_HOME_URL = "https://www.allkeyshop.com/blog/en-us/"
AKS_API_VERSION_FALLBACK = "v2-1-250304"
AKS_FIELDS = (
    "id,name,link,operating_system.id,"
    "offers.price,offers.buy_url,offers.stock_status,offers.merchant.name"
)
REQUEST_DELAY = 3.0  # seconds between requests

_scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)
_api_version: str | None = None


@dataclass
class AKSPrice:
    appid: int
    name: str
    price_usd: float
    store: str
    store_url: str


def fetch_prices(games: dict[int, str]) -> dict[int, AKSPrice]:
    """Fetch best PC prices for each game from AllKeyShop's CatalogV2 API."""
    results: dict[int, AKSPrice] = {}
    request_count = 0

    for appid, name in games.items():
        time.sleep(REQUEST_DELAY)
        try:
            price = _fetch_game(appid, name)
            request_count += 1
            if price:
                results[appid] = price
            else:
                logger.debug("AllKeyShop: no match found for '%s'", name)
        except Exception as exc:
            request_count += 1
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                logger.warning(
                    "AllKeyShop rate-limited (429) after %d request(s) — '%s' (appid=%d).",
                    request_count, name, appid,
                )
            else:
                logger.warning("AllKeyShop error for '%s' (appid=%d): %s", name, appid, exc)

    logger.info(
        "AllKeyShop: fetched prices for %d/%d games (%d requests).",
        len(results), len(games), request_count,
    )
    return results


def _api_url() -> str:
    return f"https://www.allkeyshop.com/api/{_get_api_version()}/vaks.php"


def _get_api_version() -> str:
    """Auto-detect the current API version from the AKS homepage HTML."""
    global _api_version
    if _api_version:
        return _api_version
    try:
        resp = _scraper.get(AKS_HOME_URL, timeout=15)
        match = re.search(r"/api/(v[\d-]+)/vaks\.php", resp.text)
        if match:
            _api_version = match.group(1)
            logger.info("AllKeyShop: detected API version %s", _api_version)
            return _api_version
    except Exception as exc:
        logger.debug("Could not auto-detect AKS API version: %s", exc)
    logger.info("AllKeyShop: using fallback API version %s", AKS_API_VERSION_FALLBACK)
    _api_version = AKS_API_VERSION_FALLBACK
    return _api_version


def _fetch_game(appid: int, name: str) -> AKSPrice | None:
    params = {
        "action": "CatalogV2",
        "locale": "en",
        "currency": "USD",
        "price_mode": "price_card",
        "search_name": name,
        "sort_field": "popularity",
        "sort_order": "desc",
        "pagenum": 1,
        "per_page": 10,
        "fields": AKS_FIELDS,
        "rating_min": 0,
        "deal_score_min": 0,
        "deal_score_max": 1,
    }
    resp = _scraper.get(_api_url(), params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    products = data.get("products", [])
    if not products:
        return None

    # Prefer PC products; fall back to all if none found
    pc_products = [p for p in products if p.get("operating_system", {}).get("id") == "pc"]
    candidates = pc_products if pc_products else products

    product = _best_name_match(name, candidates)
    if not product:
        return None

    # Best in-stock offer (lowest price > 0)
    offers = [
        o for o in product.get("offers", [])
        if o.get("stock_status") == "in_stock" and (o.get("price") or 0) > 0
    ]
    if not offers:
        return None

    best = min(offers, key=lambda o: o["price"])
    return AKSPrice(
        appid=appid,
        name=product["name"],
        price_usd=float(best["price"]),
        store=best.get("merchant", {}).get("name", "AllKeyShop"),
        store_url=product.get("link", "https://www.allkeyshop.com/blog/en-us/"),
    )


def _best_name_match(query: str, products: list[dict]) -> dict | None:
    """Return the product whose name best matches the query, or the first result."""
    names = [p["name"] for p in products]
    normalised = [n.lower() for n in names]
    matches = difflib.get_close_matches(query.lower(), normalised, n=1, cutoff=0.5)
    if matches:
        idx = normalised.index(matches[0])
        return products[idx]
    # No close match — return the first (most popular) result as a best-effort
    return products[0]
