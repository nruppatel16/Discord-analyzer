"""
analyzer.py — Analyzes grouped conversation data and produces structured output.

PHASE 1: STUB implementation.
Returns clearly-labelled placeholder data so the full report pipeline
can be developed and tested end-to-end.

To activate the real LLM (Phase 2):
  1. Run: ollama pull qwen2.5:7b
  2. Set OLLAMA_URL in .env
  3. Replace the body of _stub_analyze_group() with _llm_analyze_group()
     — the function signature stays identical.
"""

import json
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

# Common ticker pattern: 1-5 uppercase letters, optionally preceded by $ sign
TICKER_RE = re.compile(r'\$([A-Z]{1,5})\b|(?<![a-z])([A-Z]{2,5})(?![a-z])')

# Words that look like tickers but aren't (common false positives in chat)
TICKER_BLACKLIST = {
    "I", "A", "AT", "BE", "DO", "GO", "IF", "IN", "IS", "IT", "ME", "MY",
    "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP", "US", "WE", "BY",
    "CEO", "CFO", "COO", "IPO", "ETF", "RSI", "ATH", "ATL", "DCA", "DD",
    "IMO", "TBH", "FYI", "EPS", "PE", "PEG", "YOY", "QOQ", "FOMO", "YOLO",
    "GDP", "CPI", "FED", "SEC", "NYSE", "TSX", "NASDAQ",
}


def analyze(conversation_groups: list) -> dict:
    """
    Main entry point: accepts conversation groups from grouper.py,
    returns structured analysis dict.

    Output schema:
    {
        "tickers": [...],
        "lessons": [...],
        "general_discussion": [...]
    }
    """
    tickers_map: dict[str, dict] = {}
    lessons: list[dict] = []
    general_discussion: list[dict] = []

    for group in conversation_groups:
        result = _stub_analyze_group(group)

        # Merge ticker data (accumulate mentions across groups)
        for t in result.get("tickers", []):
            sym = t["symbol"]
            if sym in tickers_map:
                tickers_map[sym]["mentions"] += t["mentions"]
                tickers_map[sym]["unique_users"] = max(
                    tickers_map[sym]["unique_users"], t["unique_users"]
                )
            else:
                tickers_map[sym] = t

        lessons.extend(result.get("lessons", []))
        general_discussion.extend(result.get("general_discussion", []))

    return {
        "tickers": list(tickers_map.values()),
        "lessons": lessons,
        "general_discussion": general_discussion,
    }


def _stub_analyze_group(group: dict) -> dict:
    """
    STUB: Extracts tickers with regex and returns placeholder analysis text.
    Replace this function body with _llm_analyze_group() to activate the LLM.
    """
    server = group["server"]
    channel = group["channel"]
    mode = group["mode"]
    messages = group["messages"]

    all_text = " ".join(m["content"] for m in messages)
    authors = list({m["author"] for m in messages})

    tickers = []
    lessons = []
    general = []

    # --- Ticker extraction (regex, works in all modes) ---
    found_tickers = _extract_tickers(all_text)
    for sym in found_tickers:
        tickers.append({
            "symbol": sym,
            "server": server,
            "channel": channel,
            "mentions": all_text.upper().count(sym),
            "unique_users": len(authors),
            "sentiment": "[STUB] Sentiment pending LLM",
            "community_bet": "[STUB] Community position pending LLM",
            "reason": f"[STUB] {sym} was discussed in #{channel} on {server}. "
                      f"Real thesis will be extracted by LLM in Phase 2.",
        })

    # --- Lessons (qa_educational mode) ---
    if mode == "qa_educational":
        lessons.append({
            "server": server,
            "channel": channel,
            "topic": f"[STUB] Lesson from #{channel}",
            "content": (
                "[STUB] This section will contain a progressive learning narrative "
                "extracted from Q&A and discussions in this channel. "
                "The LLM will start from the basic concept raised, build through the "
                "nuances debated, and end with the advanced insight reached. "
                f"({len(messages)} messages analysed from {len(authors)} users.)"
            ),
        })

    # --- General discussion (all modes) ---
    general.append({
        "server": server,
        "channel": channel,
        "highlights": [
            f"[STUB] {len(messages)} messages from {len(authors)} user(s) in this session.",
            "[STUB] Notable points, plans, warnings, and debates will be extracted by LLM.",
            f"[STUB] Sample content: \"{all_text[:120].strip()}...\"" if len(all_text) > 120 else f"[STUB] Content: \"{all_text.strip()}\"",
        ],
    })

    return {"tickers": tickers, "lessons": lessons, "general_discussion": general}


# ---------------------------------------------------------------------------
# PHASE 2 — Real LLM implementation (uncomment + call from analyze() to use)
# ---------------------------------------------------------------------------

def _llm_analyze_group(group: dict) -> dict:
    """
    Real LLM analysis via Ollama. Identical signature to _stub_analyze_group.
    Swap this into analyze() when Ollama is running.
    """
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    server = group["server"]
    channel = group["channel"]
    mode = group["mode"]
    messages = group["messages"]

    formatted = "\n".join(
        f"[{m['author']}]: {m['content']}" for m in messages
    )

    prompt = _build_prompt(server, channel, mode, formatted)

    try:
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        return _parse_llm_response(raw, server, channel, mode)
    except Exception as exc:
        logger.error("Ollama call failed for [%s / %s]: %s", server, channel, exc)
        # Fall back to stub so the pipeline never crashes
        return _stub_analyze_group(group)


def _build_prompt(server: str, channel: str, mode: str, messages_text: str) -> str:
    base = (
        f"You are a financial market analyst reviewing Discord messages.\n"
        f"Server: {server}\nChannel: {channel}\nMode: {mode}\n\n"
        f"Messages:\n{messages_text}\n\n"
    )

    if mode == "qa_educational":
        return base + (
            "Extract:\n"
            "1. All stock/ETF tickers mentioned, their sentiment, and why.\n"
            "2. A single progressive learning narrative from Q&A — start simple, build to nuance.\n"
            "3. General discussion highlights.\n"
            "Return JSON matching this schema exactly:\n"
            '{"tickers":[{"symbol":"","server":"","channel":"","mentions":0,"unique_users":0,'
            '"sentiment":"","community_bet":"","reason":""}],'
            '"lessons":[{"server":"","channel":"","topic":"","content":""}],'
            '"general_discussion":[{"server":"","channel":"","highlights":[]}]}'
        )
    else:
        return base + (
            "Extract:\n"
            "1. All stock/ETF tickers mentioned, their sentiment, and why.\n"
            "2. General discussion highlights — every notable point, plan, warning, debate.\n"
            "Return JSON matching this schema exactly:\n"
            '{"tickers":[{"symbol":"","server":"","channel":"","mentions":0,"unique_users":0,'
            '"sentiment":"","community_bet":"","reason":""}],'
            '"lessons":[],'
            '"general_discussion":[{"server":"","channel":"","highlights":[]}]}'
        )


def _parse_llm_response(raw: str, server: str, channel: str, mode: str) -> dict:
    """Extract JSON from the LLM response string."""
    try:
        # Find the first { ... } block
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("Could not parse LLM JSON for [%s / %s]: %s", server, channel, exc)
        return {"tickers": [], "lessons": [], "general_discussion": []}


def _extract_tickers(text: str) -> list:
    """Simple regex-based ticker extraction used by the stub."""
    found = set()
    for m in TICKER_RE.finditer(text):
        sym = (m.group(1) or m.group(2)).upper()
        if sym not in TICKER_BLACKLIST and len(sym) >= 2:
            found.add(sym)
    return sorted(found)
