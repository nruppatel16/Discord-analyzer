"""
analyzer.py — Analyzes grouped conversation data using Ollama LLM.

PHASE 2: Real LLM integration.

Three separate Ollama calls per run:
  1. Ticker extraction   — all messages, all channels
  2. Lessons             — qa_educational channels only
  3. General discussion  — all messages, all channels

Batching: max 50 messages per call (fits 8 GB RAM + 7B model context).
3-second delay between calls to avoid overloading Ollama.
Fallback: on any error (connection, timeout, bad JSON) the affected
section falls back to stub output. Other sections continue unaffected.
The pipeline never crashes.
"""

import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

BATCH_SIZE = 50        # max messages per Ollama call
CALL_DELAY = 3         # seconds between Ollama calls
OLLAMA_TIMEOUT = 120   # seconds per HTTP request

# ---------------------------------------------------------------------------
# Stub utilities — regex ticker extraction, kept for fallback
# ---------------------------------------------------------------------------

TICKER_RE = re.compile(r'\$([A-Z]{1,5})\b|(?<![a-z])([A-Z]{2,5})(?![a-z])')

TICKER_BLACKLIST = {
    "I", "A", "AT", "BE", "DO", "GO", "IF", "IN", "IS", "IT", "ME", "MY",
    "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP", "US", "WE", "BY",
    "CEO", "CFO", "COO", "IPO", "ETF", "RSI", "ATH", "ATL", "DCA", "DD",
    "IMO", "TBH", "FYI", "EPS", "PE", "PEG", "YOY", "QOQ", "FOMO", "YOLO",
    "GDP", "CPI", "FED", "SEC", "NYSE", "TSX", "NASDAQ",
}


# ===========================================================================
# PUBLIC API — identical signature to Phase 1
# ===========================================================================

def analyze(conversation_groups: list) -> dict:
    """
    Main entry point. Accepts conversation groups from grouper.py.
    Returns structured analysis dict:
    {
        "tickers":            [...],
        "lessons":            [...],
        "general_discussion": [...]
    }
    """
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    # ── Connectivity check ────────────────────────────────────────────────
    if not _check_ollama(ollama_url):
        logger.warning(
            "Ollama not reachable at %s — falling back to stub for all sections.", ollama_url
        )
        return _stub_analyze_all(conversation_groups)

    logger.info("Ollama reachable at %s  model=%s", ollama_url, model)

    # ── Flatten message lists with their server/channel context ──────────
    all_ctx: list[dict] = []     # every message + context
    qa_ctx:  list[dict] = []     # qa_educational only

    for group in conversation_groups:
        server  = group["server"]
        channel = group["channel"]
        mode    = group["mode"]
        for msg in group["messages"]:
            entry = {"server": server, "channel": channel, "mode": mode, "msg": msg}
            all_ctx.append(entry)
            if mode == "qa_educational":
                qa_ctx.append(entry)

    if not all_ctx:
        logger.info("No messages to analyze.")
        return {"tickers": [], "lessons": [], "general_discussion": []}

    # ── Call 1: Ticker extraction ─────────────────────────────────────────
    logger.info(
        "Ollama 1/3 — Ticker extraction  (%d messages, batch=%d)",
        len(all_ctx), BATCH_SIZE,
    )
    tickers = _call_tickers(ollama_url, model, all_ctx, conversation_groups)
    time.sleep(CALL_DELAY)

    # ── Call 2: Lessons ───────────────────────────────────────────────────
    logger.info(
        "Ollama 2/3 — Lessons  (%d qa_educational messages)", len(qa_ctx)
    )
    lessons = _call_lessons(ollama_url, model, qa_ctx, conversation_groups)
    time.sleep(CALL_DELAY)

    # ── Call 3: General discussion ────────────────────────────────────────
    logger.info(
        "Ollama 3/3 — General discussion  (%d messages)", len(all_ctx)
    )
    general_discussion = _call_general(ollama_url, model, all_ctx, conversation_groups)

    return {
        "tickers":            tickers,
        "lessons":            lessons,
        "general_discussion": general_discussion,
    }


# ===========================================================================
# CALL 1 — Ticker extraction
# ===========================================================================

_TICKER_SYSTEM = (
    "You are a financial analyst reading stock trading community messages. "
    "Extract every stock ticker mentioned. "
    "For each ticker return exactly this JSON structure and nothing else, "
    "no explanation, no markdown:\n"
    '{\n'
    '  "tickers": [\n'
    '    {\n'
    '      "symbol": "CCO",\n'
    '      "server": "server name",\n'
    '      "channel": "channel name",\n'
    '      "mentions": 4,\n'
    '      "unique_users": 3,\n'
    '      "sentiment": "Bullish|Bearish|Neutral|Mixed",\n'
    '      "community_bet": "one line on what community is doing",\n'
    '      "reason": "the thesis or reason discussed"\n'
    '    }\n'
    '  ]\n'
    '}\n'
    "Only include tickers with actual discussion. "
    "Return valid JSON only."
)


def _call_tickers(
    url: str, model: str, all_ctx: list, conversation_groups: list
) -> list:
    """
    Batch all messages into 50-message chunks, call Ollama for each,
    merge ticker results across batches.
    Falls back to stub if every batch fails.
    """
    tickers_map: dict[str, dict] = {}
    any_success = False

    for batch in _batch(all_ctx, BATCH_SIZE):
        messages_text = _format_messages(batch)
        prompt = f"{_TICKER_SYSTEM}\n\nMessages:\n{messages_text}"

        raw = _ollama_call(url, model, prompt)
        if raw is None:
            logger.warning("Ticker batch failed — skipping batch of %d.", len(batch))
            continue

        parsed = _parse_json(raw, expected_key="tickers", context="ticker batch")
        if parsed is None:
            continue

        any_success = True
        for t in parsed.get("tickers", []):
            sym = t.get("symbol", "").upper().strip()
            if not sym or len(sym) > 5:
                continue
            if sym in tickers_map:
                tickers_map[sym]["mentions"]     += int(t.get("mentions", 1))
                tickers_map[sym]["unique_users"]  = max(
                    tickers_map[sym]["unique_users"], int(t.get("unique_users", 1))
                )
                # Prefer longer reason/community_bet (more informative)
                if len(t.get("reason", "")) > len(tickers_map[sym].get("reason", "")):
                    tickers_map[sym]["reason"]        = t.get("reason", "")
                    tickers_map[sym]["community_bet"] = t.get("community_bet", "")
                    tickers_map[sym]["sentiment"]     = t.get("sentiment", "Neutral")
            else:
                tickers_map[sym] = {
                    "symbol":        sym,
                    "server":        t.get("server", ""),
                    "channel":       t.get("channel", ""),
                    "mentions":      int(t.get("mentions", 1)),
                    "unique_users":  int(t.get("unique_users", 1)),
                    "sentiment":     t.get("sentiment", "Neutral"),
                    "community_bet": t.get("community_bet", ""),
                    "reason":        t.get("reason", ""),
                }

        time.sleep(CALL_DELAY)

    if not any_success:
        logger.warning("All ticker batches failed — using stub fallback.")
        return _stub_tickers(conversation_groups)

    return list(tickers_map.values())


# ===========================================================================
# CALL 2 — Lessons (qa_educational only)
# ===========================================================================

_LESSONS_SYSTEM = (
    "You are an investing educator. Read these community discussions and extract "
    "all questions asked and answers given. Convert them into one continuous "
    "progressive learning narrative — start from the basic concept being discussed, "
    "build up to the nuance and complexity. Do not split into beginner/advanced "
    "sections. Write it as one flowing lesson. Include every Q&A, miss nothing.\n"
    "Return exactly this JSON and nothing else:\n"
    '{\n'
    '  "lessons": [\n'
    '    {\n'
    '      "server": "server name",\n'
    '      "channel": "channel name",\n'
    '      "topic": "lesson topic in 5 words",\n'
    '      "content": "full progressive lesson text here"\n'
    '    }\n'
    '  ]\n'
    '}'
)


def _call_lessons(
    url: str, model: str, qa_ctx: list, conversation_groups: list
) -> list:
    """
    Batch qa_educational messages, call Ollama for lessons.
    Merges lesson content for the same (server, channel) across batches.
    Falls back to stub if no batches succeed.
    """
    if not qa_ctx:
        return []

    # lessons_map: (server, channel) -> lesson dict
    lessons_map: dict[tuple, dict] = {}
    any_success = False

    for batch in _batch(qa_ctx, BATCH_SIZE):
        messages_text = _format_messages(batch)
        prompt = f"{_LESSONS_SYSTEM}\n\nMessages:\n{messages_text}"

        raw = _ollama_call(url, model, prompt)
        if raw is None:
            logger.warning("Lessons batch failed — skipping batch of %d.", len(batch))
            continue

        parsed = _parse_json(raw, expected_key="lessons", context="lessons batch")
        if parsed is None:
            continue

        any_success = True
        for les in parsed.get("lessons", []):
            server  = les.get("server", "")
            channel = les.get("channel", "")
            key = (server, channel)
            if key in lessons_map:
                # Append additional content from later batches
                existing = lessons_map[key]
                addition = les.get("content", "").strip()
                if addition:
                    existing["content"] = existing["content"].rstrip() + "\n\n" + addition
            else:
                lessons_map[key] = {
                    "server":  server,
                    "channel": channel,
                    "topic":   les.get("topic", ""),
                    "content": les.get("content", ""),
                }

        time.sleep(CALL_DELAY)

    if not any_success:
        logger.warning("All lesson batches failed — using stub fallback.")
        return _stub_lessons(conversation_groups)

    return list(lessons_map.values())


# ===========================================================================
# CALL 3 — General discussion
# ===========================================================================

_GENERAL_SYSTEM = (
    "You are summarizing stock trading community discussions. "
    "For each server and channel, extract every notable point: "
    "what people are doing, planning, debating, warning about, "
    "sharing results on. Miss nothing. Be factual and concise.\n"
    "Return exactly this JSON and nothing else:\n"
    '{\n'
    '  "general_discussion": [\n'
    '    {\n'
    '      "server": "server name",\n'
    '      "channel": "channel name",\n'
    '      "highlights": [\n'
    '        "highlight 1",\n'
    '        "highlight 2"\n'
    '      ]\n'
    '    }\n'
    '  ]\n'
    '}'
)


def _call_general(
    url: str, model: str, all_ctx: list, conversation_groups: list
) -> list:
    """
    Batch all messages, call Ollama for general discussion highlights.
    Merges highlights for the same (server, channel) across batches.
    Falls back to stub if no batches succeed.
    """
    # general_map: (server, channel) -> {"server":..,"channel":..,"highlights":[..]}
    general_map: dict[tuple, dict] = {}
    any_success = False

    for batch in _batch(all_ctx, BATCH_SIZE):
        messages_text = _format_messages(batch)
        prompt = f"{_GENERAL_SYSTEM}\n\nMessages:\n{messages_text}"

        raw = _ollama_call(url, model, prompt)
        if raw is None:
            logger.warning("General batch failed — skipping batch of %d.", len(batch))
            continue

        parsed = _parse_json(raw, expected_key="general_discussion", context="general batch")
        if parsed is None:
            continue

        any_success = True
        for g in parsed.get("general_discussion", []):
            server  = g.get("server", "")
            channel = g.get("channel", "")
            key = (server, channel)
            new_highlights = [h for h in g.get("highlights", []) if h]
            if key in general_map:
                # Merge highlights, deduplicate by exact match
                existing = general_map[key]["highlights"]
                seen = set(existing)
                for h in new_highlights:
                    if h not in seen:
                        existing.append(h)
                        seen.add(h)
            else:
                general_map[key] = {
                    "server":     server,
                    "channel":    channel,
                    "highlights": new_highlights,
                }

        time.sleep(CALL_DELAY)

    if not any_success:
        logger.warning("All general batches failed — using stub fallback.")
        return _stub_general(conversation_groups)

    return list(general_map.values())


# ===========================================================================
# Core Ollama HTTP call
# ===========================================================================

def _ollama_call(url: str, model: str, prompt: str) -> str | None:
    """
    POST to Ollama /api/generate. Returns the response string, or None on error.
    Handles: connection refused, timeout, non-200 status, malformed response.
    """
    endpoint = f"{url}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False}

    try:
        resp = requests.post(endpoint, json=payload, timeout=OLLAMA_TIMEOUT)
    except requests.exceptions.ConnectionError as exc:
        logger.error("Ollama connection refused at %s: %s", endpoint, exc)
        return None
    except requests.exceptions.Timeout:
        logger.error("Ollama request timed out after %ds.", OLLAMA_TIMEOUT)
        return None
    except requests.exceptions.RequestException as exc:
        logger.error("Ollama request error: %s", exc)
        return None

    if resp.status_code != 200:
        logger.error("Ollama returned HTTP %d: %s", resp.status_code, resp.text[:200])
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.error("Ollama response is not valid JSON.")
        return None

    response_text = data.get("response", "").strip()
    if not response_text:
        logger.warning("Ollama returned an empty response.")
        return None

    return response_text


def _check_ollama(url: str) -> bool:
    """Quick health check: GET /api/tags (Ollama's list-models endpoint)."""
    try:
        resp = requests.get(f"{url}/api/tags", timeout=5)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


# ===========================================================================
# JSON parsing — strips markdown fences, catches all errors
# ===========================================================================

# Matches ```json ... ``` or ``` ... ```
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_json(raw: str, expected_key: str, context: str) -> dict | None:
    """
    Strip markdown fences, then parse JSON.
    Returns the parsed dict, or None on failure (logs the raw response).
    """
    # Remove markdown code fences if present
    fence_match = _FENCE_RE.search(raw)
    text = fence_match.group(1) if fence_match else raw

    # Find the outermost { ... } block
    try:
        start = text.index("{")
        end   = text.rindex("}") + 1
        text  = text[start:end]
    except ValueError:
        logger.warning("[%s] No JSON object found in response. Raw:\n%s", context, raw[:500])
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("[%s] JSON parse error: %s\nRaw (first 500):\n%s", context, exc, raw[:500])
        return None

    if expected_key not in parsed:
        logger.warning(
            "[%s] Expected key '%s' not in parsed JSON. Keys: %s",
            context, expected_key, list(parsed.keys()),
        )
        # Still return it — caller will do .get(expected_key, [])
    return parsed


# ===========================================================================
# Message formatting helpers
# ===========================================================================

def _format_messages(ctx_entries: list) -> str:
    """
    Format a list of context entries into a readable block for the LLM.
    Groups consecutive messages from the same server/channel under one header.
    """
    lines = []
    current_header = None

    for entry in ctx_entries:
        header = f"[{entry['server']} / #{entry['channel']}]"
        if header != current_header:
            lines.append(f"\n{header}")
            current_header = header
        msg = entry["msg"]
        content = msg.get("content", "").strip()
        if content:
            lines.append(f"[{msg['author']}]: {content}")

    return "\n".join(lines).strip()


def _batch(items: list, size: int):
    """Yield successive chunks of `size` from `items`."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ===========================================================================
# Stub fallbacks — used when Ollama is unavailable or a section fails
# ===========================================================================

def _stub_analyze_all(conversation_groups: list) -> dict:
    """Full stub fallback — runs all groups through the per-group stub."""
    tickers_map: dict[str, dict] = {}
    lessons: list[dict]          = []
    general: list[dict]          = []

    for group in conversation_groups:
        result = _stub_analyze_group(group)
        for t in result.get("tickers", []):
            sym = t["symbol"]
            if sym in tickers_map:
                tickers_map[sym]["mentions"]    += t["mentions"]
                tickers_map[sym]["unique_users"] = max(
                    tickers_map[sym]["unique_users"], t["unique_users"]
                )
            else:
                tickers_map[sym] = t
        lessons.extend(result.get("lessons", []))
        general.extend(result.get("general_discussion", []))

    return {
        "tickers":            list(tickers_map.values()),
        "lessons":            lessons,
        "general_discussion": general,
    }


def _stub_tickers(conversation_groups: list) -> list:
    """Stub fallback for the tickers section only."""
    tickers_map: dict[str, dict] = {}
    for group in conversation_groups:
        for t in _stub_analyze_group(group).get("tickers", []):
            sym = t["symbol"]
            if sym in tickers_map:
                tickers_map[sym]["mentions"]    += t["mentions"]
                tickers_map[sym]["unique_users"] = max(
                    tickers_map[sym]["unique_users"], t["unique_users"]
                )
            else:
                tickers_map[sym] = t
    return list(tickers_map.values())


def _stub_lessons(conversation_groups: list) -> list:
    """Stub fallback for the lessons section only."""
    lessons = []
    for group in conversation_groups:
        if group["mode"] == "qa_educational":
            lessons.extend(_stub_analyze_group(group).get("lessons", []))
    return lessons


def _stub_general(conversation_groups: list) -> list:
    """Stub fallback for the general discussion section only."""
    general = []
    for group in conversation_groups:
        general.extend(_stub_analyze_group(group).get("general_discussion", []))
    return general


def _stub_analyze_group(group: dict) -> dict:
    """
    Per-group stub: regex ticker extraction + placeholder text.
    Identical to Phase 1 implementation — used as fallback throughout.
    """
    server   = group["server"]
    channel  = group["channel"]
    mode     = group["mode"]
    messages = group["messages"]

    all_text = " ".join(m["content"] for m in messages)
    authors  = list({m["author"] for m in messages})

    tickers = []
    lessons = []
    general = []

    for sym in _extract_tickers(all_text):
        tickers.append({
            "symbol":        sym,
            "server":        server,
            "channel":       channel,
            "mentions":      all_text.upper().count(sym),
            "unique_users":  len(authors),
            "sentiment":     "[STUB] Sentiment pending LLM",
            "community_bet": "[STUB] Community position pending LLM",
            "reason":        (
                f"[STUB] {sym} was discussed in #{channel} on {server}. "
                "Ollama unavailable — connect LLM for real analysis."
            ),
        })

    if mode == "qa_educational":
        lessons.append({
            "server":  server,
            "channel": channel,
            "topic":   f"[STUB] Lesson from #{channel}",
            "content": (
                "[STUB] Progressive learning narrative will appear here once "
                f"Ollama is connected. ({len(messages)} messages from {len(authors)} user(s).)"
            ),
        })

    general.append({
        "server":  server,
        "channel": channel,
        "highlights": [
            f"[STUB] {len(messages)} messages from {len(authors)} user(s).",
            "[STUB] Connect Ollama to see real highlights.",
            f"[STUB] Sample: \"{all_text[:120].strip()}...\"" if len(all_text) > 120
            else f"[STUB] Content: \"{all_text.strip()}\"",
        ],
    })

    return {"tickers": tickers, "lessons": lessons, "general_discussion": general}


def _extract_tickers(text: str) -> list:
    """Regex-based ticker extraction used by the stub."""
    found = set()
    for m in TICKER_RE.finditer(text):
        sym = (m.group(1) or m.group(2)).upper()
        if sym not in TICKER_BLACKLIST and len(sym) >= 2:
            found.add(sym)
    return sorted(found)
