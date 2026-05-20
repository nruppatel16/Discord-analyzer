#!/bin/bash
# setup.sh — One-time setup for Discord Analyzer.
# Run once after cloning: bash setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_PY="$SCRIPT_DIR/main.py"
RUN_SH="$SCRIPT_DIR/run.sh"
LOG_DIR="$SCRIPT_DIR/logs"
REPORTS_DIR="$SCRIPT_DIR/reports"
ENV_FILE="$SCRIPT_DIR/.env"

echo ""
echo "========================================"
echo "  Discord Analyzer — Setup"
echo "========================================"

# 1. Install Python dependencies
echo ""
echo "[1/5] Installing Python dependencies ..."
pip3 install --quiet requests pyyaml python-dotenv
echo "      Done: requests, pyyaml, python-dotenv installed."

# 2. Create reports/ and logs/ directories
echo ""
echo "[2/5] Creating output directories ..."
mkdir -p "$REPORTS_DIR" "$LOG_DIR"
echo "      Done: $REPORTS_DIR, $LOG_DIR"

# 3. Create .env template if it doesn't already exist
echo ""
echo "[3/5] Creating .env template (if not present) ..."
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'EOF'
DISCORD_TOKEN=
EMAIL_FROM=
EMAIL_PASSWORD=
EMAIL_TO=
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
HOURS_LOOKBACK=5
FETCH_DELAY_SECONDS=2
EOF
    echo "      Created: $ENV_FILE"
else
    echo "      Skipped: .env already exists."
fi

# 4. Make run.sh executable and patch its path
echo ""
echo "[4/5] Configuring run.sh ..."
sed -i "s|/path/to/discord-analyzer|$SCRIPT_DIR|g" "$RUN_SH"
chmod +x "$RUN_SH"
echo "      Done: run.sh is executable."

# 5. Register cron job (runs at 06:00, 10:00, 14:00, 18:00, 22:00 every day)
echo ""
echo "[5/5] Registering cron job ..."
CRON_LINE="0 6,10,14,18,22 * * * $RUN_SH >> $LOG_DIR/analyzer.log 2>&1"

# Check if the cron job already exists to avoid duplicates
EXISTING=$(crontab -l 2>/dev/null | grep -F "$RUN_SH" || true)
if [ -z "$EXISTING" ]; then
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "      Cron job added: $CRON_LINE"
else
    echo "      Skipped: cron job already registered."
fi

echo ""
echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo ""
echo "NEXT STEPS:"
echo ""
echo "  1. Fill in your credentials in .env:"
echo "     $ENV_FILE"
echo ""
echo "     DISCORD_TOKEN   — Your Discord user token"
echo "                       (DevTools → Network → any API call → Authorization header)"
echo "     EMAIL_FROM      — Your Gmail address"
echo "     EMAIL_PASSWORD  — Gmail App Password (not login password)"
echo "                       Enable 2FA → myaccount.google.com/apppasswords"
echo "     EMAIL_TO        — Where to send reports"
echo ""
echo "  2. Fill in your server/channel IDs in servers.yaml"
echo "     (Right-click server/channel in Discord → Copy ID)"
echo "     Enable Developer Mode: Settings → Advanced → Developer Mode"
echo ""
echo "  3. Test a manual run:"
echo "     cd $SCRIPT_DIR && python3 main.py"
echo ""
echo "  4. (Optional) Activate LLM analysis:"
echo "     ollama pull qwen2.5:7b"
echo "     Then set OLLAMA_URL=http://localhost:11434 in .env"
echo "     And swap _stub_analyze_group → _llm_analyze_group in analyzer.py"
echo ""
echo "  Cron runs at: 06:00, 10:00, 14:00, 18:00, 22:00 daily"
echo "  Logs: $LOG_DIR/analyzer.log"
echo "  Reports: $REPORTS_DIR/latest.html"
echo ""
