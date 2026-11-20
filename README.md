# ⚡ Autonomous Indian Stock Market Trading Daemon (GCP Cloud)

An autonomous intraday quantitative trading daemon built for **NIFTY 50 Options** using a **15-Minute Opening Range Breakout (ORB)** model with asymmetric **1:2 Risk-to-Reward**, **AI Hedge Fund Committee analysis (Gemini API)**, and **real-time Telegram bot controls**.

Designed to run **24/7 on a Google Cloud Platform (GCP) Free-Tier `e2-micro` VM**.

---

## 🏛️ System Features
- **15-Minute ORB Engine:** Tracks 09:15–09:30 AM IST range boundaries and detects breakout/retest momentum.
- **Strict 1:2 R:R Guard:** Automatically calculates Entry, Stop Loss (-1R), and Target (+2R).
- **Daily Quota:** Exactly 1 trade per day — zero revenge trading or commission bleed.
- **AI Hedge Fund Committee:** Evaluates market structure and sentiment using Google Gemini.
- **Two-Way Telegram Bot:**
  - Receive automated 09:30 range locks, instant entry alerts, and target/stop hits.
  - Interactive commands: `/status`, `/ai_view`, `/balance`, `/journal`, `/close`.
- **Systemd Daemon:** Runs continuously in the background, automatically restarting on system reboots.

---

## 🚀 Step 1: Push Code to GitHub

Open Terminal on your Mac and run:

```bash
cd /Users/vamsi/.gemini/antigravity/scratch/india-trading-gcp

# 1. Initialize git
git init
git add .
git commit -m "feat: Initial commit for GCP autonomous trading daemon"

# 2. Add your GitHub remote (create a new private repo on github.com named 'india-trading-gcp')
git branch -M main
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/india-trading-gcp.git

# 3. Push to GitHub
git push -u origin main
```

---

## ☁️ Step 2: Create a Free-Tier VM on Google Cloud (GCP)

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Navigate to **Compute Engine** > **VM Instances**.
3. Click **Create Instance**:
   - **Name:** `trading-bot`
   - **Region:** `us-central1` (Iowa), `us-west1` (Oregon), or `asia-south1` (Mumbai) *(Note: `us-central1` qualifies for GCP Always Free Tier)*
   - **Machine Configuration:**
     - Series: **E2**
     - Machine type: **e2-micro** (2 vCPU, 1 GB memory — *Always Free Tier*)
   - **Boot Disk:** Change to **Ubuntu 24.04 LTS** (Standard persistent disk, 20 GB).
   - **Firewall:** Check *"Allow HTTPS traffic"*.
4. Click **Create**.

---

## 🔧 Step 3: 1-Click Installation on GCP VM

1. In the GCP VM Instances list, click the **SSH** button next to your `trading-bot` VM.
2. In the SSH terminal window, run:

```bash
# Clone your repository
git clone https://github.com/<YOUR_GITHUB_USERNAME>/india-trading-gcp.git
cd india-trading-gcp

# Run the automated 1-click installer
./setup_gcp_vm.sh
```

The script will automatically:
- Install Python 3, pip, and venv.
- Configure dependencies and environment settings.
- Register `trading.service` with Linux `systemd`.
- Start the bot daemon immediately!

---

## 📱 Step 4: Test & Control from Your Phone (Telegram)

Open your Telegram app, search for **`@vamsi_new_bot`**, and type:

- `/status` — Live NIFTY Spot, active trade status, and P&L.
- `/ai_view` — Ask the AI Hedge Fund Committee for live market analysis.
- `/balance` — Check your account balance.
- `/journal` — Review today's trade log.
- `/close` — Emergency square-off of open positions.

---

## 🛠️ Management Commands on GCP VM

```bash
# View live streaming daemon logs
sudo journalctl -u trading -f

# Check service status
sudo systemctl status trading

# Restart the bot
sudo systemctl restart trading

# Stop the bot
sudo systemctl stop trading
```
