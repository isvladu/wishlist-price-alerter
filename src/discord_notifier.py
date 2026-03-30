"""Discord webhook notification sender."""

import logging
from datetime import datetime, timezone

import requests

from .price_checker import Deal

logger = logging.getLogger(__name__)

STEAM_STORE_ICON = "https://store.steampowered.com/favicon.ico"
COLOR_NEW_LOW = 0xE74C3C    # red — exciting
COLOR_GOOD_DEAL = 0x2ECC71  # green — good
COLOR_DEFAULT = 0x3498DB    # blue


def send_deals(webhook_url: str, deals: list[Deal]) -> None:
    """Send one Discord message per deal as a rich embed."""
    for deal in deals:
        embed = _build_embed(deal)
        payload = {"embeds": [embed]}
        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Discord: notified deal — %s @ $%.2f (%s)", deal.name, deal.current_price, deal.source)
        except Exception as exc:
            logger.error("Discord webhook error for %s: %s", deal.name, exc)


DISCORD_DESCRIPTION_LIMIT = 4096  # Discord embed description character limit


def send_summary(webhook_url: str, deals: list[Deal], run_at: datetime | None = None) -> bool:
    """
    Send deal summary to Discord, splitting into multiple messages if the
    description would exceed Discord's 4096-character embed limit.
    Returns True only if all messages were delivered successfully.
    """
    if not deals:
        return True

    run_at = run_at or datetime.now(timezone.utc)
    batches = _split_into_batches(deals)
    total = len(batches)
    all_sent = True

    for idx, batch in enumerate(batches):
        title = f"🎮 {len(deals)} wishlist deal{'s' if len(deals) != 1 else ''} found"
        if total > 1:
            title += f" ({idx + 1}/{total})"

        lines = []
        for deal in batch:
            reasons = ", ".join(deal.reasons)
            lines.append(
                f"**{deal.name}** — ${deal.current_price:.2f} via {deal.source} ({reasons})\n"
                f"[View deal]({deal.store_url})"
            )

        embed = {
            "title": title,
            "description": "\n\n".join(lines),
            "color": COLOR_GOOD_DEAL,
            "footer": {"text": f"Checked at {run_at.strftime('%Y-%m-%d %H:%M UTC')}"},
            "thumbnail": {"url": STEAM_STORE_ICON},
        }
        try:
            resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
            if not resp.ok:
                logger.error(
                    "Discord webhook error %d: %s", resp.status_code, resp.text[:300]
                )
                resp.raise_for_status()
            logger.info("Discord: sent batch %d/%d (%d deals).", idx + 1, total, len(batch))
        except Exception as exc:
            logger.error("Discord webhook error: %s", exc)
            all_sent = False

    return all_sent


def _split_into_batches(deals: list[Deal]) -> list[list[Deal]]:
    """Group deals into batches that each fit within the Discord description limit."""
    batches: list[list[Deal]] = []
    current_batch: list[Deal] = []
    current_len = 0

    for deal in deals:
        reasons = ", ".join(deal.reasons)
        line = (
            f"**{deal.name}** — ${deal.current_price:.2f} via {deal.source} ({reasons})\n"
            f"[View deal]({deal.store_url})"
        )
        line_len = len(line) + 2  # +2 for the \n\n separator

        if current_batch and current_len + line_len > DISCORD_DESCRIPTION_LIMIT:
            batches.append(current_batch)
            current_batch = []
            current_len = 0

        current_batch.append(deal)
        current_len += line_len

    if current_batch:
        batches.append(current_batch)

    return batches


def _build_embed(deal: Deal) -> dict:
    color = COLOR_NEW_LOW if deal.is_new_low else COLOR_GOOD_DEAL

    fields = [
        {"name": "Current price", "value": f"**${deal.current_price:.2f}**", "inline": True},
        {"name": "Source", "value": deal.source, "inline": True},
    ]

    if deal.historical_min is not None:
        fields.append({"name": "All-time low", "value": f"${deal.historical_min:.2f}", "inline": True})

    if deal.historical_avg is not None:
        discount = deal.discount_vs_avg
        avg_text = f"${deal.historical_avg:.2f}"
        if discount:
            avg_text += f" ({round(discount * 100)}% below avg)"
        fields.append({"name": "90-day avg", "value": avg_text, "inline": True})

    fields.append(
        {"name": "Reasons", "value": ", ".join(deal.reasons), "inline": False}
    )

    return {
        "title": f"{deal.name}",
        "url": deal.store_url,
        "description": "A deal was found on your Steam wishlist!",
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"Steam AppID {deal.appid} • {deal.source}",
            "icon_url": STEAM_STORE_ICON,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
