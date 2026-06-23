"""
test_newsletter.py — One-off: fetch a single channel's recent chat, analyze it,
and email the newsletter. Bypasses the dedup DB so it can be re-run freely.

Usage:
    python3 test_newsletter.py [CHANNEL_ID] [HOURS] [EMAIL_TO] [MODE]
    MODE = ticker_discussion | qa_educational

Defaults are filled in below. Server/channel names are auto-discovered from the
Discord API; falls back to placeholders if the lookup is not permitted.
"""

import logging
import sys
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
import os

import fetcher
import grouper
import analyzer
import reporter
import emailer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("test_newsletter")

# ── Defaults (overridable via CLI args) ─────────────────────────────────────
CHANNEL_ID = "1039195519068668035"
HOURS      = 4
EMAIL_TO   = "nrup1618@gmail.com"
MODE       = "ticker_discussion"   # or "qa_educational" to also extract lessons

DISCORD_API = "https://discord.com/api/v10"


def _discover_names(channel_id: str, token: str):
    """Return (server_name, channel_name) from Discord; fall back gracefully."""
    headers = {"Authorization": token}
    channel_name = f"channel-{channel_id[-4:]}"
    server_name = "Discord"
    try:
        r = requests.get(f"{DISCORD_API}/channels/{channel_id}", headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            channel_name = data.get("name") or channel_name
            guild_id = data.get("guild_id")
            if guild_id:
                g = requests.get(f"{DISCORD_API}/guilds/{guild_id}", headers=headers, timeout=15)
                if g.status_code == 200:
                    server_name = g.json().get("name") or server_name
        else:
            log.warning("Channel lookup returned HTTP %d — using placeholder names.", r.status_code)
    except requests.RequestException as exc:
        log.warning("Channel lookup failed (%s) — using placeholder names.", exc)
    return server_name, channel_name


def main():
    channel_id = sys.argv[1] if len(sys.argv) > 1 else CHANNEL_ID
    hours      = int(sys.argv[2]) if len(sys.argv) > 2 else HOURS
    email_to   = sys.argv[3] if len(sys.argv) > 3 else EMAIL_TO
    mode       = sys.argv[4] if len(sys.argv) > 4 else MODE

    load_dotenv()
    token          = os.getenv("DISCORD_TOKEN", "").strip()
    email_from     = os.getenv("EMAIL_FROM", "").strip()
    email_password = os.getenv("EMAIL_PASSWORD", "").strip()
    delay_seconds  = float(os.getenv("FETCH_DELAY_SECONDS", "2"))

    if not token:
        log.error("DISCORD_TOKEN missing in .env"); sys.exit(1)
    if not (email_from and email_password):
        log.error("EMAIL_FROM / EMAIL_PASSWORD missing in .env"); sys.exit(1)

    log.info("=" * 60)
    log.info("Test newsletter — channel %s, last %dh → %s", channel_id, hours, email_to)
    log.info("=" * 60)

    server_name, channel_name = _discover_names(channel_id, token)
    log.info("Resolved: %s / #%s  (mode=%s)", server_name, channel_name, mode)

    server_config = {
        "servers": [{
            "name": server_name,
            "mode": mode,
            "channels": [{"name": channel_name, "channel_id": channel_id}],
        }]
    }

    period_end   = datetime.now(timezone.utc)
    period_start = period_end - timedelta(hours=hours)

    # 1. Fetch (bypass dedup so the run is repeatable)
    messages = fetcher.fetch_channel_messages(
        channel_id=channel_id,
        channel_name=channel_name,
        server_name=server_name,
        token=token,
        hours_lookback=hours,
        delay_seconds=delay_seconds,
        already_processed_fn=lambda _mid: False,
    )
    log.info("Fetched %d message(s).", len(messages))

    # Optional cap (most recent N) for fast validation runs: MAX_MESSAGES=250
    cap = int(os.getenv("MAX_MESSAGES", "0"))
    if cap and len(messages) > cap:
        messages = messages[-cap:]
        log.info("Capped to most recent %d message(s) for this run.", cap)

    # 2. Group
    groups = grouper.group_messages(messages, server_config)
    log.info("Grouped into %d conversation group(s).", len(groups))

    # 3. Analyze (real LLM API; falls back to stub if unconfigured)
    analysis = analyzer.analyze(groups)
    log.info(
        "Analysis: %d ticker(s), %d lesson(s), %d discussion block(s).",
        len(analysis.get("tickers", [])),
        len(analysis.get("lessons", [])),
        len(analysis.get("general_discussion", [])),
    )

    # 4. Build + save report
    html = reporter.build_report(analysis, period_start, period_end)
    path = reporter.save_report(html, "reports/test_newsletter.html")
    log.info("Report saved: %s", path)

    # 5. Email it
    ok = emailer.send_report(html, email_from, email_password, email_to)
    log.info("-" * 60)
    log.info("Email to %s: %s", email_to, "SENT" if ok else "FAILED (see log above)")
    log.info("Report also saved at: %s", path)


if __name__ == "__main__":
    main()
