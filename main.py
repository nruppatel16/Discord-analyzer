"""
main.py — Orchestrator. Runs the full Discord Analyzer pipeline end-to-end.

Pipeline:
  1. Load config (.env + servers.yaml)
  2. Init dedup DB
  3. Fetch messages (fetcher.py) → dedup filter → mark processed
  4. Group messages into conversations (grouper.py)
  5. Analyze conversations (analyzer.py)
  6. Generate HTML report (reporter.py)
  7. Save report to reports/latest.html
  8. Email report (emailer.py)
  9. Log summary
"""

import logging
import os
import sys
from datetime import datetime, timezone, timedelta

import yaml
from dotenv import load_dotenv

import dedup
import fetcher
import grouper
import analyzer
import reporter
import emailer

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def load_config():
    """Load .env and servers.yaml. Abort with a clear message if anything is missing."""
    load_dotenv()

    required = ["DISCORD_TOKEN", "EMAIL_FROM", "EMAIL_PASSWORD", "EMAIL_TO"]
    missing = [k for k in required if not os.getenv(k, "").strip()]
    if missing:
        logger.error("Missing required .env variables: %s", ", ".join(missing))
        logger.error("Fill in .env and re-run.")
        sys.exit(1)

    yaml_path = "servers.yaml"
    if not os.path.exists(yaml_path):
        logger.error("servers.yaml not found. Run setup.sh first.")
        sys.exit(1)

    with open(yaml_path, "r") as f:
        server_config = yaml.safe_load(f)

    # Validate at least one channel is configured
    configured_channels = [
        ch
        for srv in server_config.get("servers", [])
        for ch in srv.get("channels", [])
        if ch.get("channel_id", "").strip()
    ]
    if not configured_channels:
        logger.warning("No channel IDs configured in servers.yaml. Nothing to fetch.")

    return server_config


def run():
    logger.info("=" * 60)
    logger.info("Discord Analyzer — run started")
    logger.info("=" * 60)

    # 1. Load config
    server_config = load_config()

    token = os.getenv("DISCORD_TOKEN").strip()
    email_from = os.getenv("EMAIL_FROM").strip()
    email_password = os.getenv("EMAIL_PASSWORD").strip()
    email_to = os.getenv("EMAIL_TO").strip()
    hours_lookback = int(os.getenv("HOURS_LOOKBACK", "5"))
    delay_seconds = float(os.getenv("FETCH_DELAY_SECONDS", "2"))

    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(hours=hours_lookback)

    # 2. Init dedup DB (creates table if not exists, purges old records)
    dedup.init_db()
    dedup.purge_old_records()

    # 3. Fetch all messages
    logger.info("Fetching messages from last %d hour(s) ...", hours_lookback)
    all_messages = fetcher.fetch_all_servers(
        config=server_config,
        token=token,
        hours_lookback=hours_lookback,
        delay_seconds=delay_seconds,
        already_processed_fn=dedup.is_processed,
    )

    if not all_messages:
        logger.info("No new messages found. Generating empty report.")

    # Mark all fetched messages as processed (bulk insert)
    new_ids = [m["message_id"] for m in all_messages]
    dedup.mark_processed_bulk(new_ids)
    logger.info("Marked %d new message IDs as processed.", len(new_ids))

    # 4. Group messages into conversation threads
    groups = grouper.group_messages(all_messages, server_config)
    logger.info("Created %d conversation group(s).", len(groups))

    # 5. Analyze
    logger.info("Running analysis ...")
    analysis = analyzer.analyze(groups)

    ticker_count = len(analysis.get("tickers", []))
    lesson_count = len(analysis.get("lessons", []))
    logger.info(
        "Analysis complete: %d ticker(s), %d lesson(s), %d discussion group(s).",
        ticker_count,
        lesson_count,
        len(analysis.get("general_discussion", [])),
    )

    # 6 + 7. Build and save report
    html = reporter.build_report(analysis, period_start, period_end)
    report_path = reporter.save_report(html)
    logger.info("Report saved: %s", report_path)

    # 8. Email report
    logger.info("Sending email report to %s ...", email_to)
    success = emailer.send_report(html, email_from, email_password, email_to)
    if not success:
        logger.warning("Email failed — report still available at %s", report_path)

    # 9. Summary
    logger.info("-" * 60)
    logger.info("Run complete.")
    logger.info("  Messages fetched : %d", len(all_messages))
    logger.info("  Tickers found    : %d", ticker_count)
    logger.info("  Report           : %s", report_path)
    logger.info("  Email sent       : %s", "yes" if success else "no (see log above)")
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
