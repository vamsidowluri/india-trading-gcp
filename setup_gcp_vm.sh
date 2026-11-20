#!/usr/bin/env bash
set -e

echo "=========================================================="
echo "🚀 Setting up Autonomous Cloud Trading Daemon on GCP VM"
echo "=========================================================="

# 1. Update OS and install python3 prerequisites
echo "📦 Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl

# 2. Setup Virtual Environment
echo "🐍 Setting up Python Virtual Environment..."
cd "$(dirname "$0")"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Create .env if not exists
if [ ! -f .env ]; then
    echo "⚙️ Creating .env configuration file..."
    cp .env.example .env
fi

# 4. Configure Systemd Daemon Service
echo "🔧 Configuring systemd background service..."
CURRENT_USER=$(whoami)
CURRENT_DIR=$(pwd)

# Replace user and path in service file dynamically
sed -i "s|User=ubuntu|User=$CURRENT_USER|g" trading.service
sed -i "s|/home/ubuntu/india-trading-gcp|$CURRENT_DIR|g" trading.service

sudo cp trading.service /etc/systemd/system/trading.service
sudo systemctl daemon-reload
sudo systemctl enable trading.service
sudo systemctl restart trading.service

echo ""
echo "=========================================================="
echo "✅ Setup Complete! Trading Daemon is now RUNNING 24/7."
echo "=========================================================="
echo "Useful Commands:"
echo "• Check Live Logs:    sudo journalctl -u trading -f"
echo "• Service Status:     sudo systemctl status trading"
echo "• Restart Bot:        sudo systemctl restart trading"
echo "• Stop Bot:           sudo systemctl stop trading"
echo "=========================================================="
