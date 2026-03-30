"""
Persistent scheduler — runs main.py every N hours using APScheduler.

Usage:
    python scheduler.py

Leave this process running (e.g. as a Windows service, a systemd unit, or a screen/tmux session).
Alternatively, use your OS scheduler (Windows Task Scheduler / cron) to invoke `python main.py`
every 6 hours and skip this file entirely.
"""

import json
import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduler")


def load_interval() -> int:
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f).get("schedule_interval_hours", 6)
    return 6


def main() -> None:
    from main import run  # import here so dotenv is loaded by main.py

    interval_hours = load_interval()
    logger.info("Scheduler starting — will run every %d hour(s).", interval_hours)

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run,
        trigger=IntervalTrigger(hours=interval_hours),
        id="price_check",
        name="Wishlist price check",
        replace_existing=True,
    )

    # Fire once immediately on start so we don't wait N hours for the first run
    logger.info("Running initial check now…")
    try:
        run()
    except Exception as exc:
        logger.error("Initial run failed: %s", exc)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
