"""Steam Wishlist API client and app name resolver."""

import logging
import time

import requests

logger = logging.getLogger(__name__)

WISHLIST_URL = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"


def fetch_wishlist(steam_id: str) -> list[int]:
    """Return ordered list of appids from the user's Steam wishlist."""
    resp = requests.get(WISHLIST_URL, params={"steamid": steam_id}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    items = data.get("response", {}).get("items", [])
    if not items:
        logger.warning("Wishlist is empty or profile is private.")
        return []

    # items is a flat list: [{"appid": int, "priority": int, "date_added": int}, ...]
    appids: list[tuple[int, int]] = [
        (entry["appid"], entry.get("priority", 9999)) for entry in items
    ]

    # Sort by wishlist priority (lower = higher priority)
    appids.sort(key=lambda x: x[1])
    return [a for a, _ in appids]


def resolve_names(appids: list[int]) -> dict[int, str]:
    """
    Return {appid: name} for the given list.

    Checks the local SQLite cache (games table) first so that games already
    seen in a previous run never hit the network. Only unknown appids trigger
    a store.steampowered.com/api/appdetails call (one at a time, rate-limited).
    """
    from . import database as db

    # Seed from DB so repeat runs are fast
    cached: dict[int, str] = {}
    with db.get_connection() as conn:
        rows = conn.execute("SELECT appid, name FROM games").fetchall()
        for row in rows:
            cached[row["appid"]] = row["name"]

    result: dict[int, str] = {}
    unknown: list[int] = []

    for appid in appids:
        if appid in cached:
            result[appid] = cached[appid]
        else:
            unknown.append(appid)

    if unknown:
        logger.info("Resolving %d unknown game name(s) via Steam store API…", len(unknown))

    for appid in unknown:
        try:
            resp = requests.get(
                APP_DETAILS_URL,
                params={"appids": appid, "filters": "basic"},
                timeout=10,
            )
            resp.raise_for_status()
            detail = resp.json().get(str(appid), {})
            if detail.get("success"):
                name = detail["data"]["name"]
            else:
                name = f"App {appid}"
        except Exception as exc:
            logger.debug("Could not resolve name for appid %d: %s", appid, exc)
            name = f"App {appid}"

        result[appid] = name
        time.sleep(0.5)  # respect Steam rate limits

    return result
