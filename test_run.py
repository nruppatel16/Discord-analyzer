"""
test_run.py — One-time end-to-end pipeline validation with real data.

Uses real Discord token, real Ollama, real email.
Writes to test_analyzer.db and reports/test_run.html ONLY.
Does NOT touch analyzer.db, reports/latest.html, or cron.

Usage: python3 test_run.py
"""

import os
import smtplib
import sys
import time
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import yaml
from dotenv import load_dotenv

# Import pipeline modules — all existing logic is reused, nothing duplicated
import dedup
import fetcher
import grouper
import analyzer
import reporter

# ── Isolate test DB from production DB ───────────────────────────────────────
dedup.DB_PATH = "test_analyzer.db"

TEST_HOURS          = 2    # fetch last 2 hours only
TEST_MAX_PER_CHANNEL = 20  # cap per channel to keep the run fast
TEST_REPORT_PATH    = "reports/test_run.html"
DISCORD_API         = "https://discord.com/api/v10"


# ===========================================================================
# Pretty printing helpers
# ===========================================================================

def ok(msg: str):
    print(f"  ✓ {msg}")

def fail(msg: str):
    print(f"  ✗ {msg}")

def section(title: str):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ===========================================================================
# Main test runner
# ===========================================================================

def run():
    print()
    print("━" * 54)
    print("  DISCORD ANALYZER — TEST RUN")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("━" * 54)

    # Tracking for final summary
    status = {
        "discord":  False,
        "messages": 0,
        "ollama":   False,
        "tickers":  0,
        "lessons":  0,
        "general":  0,
        "report":   False,
        "email":    False,
    }

    # ── 1. Load config ────────────────────────────────────────────────────
    section("1 / 7  CONFIG")
    load_dotenv()

    required = ["DISCORD_TOKEN", "EMAIL_FROM", "EMAIL_PASSWORD", "EMAIL_TO"]
    missing = [k for k in required if not os.getenv(k, "").strip()]
    if missing:
        fail(f"Missing .env variables: {', '.join(missing)}")
        _print_summary(status)
        sys.exit(1)

    token          = os.getenv("DISCORD_TOKEN").strip()
    email_from     = os.getenv("EMAIL_FROM").strip()
    email_password = os.getenv("EMAIL_PASSWORD").strip()
    email_to       = os.getenv("EMAIL_TO").strip()
    ollama_url     = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
    delay_seconds  = float(os.getenv("FETCH_DELAY_SECONDS", "2"))

    if not os.path.exists("servers.yaml"):
        fail("servers.yaml not found")
        _print_summary(status)
        sys.exit(1)

    with open("servers.yaml", "r") as f:
        server_config = yaml.safe_load(f)

    ok("Config loaded (.env + servers.yaml)")

    # Warn if no channel IDs are configured
    configured = [
        ch for srv in server_config.get("servers", [])
        for ch in srv.get("channels", [])
        if ch.get("channel_id", "").strip()
    ]
    if not configured:
        fail("No channel IDs configured in servers.yaml — nothing to fetch.")
        _print_summary(status)
        sys.exit(1)

    ok(f"{len(configured)} channel(s) configured across "
       f"{len(server_config.get('servers', []))} server(s)")

    # ── 2. Check Discord connectivity ────────────────────────────────────
    section("2 / 7  DISCORD CONNECTIVITY")
    discord_user = _check_discord(token)
    if discord_user:
        ok(f"Connected to Discord as @{discord_user}")
        status["discord"] = True
    else:
        fail("Could not connect to Discord — check DISCORD_TOKEN in .env")
        # Continue — we still attempt fetching to surface per-channel errors

    # ── 3. Init test dedup DB ─────────────────────────────────────────────
    section("3 / 7  FETCH MESSAGES")
    print(f"  Fetching last {TEST_HOURS}h, max {TEST_MAX_PER_CHANNEL} msgs/channel\n")

    dedup.init_db()
    ok(f"Test DB initialised ({dedup.DB_PATH})")

    all_messages = []
    period_end   = datetime.now(timezone.utc)
    period_start = period_end - timedelta(hours=TEST_HOURS)

    for srv in server_config.get("servers", []):
        server_name = srv["name"]
        for ch in srv.get("channels", []):
            channel_name = ch["name"]
            channel_id   = ch.get("channel_id", "").strip()

            if not channel_id:
                print(f"  ⊘ Skipped [{server_name} / #{channel_name}] — no channel_id")
                continue

            try:
                msgs = fetcher.fetch_channel_messages(
                    channel_id          = channel_id,
                    channel_name        = channel_name,
                    server_name         = server_name,
                    token               = token,
                    hours_lookback      = TEST_HOURS,
                    delay_seconds       = delay_seconds,
                    already_processed_fn = dedup.is_processed,
                )
                msgs = msgs[:TEST_MAX_PER_CHANNEL]  # enforce per-channel cap
                all_messages.extend(msgs)
                ok(f"Fetched {len(msgs):>3} message(s) from  "
                   f"{server_name}  #{channel_name}")
                time.sleep(delay_seconds)

            except Exception as exc:
                fail(f"Fetch failed [{server_name} / #{channel_name}]: {exc}")

    # Mark all fetched messages in test DB (does not touch analyzer.db)
    dedup.mark_processed_bulk([m["message_id"] for m in all_messages])

    status["messages"] = len(all_messages)
    print(f"\n  Total new messages: {len(all_messages)}")

    if not all_messages:
        print("  ⚠  No new messages found in the last "
              f"{TEST_HOURS}h (may all be deduped or channels empty).")

    # ── 4. Check Ollama ───────────────────────────────────────────────────
    section("4 / 7  OLLAMA LLM")
    ollama_ok = analyzer._check_ollama(ollama_url)
    if ollama_ok:
        ok(f"Connected to Ollama at {ollama_url}")
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        ok(f"Model: {model}")
        status["ollama"] = True
    else:
        fail(f"Ollama not reachable at {ollama_url} — "
             "LLM analysis will fall back to stub")

    # ── 5. Group + Analyze ────────────────────────────────────────────────
    section("5 / 7  ANALYSIS")
    groups = grouper.group_messages(all_messages, server_config)
    ok(f"Grouped {len(all_messages)} message(s) into {len(groups)} conversation group(s)")

    try:
        analysis = analyzer.analyze(groups)
        tickers  = analysis.get("tickers", [])
        lessons  = analysis.get("lessons", [])
        general  = analysis.get("general_discussion", [])

        if status["ollama"]:
            ok("LLM analysis complete (Ollama)")
        else:
            ok("Analysis complete (stub fallback — Ollama unavailable)")

        status["tickers"] = len(tickers)
        status["lessons"] = len(lessons)
        status["general"] = len(general)

        ok(f"Tickers found:    {len(tickers)}"
           + (f"  [{', '.join(t['symbol'] for t in tickers)}]" if tickers else ""))
        ok(f"Lessons produced: {len(lessons)}")
        ok(f"Discussion blocks:{len(general)}")

    except Exception as exc:
        fail(f"Analysis failed: {exc}")
        analysis = {"tickers": [], "lessons": [], "general_discussion": []}

    # ── 6. Build + save report ────────────────────────────────────────────
    section("6 / 7  REPORT")
    try:
        html = reporter.build_report(analysis, period_start, period_end)
        os.makedirs("reports", exist_ok=True)
        reporter.save_report(html, TEST_REPORT_PATH)
        size_kb = os.path.getsize(TEST_REPORT_PATH) / 1024
        ok(f"Report generated → {TEST_REPORT_PATH}  ({size_kb:.1f} KB)")
        status["report"] = True
    except Exception as exc:
        fail(f"Report generation failed: {exc}")
        html = "<html><body>Report generation failed.</body></html>"

    # ── 7. Email ──────────────────────────────────────────────────────────
    section("7 / 7  EMAIL")
    email_sent = _send_test_email(html, email_from, email_password, email_to)
    if email_sent:
        ok(f"Email sent to {email_to}")
        status["email"] = True
    else:
        fail(f"Email failed — report saved locally at {TEST_REPORT_PATH}")

    # ── Summary ───────────────────────────────────────────────────────────
    _print_summary(status)


# ===========================================================================
# Helpers
# ===========================================================================

def _check_discord(token: str) -> str | None:
    """
    Validate the Discord token by fetching the current user profile.
    Returns the username on success, None on failure.
    """
    try:
        resp = requests.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": token},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("username", "unknown")
        fail(f"Discord auth failed — HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    except requests.exceptions.ConnectionError as exc:
        fail(f"Discord connection error: {exc}")
        return None
    except requests.exceptions.Timeout:
        fail("Discord request timed out")
        return None
    except Exception as exc:
        fail(f"Discord check error: {exc}")
        return None


def _send_test_email(
    html: str, email_from: str, email_password: str, email_to: str
) -> bool:
    """
    Send the test report email with a [TEST RUN] subject prefix.
    Inline SMTP required here because emailer.send_report() hardcodes
    the production subject line — this avoids touching that file.
    """
    now      = datetime.now(timezone.utc)
    date_str = now.strftime("%b %-d, %Y")
    subject  = f"[TEST RUN] Discord Market Digest · {date_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_from
    msg["To"]      = email_to
    msg.attach(MIMEText(
        "Your email client does not support HTML. "
        f"View the report at {TEST_REPORT_PATH}",
        "plain",
    ))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_from, email_password)
            server.sendmail(email_from, email_to, msg.as_string())
        return True

    except smtplib.SMTPAuthenticationError:
        fail(
            "Email auth failed — EMAIL_PASSWORD must be a Gmail App Password. "
            "Enable 2FA → myaccount.google.com/apppasswords"
        )
        return False
    except smtplib.SMTPException as exc:
        fail(f"SMTP error: {exc}")
        return False
    except OSError as exc:
        fail(f"Email network error: {exc}")
        return False


def _print_summary(status: dict):
    ready = (
        status["discord"]
        and status["ollama"]
        and status["report"]
        and status["email"]
    )

    def sym(val: bool) -> str:
        return "✓" if val else "✗"

    print()
    print("━" * 42)
    print("  TEST RUN SUMMARY")
    print("━" * 42)
    print(f"  Discord fetch:    {sym(status['discord'])}")
    print(f"  Messages fetched: {status['messages']}")
    print(f"  Ollama LLM:       {sym(status['ollama'])}")
    print(f"  Tickers found:    {status['tickers']}")
    print(f"  Lessons:          {status['lessons']}")
    print(f"  Discussion items: {status['general']}")
    print(f"  Report generated: {sym(status['report'])}")
    print(f"  Email sent:       {sym(status['email'])}")
    print("━" * 42)
    print(f"  Ready for autonomy: {'YES' if ready else 'NO'}")
    print("━" * 42)
    print()

    if not ready:
        problems = []
        if not status["discord"]: problems.append("Discord token")
        if not status["ollama"]:  problems.append("Ollama LLM")
        if not status["report"]:  problems.append("Report generation")
        if not status["email"]:   problems.append("Email delivery")
        print(f"  Fix before enabling cron: {', '.join(problems)}")
        print()


if __name__ == "__main__":
    run()
