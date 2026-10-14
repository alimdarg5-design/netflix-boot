#!/usr/bin/env bash
# ── Netflix VIP Bot — VPS Deploy Script (Ubuntu/Debian) ──
set -e

APP_DIR="/opt/netflix-bot"
SERVICE="netflixbot"

echo "==> System update + dependencies"
sudo apt update -y
sudo apt install -y python3 python3-venv python3-pip git

echo "==> App folder: $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"

echo "==> Files copy (bot.py, requirements.txt, Procfile)"
cp bot.py requirements.txt Procfile "$APP_DIR"/

echo "==> Virtual environment"
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

if [ ! -f "$APP_DIR/.env" ]; then
  echo "==> .env nahi mila — banaya ja raha hai (values edit karo!)"
  cat > "$APP_DIR/.env" <<'EOF'
BOT_TOKEN=YAHAN_TELEGRAM_BOT_TOKEN
GITHUB_REPO=alimdarg5-design/netflix-boot
GITHUB_TOKEN=YAHAN_GITHUB_PAT
ACCOUNTS_FOLDER=netflix_accounts
PROXY_URL=
EOF
  echo ">>> ABHI '$APP_DIR/.env' kholo aur asli values daalo, phir script dobara chalao."
  exit 0
fi

echo "==> systemd service install"
sudo tee /etc/systemd/system/${SERVICE}.service >/dev/null <<EOF
[Unit]
Description=Netflix VIP Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"

echo "==> Status:"
sudo systemctl status "$SERVICE" --no-pager -l
echo ""
echo "Logs dekhne ke liye:  journalctl -u $SERVICE -f"