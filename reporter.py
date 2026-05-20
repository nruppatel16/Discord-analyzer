"""
reporter.py — Builds a financial-newsletter-style HTML report from analysis data.
Dark background, readable fonts, renders well in email clients.
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"


def _get_edition(dt: datetime) -> str:
    """Return Morning / Afternoon / Evening / Night based on hour (UTC)."""
    h = dt.hour
    if 5 <= h < 12:
        return "Morning"
    elif 12 <= h < 17:
        return "Afternoon"
    elif 17 <= h < 22:
        return "Evening"
    else:
        return "Night"


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%A, %B %-d %Y")


def _render_tickers(tickers: list) -> str:
    if not tickers:
        return "<p class='empty'>No tickers identified in this session.</p>"

    cards = []
    for t in tickers:
        sentiment_class = "bull" if "bull" in t.get("sentiment", "").lower() else \
                          "bear" if "bear" in t.get("sentiment", "").lower() else "neutral"
        cards.append(f"""
        <div class="ticker-card">
            <div class="ticker-header">
                <span class="ticker-symbol">${t['symbol']}</span>
                <span class="sentiment-badge {sentiment_class}">{t.get('sentiment', 'N/A')}</span>
            </div>
            <div class="ticker-meta">
                <span class="meta-item">&#128203; {t['server']}</span>
                <span class="meta-item">&#35; {t['channel']}</span>
                <span class="meta-item">&#128483; {t.get('mentions', 0)} mention(s)</span>
                <span class="meta-item">&#128100; {t.get('unique_users', 0)} user(s)</span>
            </div>
            <div class="ticker-bet"><strong>Community position:</strong> {t.get('community_bet', 'N/A')}</div>
            <div class="ticker-reason">{t.get('reason', '')}</div>
        </div>""")

    return "\n".join(cards)


def _render_lessons(lessons: list) -> str:
    if not lessons:
        return "<p class='empty'>No educational content in this session.</p>"

    items = []
    for lesson in lessons:
        items.append(f"""
        <div class="lesson-block">
            <div class="lesson-source">
                <span class="source-server">{lesson['server']}</span>
                <span class="source-sep">/</span>
                <span class="source-channel">#{lesson['channel']}</span>
            </div>
            <div class="lesson-topic">{lesson.get('topic', '')}</div>
            <div class="lesson-content">{lesson.get('content', '')}</div>
        </div>""")

    return "\n".join(items)


def _render_general(general_discussion: list) -> str:
    if not general_discussion:
        return "<p class='empty'>No general discussion captured this session.</p>"

    # Group by server
    by_server: dict[str, list] = {}
    for g in general_discussion:
        by_server.setdefault(g["server"], []).append(g)

    blocks = []
    for server_name, channels in by_server.items():
        channel_html = []
        for ch in channels:
            highlights = ch.get("highlights", [])
            if not highlights:
                continue
            bullets = "".join(f"<li>{h}</li>" for h in highlights)
            channel_html.append(f"""
            <div class="gen-channel">
                <div class="gen-channel-name">#{ch['channel']}</div>
                <ul class="gen-bullets">{bullets}</ul>
            </div>""")

        if channel_html:
            blocks.append(f"""
        <div class="gen-server">
            <div class="gen-server-name">{server_name}</div>
            {''.join(channel_html)}
        </div>""")

    return "\n".join(blocks) if blocks else "<p class='empty'>No general discussion captured this session.</p>"


def build_report(analysis: dict, period_start: datetime, period_end: datetime) -> str:
    """
    Build the complete HTML report string from the analysis dict.
    Returns the full HTML as a string.
    """
    now = datetime.now(timezone.utc)
    edition = _get_edition(now)
    date_str = _fmt_date(now)

    period_str = (
        f"{period_start.strftime('%H:%M UTC')} — {period_end.strftime('%H:%M UTC, %b %-d')}"
    )

    tickers_html = _render_tickers(analysis.get("tickers", []))
    lessons_html = _render_lessons(analysis.get("lessons", []))
    general_html = _render_general(analysis.get("general_discussion", []))

    ticker_count = len(analysis.get("tickers", []))
    msg_count = sum(
        g.get("mentions", 1) for g in analysis.get("general_discussion", [])
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Discord Market Digest &middot; {edition} &middot; {date_str}</title>
<style>
  /* ── Reset & Base ── */
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0d0f14;
    color: #d4d8e2;
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 15px;
    line-height: 1.65;
    max-width: 780px;
    margin: 0 auto;
    padding: 24px 16px 48px;
  }}
  a {{ color: #7eb3f7; text-decoration: none; }}

  /* ── Header ── */
  .header {{
    border-bottom: 3px solid #2a3a5c;
    padding-bottom: 18px;
    margin-bottom: 32px;
    text-align: center;
  }}
  .masthead {{
    font-size: 28px;
    font-weight: bold;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #e8eaf0;
  }}
  .edition-line {{
    font-size: 13px;
    color: #7a8096;
    margin-top: 4px;
    font-family: 'Courier New', monospace;
    letter-spacing: 1px;
  }}
  .period-line {{
    font-size: 12px;
    color: #555d78;
    margin-top: 2px;
    font-family: 'Courier New', monospace;
  }}

  /* ── Section titles ── */
  .section {{
    margin-bottom: 36px;
  }}
  .section-title {{
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #5a7bbf;
    border-bottom: 1px solid #1e2740;
    padding-bottom: 6px;
    margin-bottom: 18px;
  }}

  /* ── Ticker cards ── */
  .ticker-card {{
    background: #131720;
    border: 1px solid #1e2740;
    border-left: 4px solid #2a5baf;
    border-radius: 4px;
    padding: 14px 16px;
    margin-bottom: 12px;
  }}
  .ticker-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 6px;
  }}
  .ticker-symbol {{
    font-size: 20px;
    font-weight: bold;
    font-family: 'Courier New', monospace;
    color: #e8eaf0;
  }}
  .sentiment-badge {{
    font-size: 11px;
    font-weight: bold;
    padding: 2px 8px;
    border-radius: 3px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }}
  .bull  {{ background: #0d2e1a; color: #4ade80; border: 1px solid #166534; }}
  .bear  {{ background: #2e0d0d; color: #f87171; border: 1px solid #7f1d1d; }}
  .neutral {{ background: #1a1e2e; color: #94a3b8; border: 1px solid #334155; }}
  .ticker-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 6px;
  }}
  .meta-item {{
    font-size: 12px;
    color: #6b7394;
    font-family: 'Courier New', monospace;
  }}
  .ticker-bet {{
    font-size: 13px;
    color: #a8b4cc;
    margin-bottom: 4px;
  }}
  .ticker-reason {{
    font-size: 13px;
    color: #8892aa;
    font-style: italic;
  }}

  /* ── Lessons ── */
  .lesson-block {{
    background: #0f1520;
    border: 1px solid #1e2a40;
    border-left: 4px solid #7e5bbf;
    border-radius: 4px;
    padding: 14px 16px;
    margin-bottom: 16px;
  }}
  .lesson-source {{
    font-size: 11px;
    font-family: 'Courier New', monospace;
    color: #555d78;
    margin-bottom: 6px;
  }}
  .source-server {{ color: #7a8296; }}
  .source-sep {{ color: #444; margin: 0 4px; }}
  .source-channel {{ color: #5a7bbf; }}
  .lesson-topic {{
    font-size: 15px;
    font-weight: bold;
    color: #c4ccdf;
    margin-bottom: 8px;
  }}
  .lesson-content {{
    font-size: 14px;
    color: #8892aa;
    line-height: 1.7;
  }}

  /* ── General discussion ── */
  .gen-server {{
    margin-bottom: 20px;
  }}
  .gen-server-name {{
    font-size: 13px;
    font-weight: bold;
    color: #7a8296;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
  }}
  .gen-channel {{
    background: #111520;
    border: 1px solid #1a2235;
    border-radius: 4px;
    padding: 10px 14px;
    margin-bottom: 8px;
  }}
  .gen-channel-name {{
    font-size: 12px;
    font-family: 'Courier New', monospace;
    color: #4a7baf;
    margin-bottom: 6px;
  }}
  .gen-bullets {{
    padding-left: 18px;
    list-style: disc;
  }}
  .gen-bullets li {{
    font-size: 13px;
    color: #8892aa;
    margin-bottom: 4px;
    line-height: 1.5;
  }}

  /* ── Footer ── */
  .footer {{
    border-top: 1px solid #1a2235;
    padding-top: 14px;
    margin-top: 40px;
    font-size: 11px;
    color: #3a4055;
    font-family: 'Courier New', monospace;
    text-align: center;
  }}

  .empty {{
    font-size: 13px;
    color: #3a4466;
    font-style: italic;
    padding: 8px 0;
  }}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="masthead">Discord Market Digest</div>
  <div class="edition-line">{date_str} &middot; {edition} Edition</div>
  <div class="period-line">Period covered: {period_str}</div>
</div>

<!-- SECTION 1: TICKERS ON THE RADAR -->
<div class="section">
  <div class="section-title">Tickers on the Radar</div>
  {tickers_html}
</div>

<!-- SECTION 2: LESSONS FROM THE COMMUNITY -->
<div class="section">
  <div class="section-title">Lessons from the Community</div>
  {lessons_html}
</div>

<!-- SECTION 3: GENERAL DISCUSSION -->
<div class="section">
  <div class="section-title">General Discussion</div>
  {general_html}
</div>

<!-- FOOTER -->
<div class="footer">
  Discord Analyzer &middot; Generated {now.strftime('%Y-%m-%d %H:%M UTC')} &middot; {ticker_count} ticker(s) identified
</div>

</body>
</html>"""

    return html


def save_report(html: str, path: str = None) -> str:
    """Write the HTML string to disk. Returns the path written."""
    if path is None:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.join(REPORTS_DIR, "latest.html")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report saved to %s", path)
    return path
