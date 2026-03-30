"""
Wishlist Price Alerter — main entry point.

Runs a single check cycle:
  1. Fetch Steam wishlist
  2. Resolve game names
  3. Fetch prices from GG.Deals and/or AllKeyShop
  4. Compare against price history
  5. Send Discord notifications for deals found
  6. Persist price snapshots to SQLite

Usage:
    python main.py            # run once
    python scheduler.py       # run on schedule (every 6h by default)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src import database as db
from src import steam, ggdeals, allkeyshop
from src.price_checker import check_prices
from src.discord_notifier import send_summary

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        logger.error("config.json not found. Copy config.example.json and fill it in.")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def run() -> None:
    config = load_config()

    steam_id = os.environ.get("STEAM_ID_64", "").strip()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

    if not steam_id:
        logger.error("STEAM_ID_64 is not set in .env")
        sys.exit(1)
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL is not set in .env")
        sys.exit(1)

    discount_threshold = config.get("discount_threshold", 0.80)
    history_days = config.get("price_history_days", 90)
    cooldown_hours = config.get("notification_cooldown_hours", 48)
    sources = config.get("sources", ["ggdeals", "allkeyshop"])

    db.init_db()

    run_at = datetime.now(timezone.utc)
    logger.info("=== Wishlist check started at %s ===", run_at.strftime("%Y-%m-%d %H:%M UTC"))

    # 1. Fetch wishlist
    logger.info("Fetching wishlist for SteamID %s…", steam_id)
    appids = steam.fetch_wishlist(steam_id)
    if not appids:
        logger.info("No wishlist items found. Exiting.")
        return
    logger.info("Found %d wishlist items.", len(appids))

    # 2. Resolve game names
    logger.info("Resolving game names…")
    names = steam.resolve_names(appids)
    for appid, name in names.items():
        db.upsert_game(appid, name)

    all_deals = []

    # GG.Deals — returns retail + keyshop prices as separate entries
    if "ggdeals" in sources:
        logger.info("Fetching GG.Deals prices…")
        gg_prices = ggdeals.fetch_prices(appids)
        if gg_prices:
            # check_prices expects {appid: price_obj}; GG.Deals returns {"appid_channel": obj}
            # Pass the full dict — price_checker uses .appid from each object as the DB key,
            # and source = "ggdeals_retail" / "ggdeals_keyshop" to keep histories separate.
            for channel in ("retail", "keyshop"):
                channel_prices = {
                    k: v for k, v in gg_prices.items() if v.channel == channel
                }
                if not channel_prices:
                    continue
                source_name = f"ggdeals_{channel}"
                deals = check_prices(
                    prices=channel_prices,
                    source=source_name,
                    discount_threshold=discount_threshold,
                    history_days=history_days,
                    cooldown_hours=cooldown_hours,
                )
                logger.info("GG.Deals %s: %d deal(s) found.", channel, len(deals))
                all_deals.extend(deals)

    # AllKeyShop
    if "allkeyshop" in sources:
        logger.info("Fetching AllKeyShop prices…")
        aks_prices = allkeyshop.fetch_prices(names)
        if aks_prices:
            aks_deals = check_prices(
                prices=aks_prices,
                source="allkeyshop",
                discount_threshold=discount_threshold,
                history_days=history_days,
                cooldown_hours=cooldown_hours,
            )
            logger.info("AllKeyShop: %d deal(s) found.", len(aks_deals))
            all_deals.extend(aks_deals)

    # 4. Notify — only log to DB after Discord confirms delivery
    if all_deals:
        logger.info("Sending Discord notification for %d deal(s)…", len(all_deals))
        sent = send_summary(webhook_url, all_deals, run_at=run_at)
        if sent:
            for deal in all_deals:
                db.log_notification(deal.appid, deal.source, deal.current_price)
    else:
        logger.info("No deals to notify about this run.")

    logger.info("=== Run complete. ===")


if __name__ == "__main__":
    run()
