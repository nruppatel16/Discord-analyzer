"""
grouper.py — Groups raw messages into logical conversation threads.

Two messages belong to the same thread if:
  (a) one is a direct reply to the other (reply chain), OR
  (b) they appear in the same channel within a 10-minute sliding window.

Within each group, messages are kept in chronological order.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

THREAD_WINDOW_MINUTES = 10


def _parse_ts(ts_str: str) -> datetime:
    """Parse an ISO-8601 Discord timestamp into an aware UTC datetime."""
    # Discord format: 2024-01-15T14:32:00.123000+00:00
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)


def group_messages(messages: list, server_config: dict) -> list:
    """
    Group a flat list of message dicts into conversation thread groups.

    Returns a list of group dicts:
    {
        "server":   str,
        "channel":  str,
        "mode":     str,   # from servers.yaml (e.g. "qa_educational")
        "messages": [...]  # list of message dicts, chronological
    }
    """
    if not messages:
        return []

    # Build a lookup: (server_name, channel_name) -> mode
    mode_map = {}
    for srv in server_config.get("servers", []):
        for ch in srv.get("channels", []):
            mode_map[(srv["name"], ch["name"])] = srv.get("mode", "ticker_discussion")

    # Bucket messages by (server_name, channel_name)
    buckets: dict[tuple, list] = {}
    for msg in messages:
        key = (msg["server_name"], msg["channel_name"])
        buckets.setdefault(key, []).append(msg)

    # Sort each bucket chronologically
    for key in buckets:
        buckets[key].sort(key=lambda m: _parse_ts(m["timestamp"]))

    groups = []

    for (server_name, channel_name), msgs in buckets.items():
        mode = mode_map.get((server_name, channel_name), "ticker_discussion")

        # Build a quick id → message index for reply-chain detection
        id_to_msg = {m["message_id"]: m for m in msgs}

        # Track which messages have already been assigned to a group
        assigned: set = set()

        # First pass: build reply chains
        chains: dict[str, list] = {}  # root_id -> [messages in chain]

        for msg in msgs:
            mid = msg["message_id"]
            if mid in assigned:
                continue

            # Check if this message replies to another in our set
            parent_id = _find_parent_id(msg, id_to_msg)

            if parent_id and parent_id not in assigned:
                # Attach to existing chain or start a new one
                root = _find_chain_root(parent_id, chains)
                if root:
                    chains[root].append(msg)
                else:
                    chains[parent_id] = [id_to_msg[parent_id], msg]
                    assigned.add(parent_id)
                assigned.add(mid)
            elif parent_id and parent_id in assigned:
                # Parent already in a chain; find and append
                root = _find_chain_root(parent_id, chains)
                if root:
                    chains[root].append(msg)
                    assigned.add(mid)

        # Second pass: time-window grouping for non-chain messages
        remaining = [m for m in msgs if m["message_id"] not in assigned]
        time_groups = _group_by_time_window(remaining)

        # Emit reply-chain groups
        for root_id, chain_msgs in chains.items():
            chain_msgs.sort(key=lambda m: _parse_ts(m["timestamp"]))
            groups.append({
                "server": server_name,
                "channel": channel_name,
                "mode": mode,
                "messages": chain_msgs,
            })

        # Emit time-window groups
        for tg in time_groups:
            if tg:
                groups.append({
                    "server": server_name,
                    "channel": channel_name,
                    "mode": mode,
                    "messages": tg,
                })

    logger.info("Grouped %d messages into %d conversation groups", len(messages), len(groups))
    return groups


def _find_parent_id(msg: dict, id_to_msg: dict) -> str | None:
    """
    Return the parent message ID if this message is a reply to one
    that exists in our current batch.
    """
    # Discord embeds replied-to message content; we stored it as referenced_message.
    # We can't directly get the parent ID from our stripped struct, so we rely on
    # the presence of referenced_message content as a heuristic signal.
    # True parent-ID linkage would require fetching the raw 'message_reference' field.
    # For now, referenced_message signals "this is a reply" but we can't chain by ID.
    return None  # Extended in a future phase with raw message_reference field


def _find_chain_root(msg_id: str, chains: dict) -> str | None:
    """Find which chain (by root ID) contains a given message ID."""
    for root_id, chain_msgs in chains.items():
        for m in chain_msgs:
            if m["message_id"] == msg_id:
                return root_id
    return None


def _group_by_time_window(msgs: list) -> list:
    """
    Group messages into buckets where consecutive messages
    are within THREAD_WINDOW_MINUTES of each other.
    """
    if not msgs:
        return []

    groups = []
    current_group = [msgs[0]]

    for msg in msgs[1:]:
        prev_ts = _parse_ts(current_group[-1]["timestamp"])
        curr_ts = _parse_ts(msg["timestamp"])
        delta_minutes = (curr_ts - prev_ts).total_seconds() / 60

        if delta_minutes <= THREAD_WINDOW_MINUTES:
            current_group.append(msg)
        else:
            groups.append(current_group)
            current_group = [msg]

    groups.append(current_group)
    return groups
