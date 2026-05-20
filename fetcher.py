"""
fetcher.py — Pulls messages from Discord channels via the REST API.
Uses a user token (Authorization header without 'Bot' prefix).
"""

import os
import time
import logging
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


def _snowflake_from_datetime(dt: datetime) -> int:
    """Convert a UTC datetime to the smallest Discord snowflake at that moment."""
    discord_epoch = 1420070400000  # 2015-01-01 in ms
    ms = int(dt.timestamp() * 1000) - discord_epoch
    return (ms << 22)


def fetch_channel_messages(
    channel_id: str,
    channel_name: str,
    server_name: str,
    token: str,
    hours_lookback: int,
    delay_seconds: float,
    already_processed_fn,
) -> list:
    """
    Fetch all messages from a single channel posted within the last `hours_lookback` hours.
    Paginates through Discord's 100-message-per-call limit.
    Skips messages already tracked by the dedup store.

    Returns a list of message dicts:
      {message_id, author, content, timestamp, server_name, channel_name, referenced_message}
    """
    headers = {"Authorization": token}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_lookback)
    after_snowflake = _snowflake_from_datetime(cutoff)

    messages = []
    last_id = after_snowflake  # fetch everything after this snowflake

    logger.info("[%s / %s] Fetching messages from last %dh ...", server_name, channel_name, hours_lookback)

    while True:
        params = {"limit": 100, "after": str(last_id)}
        url = f"{DISCORD_API}/channels/{channel_id}/messages"

        response = _get_with_retry(url, headers=headers, params=params)
        if response is None:
            logger.error("[%s / %s] Failed to fetch after retries, skipping.", server_name, channel_name)
            break

        batch = response.json()

        if not batch:
            break  # no more messages

        # Discord returns newest-first when using `after`; sort oldest-first
        batch.sort(key=lambda m: int(m["id"]))

        new_in_batch = 0
        for raw in batch:
            msg_id = raw["id"]

            # Skip if already processed in a previous run
            if already_processed_fn(msg_id):
                continue

            # Parse referenced (replied-to) message content if present
            ref_content = None
            if raw.get("referenced_message"):
                ref_content = raw["referenced_message"].get("content", "")

            messages.append({
                "message_id": msg_id,
                "author": raw["author"].get("username", "unknown"),
                "content": raw.get("content", ""),
                "timestamp": raw["timestamp"],
                "server_name": server_name,
                "channel_name": channel_name,
                "referenced_message": ref_content,
            })
            new_in_batch += 1

        # Advance cursor past the last message in this batch
        last_id = batch[-1]["id"]

        logger.info("[%s / %s] Batch: %d total, %d new", server_name, channel_name, len(batch), new_in_batch)

        # Stop paginating if we got fewer than 100 — we've reached the end
        if len(batch) < 100:
            break

        time.sleep(delay_seconds)

    logger.info("[%s / %s] Fetched %d new messages total", server_name, channel_name, len(messages))
    return messages


def _get_with_retry(url: str, headers: dict, params: dict, max_retries: int = 5) -> requests.Response | None:
    """GET with automatic 429 rate-limit handling and exponential back-off."""
    wait = 1
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as exc:
            logger.warning("Network error on attempt %d: %s", attempt, exc)
            time.sleep(wait)
            wait *= 2
            continue

        if resp.status_code == 200:
            return resp

        if resp.status_code == 429:
            retry_after = float(resp.json().get("retry_after", wait))
            logger.warning("Rate-limited (429). Waiting %.1fs before retry.", retry_after)
            time.sleep(retry_after)
            continue

        if resp.status_code == 403:
            logger.error("403 Forbidden on %s — check token or channel permissions.", url)
            return None

        if resp.status_code == 404:
            logger.error("404 Not Found: %s — check channel ID.", url)
            return None

        logger.warning("Unexpected HTTP %d on attempt %d.", resp.status_code, attempt)
        time.sleep(wait)
        wait *= 2

    return None


def fetch_all_servers(config: dict, token: str, hours_lookback: int, delay_seconds: float, already_processed_fn) -> list:
    """
    Iterate over every server → channel in servers.yaml config
    and return a flat list of all new message dicts.
    """
    all_messages = []

    for server in config.get("servers", []):
        server_name = server["name"]
        for channel in server.get("channels", []):
            channel_name = channel["name"]
            channel_id = channel.get("channel_id", "").strip()

            if not channel_id:
                logger.warning("Skipping [%s / %s] — no channel_id configured.", server_name, channel_name)
                continue

            msgs = fetch_channel_messages(
                channel_id=channel_id,
                channel_name=channel_name,
                server_name=server_name,
                token=token,
                hours_lookback=hours_lookback,
                delay_seconds=delay_seconds,
                already_processed_fn=already_processed_fn,
            )
            all_messages.extend(msgs)
            time.sleep(delay_seconds)  # polite pause between channels

    return all_messages
