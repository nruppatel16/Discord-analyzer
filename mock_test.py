"""
mock_test.py — Dry-run Phase 1 verification with synthetic data.
No Discord token, no email, no network calls required.
"""

import os
import sys
from datetime import datetime, timezone, timedelta

# ── Step 0: ensure reports/ dir exists ─────────────────────────────────────
os.makedirs("reports", exist_ok=True)

print("=" * 60)
print("  Discord Analyzer — Phase 1 Dry Run")
print("=" * 60)


# ── Step 1: Build fake messages ─────────────────────────────────────────────
print("\n[1/5] Injecting 10 fake messages across 2 servers / 4 channels ...")

now = datetime.now(timezone.utc)

def ts(minutes_ago=0):
    return (now - timedelta(minutes=minutes_ago)).isoformat()

fake_messages = [
    # Server 1 / channel: single-stock-picks  (mode: qa_educational)
    {
        "message_id": "1001",
        "author": "alice",
        "content": "What does P/E ratio actually mean for growth stocks like $PLTR?",
        "timestamp": ts(50),
        "server_name": "The Money Maze Community",
        "channel_name": "single-stock-picks",
        "referenced_message": None,
    },
    {
        "message_id": "1002",
        "author": "bob",
        "content": "P/E is price divided by earnings per share. For PLTR it's high because market bets on future growth, not current profits.",
        "timestamp": ts(48),
        "server_name": "The Money Maze Community",
        "channel_name": "single-stock-picks",
        "referenced_message": "What does P/E ratio actually mean for growth stocks like $PLTR?",
    },
    {
        "message_id": "1003",
        "author": "carol",
        "content": "Right, and CCO is the opposite — low P/E, established cash flow. Very different thesis.",
        "timestamp": ts(45),
        "server_name": "The Money Maze Community",
        "channel_name": "single-stock-picks",
        "referenced_message": None,
    },
    # Server 1 / channel: stock-discussions (mode: qa_educational)
    {
        "message_id": "1004",
        "author": "dave",
        "content": "AMZN just broke resistance at 190. Volume confirming. Adding here.",
        "timestamp": ts(30),
        "server_name": "The Money Maze Community",
        "channel_name": "stock-discussions",
        "referenced_message": None,
    },
    {
        "message_id": "1005",
        "author": "alice",
        "content": "I've been watching AMZN too. Their AWS segment is the real story, not retail.",
        "timestamp": ts(28),
        "server_name": "The Money Maze Community",
        "channel_name": "stock-discussions",
        "referenced_message": None,
    },
    # Server 2 / channel: swing-trades (mode: ticker_discussion)
    {
        "message_id": "2001",
        "author": "eve",
        "content": "Entered $PLTR at 24.50, targeting 28. Stop at 23.",
        "timestamp": ts(20),
        "server_name": "Market Masters",
        "channel_name": "swing-trades",
        "referenced_message": None,
    },
    {
        "message_id": "2002",
        "author": "frank",
        "content": "Nice setup on PLTR. I see the same pattern. Bullish on this one short term.",
        "timestamp": ts(18),
        "server_name": "Market Masters",
        "channel_name": "swing-trades",
        "referenced_message": None,
    },
    # Server 2 / channel: chat (mode: ticker_discussion)
    {
        "message_id": "2003",
        "author": "grace",
        "content": "Anyone looking at XEQT for the long term? I've been DCA-ing into it every month.",
        "timestamp": ts(10),
        "server_name": "Market Masters",
        "channel_name": "chat",
        "referenced_message": None,
    },
    {
        "message_id": "2004",
        "author": "henry",
        "content": "XEQT is solid. Low MER, globally diversified. Good for passive investors.",
        "timestamp": ts(8),
        "server_name": "Market Masters",
        "channel_name": "chat",
        "referenced_message": None,
    },
    {
        "message_id": "2005",
        "author": "iris",
        "content": "I'm split between XEQT and VFV. VFV is pure US exposure but XEQT spreads the risk.",
        "timestamp": ts(6),
        "server_name": "Market Masters",
        "channel_name": "chat",
        "referenced_message": None,
    },
]

print(f"      Injected {len(fake_messages)} messages.")
assert len(fake_messages) == 10, "Expected exactly 10 messages"
print("      PASSED: 10 messages created.")

# Fake server config matching the messages above
server_config = {
    "servers": [
        {
            "name": "The Money Maze Community",
            "server_id": "fake-001",
            "mode": "qa_educational",
            "channels": [
                {"name": "single-stock-picks", "channel_id": "fake-ch-01"},
                {"name": "stock-discussions",  "channel_id": "fake-ch-02"},
            ],
        },
        {
            "name": "Market Masters",
            "server_id": "fake-002",
            "mode": "ticker_discussion",
            "channels": [
                {"name": "swing-trades", "channel_id": "fake-ch-03"},
                {"name": "chat",         "channel_id": "fake-ch-04"},
            ],
        },
    ]
}


# ── Step 2: grouper ──────────────────────────────────────────────────────────
print("\n[2/5] Running grouper.py ...")
import grouper

groups = grouper.group_messages(fake_messages, server_config)
assert len(groups) > 0, "grouper returned no groups"

servers_seen  = {g["server"]  for g in groups}
channels_seen = {g["channel"] for g in groups}
modes_seen    = {g["mode"]    for g in groups}
total_msgs_in_groups = sum(len(g["messages"]) for g in groups)

print(f"      Groups created   : {len(groups)}")
print(f"      Servers covered  : {sorted(servers_seen)}")
print(f"      Channels covered : {sorted(channels_seen)}")
print(f"      Modes seen       : {sorted(modes_seen)}")
print(f"      Messages in groups: {total_msgs_in_groups} / {len(fake_messages)}")

assert "The Money Maze Community" in servers_seen
assert "Market Masters" in servers_seen
assert "qa_educational" in modes_seen
assert "ticker_discussion" in modes_seen
assert total_msgs_in_groups == len(fake_messages), "Not all messages ended up in groups"
print("      PASSED: all messages grouped, both modes present.")


# ── Step 3: analyzer (stub) ───────────────────────────────────────────────────
print("\n[3/5] Running analyzer.py (stub) ...")
import analyzer

result = analyzer.analyze(groups)

assert "tickers"            in result, "Missing 'tickers' key"
assert "lessons"            in result, "Missing 'lessons' key"
assert "general_discussion" in result, "Missing 'general_discussion' key"

tickers = result["tickers"]
lessons = result["lessons"]
general = result["general_discussion"]

print(f"      Tickers found    : {[t['symbol'] for t in tickers]}")
print(f"      Lessons produced : {len(lessons)}")
print(f"      Discussion blocks: {len(general)}")

# Every ticker must have required fields
required_ticker_fields = {"symbol","server","channel","mentions","unique_users","sentiment","community_bet","reason"}
for t in tickers:
    missing = required_ticker_fields - set(t.keys())
    assert not missing, f"Ticker {t.get('symbol')} missing fields: {missing}"

# Stub text must be clearly labelled
for t in tickers:
    assert "[STUB]" in t["sentiment"] or "[STUB]" in t["reason"], \
        f"Ticker {t['symbol']} missing [STUB] label"

for les in lessons:
    assert "[STUB]" in les["content"], "Lesson missing [STUB] label"
    assert les["server"] in ("The Money Maze Community",), \
        f"Lesson from unexpected server: {les['server']}"

# No lessons from ticker_discussion servers
lesson_servers = {l["server"] for l in lessons}
assert "Market Masters" not in lesson_servers, "ticker_discussion server produced lessons"

for g in general:
    assert len(g["highlights"]) >= 1, "General discussion block has no highlights"
    for h in g["highlights"]:
        assert "[STUB]" in h, f"Highlight missing [STUB] label: {h}"

print("      PASSED: schema valid, [STUB] labels present, lessons only from qa_educational.")


# ── Step 4: reporter ──────────────────────────────────────────────────────────
print("\n[4/5] Running reporter.py ...")
import reporter

period_end   = now
period_start = now - timedelta(hours=5)
html = reporter.build_report(result, period_start, period_end)

# Check all 4 sections present
assert "<html"                   in html, "Missing <html> tag"
assert "Discord Market Digest"   in html, "Missing masthead"
assert "Tickers on the Radar"    in html, "Missing Tickers section"
assert "Lessons from the Community" in html, "Missing Lessons section"
assert "General Discussion"      in html, "Missing General Discussion section"

# Check stub text flows through to HTML
assert "[STUB]" in html, "No [STUB] placeholders in report HTML"

# Basic HTML sanity: matching open/close counts for key tags
for tag in ("html", "body", "head"):
    opens  = html.count(f"<{tag}")
    closes = html.count(f"</{tag}>")
    assert opens == closes == 1, f"Unbalanced <{tag}> tags: {opens} open, {closes} close"

path = reporter.save_report(html, "reports/test_run.html")
assert os.path.exists(path), f"Report file not found at {path}"
file_size = os.path.getsize(path)
print(f"      Saved to : {path}")
print(f"      File size: {file_size:,} bytes")
assert file_size > 1000, "Report suspiciously small"
print("      PASSED: all 4 sections present, HTML balanced, [STUB] visible, file saved.")


# ── Step 5: confirm ───────────────────────────────────────────────────────────
print("\n[5/5] Summary")
print(f"      Messages processed : {len(fake_messages)}")
print(f"      Groups             : {len(groups)}")
print(f"      Tickers extracted  : {len(tickers)}")
print(f"      Lessons            : {len(lessons)}")
print(f"      Discussion blocks  : {len(general)}")
print(f"      Report             : reports/test_run.html ({file_size:,} bytes)")

print()
print("=" * 60)
print("  PHASE 1 DRY RUN — ALL STEPS PASSED")
print("=" * 60)
