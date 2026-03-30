# wishlist-price-alerter

Monitors your Steam wishlist for deals and sends Discord notifications when a game hits a new price low or drops significantly below its historical average.

Runs every 6 hours and checks prices against two sources:
- **GG.Deals API** — official retail stores and keyshop aggregator prices
- **AllKeyShop API** — key reseller marketplace prices

---

## How it works

1. Fetches your Steam wishlist via the Steam API
2. Queries GG.Deals for retail and keyshop prices (batched, per appid)
3. Queries AllKeyShop for marketplace prices (per game name)
4. Compares each price against its 90-day history stored in a local SQLite database
5. Flags a game as a deal if:
   - **New low** — current price is at or below the all-time stored minimum
   - **Good deal** — current price is ≤ 80% of the 90-day average (requires at least 3 snapshots)
6. Sends a Discord webhook notification for all deals found, split across multiple messages if needed
7. Logs the notification to the database; the same game won't trigger another alert for 48 hours

Price history accumulates over time — the longer the service runs, the more accurate the deal detection becomes.

---

## Requirements

- Python 3.11+
- A [GG.Deals API key](https://gg.deals/api/)
- A Discord webhook URL
- Your Steam ID64

---

## Setup

**1. Clone the repo and install dependencies**

```bash
git clone https://github.com/YOUR_USERNAME/wishlist-price-alerter.git
cd wishlist-price-alerter
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

**2. Configure secrets**

```bash
cp .env.example .env
```

Edit `.env`:

```env
STEAM_ID_64=76561198XXXXXXXXX
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
GGDEALS_API_KEY=your_ggdeals_api_key
```

To find your Steam ID64, visit [steamid.io](https://steamid.io) and look up your profile.

**3. Configure settings**

```bash
cp config.example.json config.json
```

Edit `config.json` to adjust thresholds:

```json
{
  "discount_threshold": 0.80,
  "price_history_days": 90,
  "notification_cooldown_hours": 48,
  "schedule_interval_hours": 12,
  "sources": ["ggdeals", "allkeyshop"]
}
```

| Key | Description | Default |
|-----|-------------|---------|
| `discount_threshold` | Alert when price ≤ this fraction of the 90-day average | `0.80` (20% below avg) |
| `price_history_days` | Rolling window used to compute average and minimum | `90` |
| `notification_cooldown_hours` | Minimum hours between repeat alerts for the same game | `48` |
| `schedule_interval_hours` | How often the scheduler runs a check | `12` |
| `sources` | Which price sources to query | `["ggdeals", "allkeyshop"]` |

---

## Running

**Run once manually:**

```bash
python main.py
```

**Run on a recurring schedule (every 12 hours):**

```bash
python scheduler.py
```

Leave `scheduler.py` running as a background process. Alternatively, use Windows Task Scheduler or a cron job to invoke `python main.py` every 6 hours and skip `scheduler.py` entirely.

---

## Project structure

```
wishlist-price-alerter/
├── main.py                  # Orchestrator — runs one full check cycle
├── scheduler.py             # APScheduler wrapper (every 12h)
├── config.example.json      # Settings template
├── .env.example             # Secrets template
├── requirements.txt
└── src/
    ├── steam.py             # Steam wishlist + app name resolver
    ├── ggdeals.py           # GG.Deals API client
    ├── allkeyshop.py        # AllKeyShop API client
    ├── database.py          # SQLite: price snapshots + notification log
    ├── price_checker.py     # Discount detection logic
    └── discord_notifier.py  # Discord webhook sender
```

---

## Database

SQLite database stored at `data/prices.db` (excluded from git).

| Table | Purpose |
|-------|---------|
| `games` | appid → name mapping, last checked timestamp |
| `price_snapshots` | Full price history per game per source |
| `notifications` | Log of successfully delivered Discord alerts (used for cooldown deduplication) |
