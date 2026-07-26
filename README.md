# ginNews — Cross-Platform Surveillance & Notification Relay

A personal monitoring system that watches **Telegram groups**, **Discord channels**, **X (Twitter) feeds**, and **Reddit subreddits** for keyword-matched alerts and relays them instantly to your Telegram DMs.

No admin rights. No expensive APIs. Just lean engineering.

## Architecture

```
[Telegram Groups]   [Discord Channels]   [X Search Feeds]   [Reddit Subreddits]
       │                    │                    │                    │
       ▼                    ▼                    ▼                    ▼
  (Telethon)         (Playwright)         (Playwright)       (AsyncPRAW/RSS)
       └────────────────────┼────────────────────┼────────────────────┘
                            ▼
              ┌──────────────────────────┐
              │   Core Processing Engine │
              │  • Keyword/Coin Filter   │
              │  • Deduplication (Redis) │
              │  • SQLite Persistence    │
              └────────────┬─────────────┘
                           ▼
              ┌──────────────────────────┐
              │   Telegram Bot (Your DM) │
              │  • Instant alerts        │
              │  • Inline action buttons │
              │  • Batch digest mode     │
              └──────────────────────────┘
```

## Quick Start

### 1. Clone & Install

```bash
cd ginNews
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium  # Required for Discord & X monitors
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your credentials:
#   - Telegram API ID/Hash (from my.telegram.org)
#   - Bot Token (from @BotFather)
#   - Your personal chat ID
#   - Subreddits, Discord URLs, X search queries
```

### 3. First Run (Manual Login)

```bash
python main.py
```

- **Telegram**: The first run will prompt for your phone number and verification code
- **Discord & X**: A browser window will open — log in manually. Sessions are saved automatically
- **Reddit (API)**: No login needed if using API credentials. RSS mode requires no credentials at all

### 4. Production Run

Once all sessions are established, you can run headless:

```bash
# Set headless=True in discord_monitor.py and twitter_monitor.py, then:
python main.py
```

## Configuration

All settings are in `.env`. See `.env.example` for the full list. Key settings:

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_API_ID` | Telethon API ID | ✅ |
| `TELEGRAM_API_HASH` | Telethon API Hash | ✅ |
| `TELEGRAM_BOT_TOKEN` | Alert bot token | ✅ |
| `ADMIN_CHAT_ID` | Your personal chat ID | ✅ |
| `WATCH_COINS` | Coins to track (comma-separated) | ✅ |
| `COMPLAINT_WORDS` | Alert keywords (comma-separated) | ✅ |
| `REDDIT_SUBREDDITS` | Subreddits to monitor | Optional |
| `REDDIT_CLIENT_ID` | Reddit API client ID | Optional |
| `DISCORD_CHANNEL_URLS` | Discord channel URLs | Optional |
| `TWITTER_SEARCH_QUERIES` | X search queries | Optional |
| `REDIS_URL` | Redis URL for deduplication | Optional |

## Testing

```bash
pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

## License

MIT
