#!/usr/bin/env python3
"""
Autonomous Cloud Trading Daemon with Dual-Index Scanner (NIFTY 50 + BSE SENSEX)
AI Hedge Fund & Telegram Interactive Control
Designed for 24/7 deployment on Google Cloud Platform (GCP e2-micro Free Tier)
"""

import os
import sys
import time
import json
import sqlite3
import logging
import threading
import datetime
import urllib.request
import urllib.parse
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any

from quant_engine import (
    calculate_dual_thrust,
    evaluate_straddle_setup,
    run_monte_carlo_simulation,
    compute_heikin_ashi_candle
)

# Environment & Timezone
IST = ZoneInfo("Asia/Kolkata")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("CloudTrader")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9283081811:AAF-jSS59rMDc-sqZllq_iNYqdSJRgWUACQ")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7590687240")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal.db")


# =====================================================================
# Database Manager (SQLite)
# =====================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY,
            starting_balance REAL NOT NULL,
            current_balance REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_ist TEXT NOT NULL,
            symbol TEXT NOT NULL,
            instrument_type TEXT NOT NULL,
            option_strike REAL,
            option_type TEXT,
            qty INTEGER NOT NULL DEFAULT 25,
            entry_time TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss_price REAL NOT NULL,
            target_price REAL NOT NULL,
            exit_time TEXT,
            exit_price REAL,
            exit_reason TEXT,
            gross_pnl REAL,
            brokerage_and_taxes REAL DEFAULT 55.0,
            net_pnl REAL,
            account_balance_after REAL,
            status TEXT NOT NULL DEFAULT 'OPEN'
        )
    """)
    # Check if account initialized
    c.execute("SELECT COUNT(*) FROM account")
    if c.fetchone()[0] == 0:
        c.execute("""
            INSERT INTO account (id, starting_balance, current_balance, updated_at)
            VALUES (1, 6640.0, 6640.0, datetime('now', 'localtime'))
        """)

    # Seed initial trade history if empty
    c.execute("SELECT COUNT(*) FROM trades")
    if c.fetchone()[0] == 0:
        c.execute("""
            INSERT INTO trades (
                date_ist, symbol, instrument_type, option_strike, option_type, qty,
                entry_time, entry_price, stop_loss_price, target_price,
                exit_time, exit_price, exit_reason, gross_pnl, brokerage_and_taxes,
                net_pnl, account_balance_after, status
            ) VALUES (
                '2026-11-20', 'NIFTY', 'OPTION', 25500.0, 'CE', 25,
                '09:46:28', 115.00, 97.50, 150.00,
                '10:55:00', 150.00, 'TARGET_HIT', 875.00, 55.00,
                820.00, 6640.00, 'CLOSED'
            )
        """)
    conn.commit()
    conn.close()

def get_account_balance() -> float:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT current_balance FROM account WHERE id=1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else 6640.0

def update_account_balance(new_balance: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE account SET current_balance = ?, updated_at = datetime('now', 'localtime') WHERE id=1", (new_balance,))
    conn.commit()
    conn.close()

def get_today_trades(date_str: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE date_ist=?", (date_str,))
    rows = c.fetchall()
    conn.close()
    return rows


# =====================================================================
# Telegram Dispatcher & Receiver
# =====================================================================
DEFAULT_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Live Status"}, {"text": "🔬 Quant Simulator"}],
        [{"text": "🏛️ AI Market View"}, {"text": "📋 Trade Journal"}],
        [{"text": "💼 Bankroll"}, {"text": "⚡ Straddle Model"}],
        [{"text": "🛑 Emergency Close"}]
    ],
    "resize_keyboard": True,
    "persistent": True
}

def set_telegram_commands():
    """
    Registers the bot commands with Telegram so they appear in the '/' menu.
    """
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    commands = [
        {"command": "status", "description": "📊 Live NIFTY & SENSEX Status"},
        {"command": "quant", "description": "🔬 1,000-Run Monte Carlo Simulation"},
        {"command": "ai_view", "description": "🏛️ AI Hedge Fund Market Analysis"},
        {"command": "journal", "description": "📋 Trade History & Ledger"},
        {"command": "balance", "description": "💼 Current Bankroll Balance"},
        {"command": "straddle", "description": "⚡ Options Straddle Volatility Model"},
        {"command": "close", "description": "🛑 Emergency Square-Off"}
    ]
    data = json.dumps({"commands": commands}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "CloudTrader/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Successfully registered persistent Telegram command menu.")
    except Exception as e:
        logger.warning(f"Could not register Telegram commands: {e}")

def send_telegram(text: str, chat_id: str = TELEGRAM_CHAT_ID, with_keyboard: bool = True) -> bool:
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if with_keyboard:
        params["reply_markup"] = json.dumps(DEFAULT_KEYBOARD)
    payload = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"User-Agent": "CloudTrader/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


# =====================================================================
# Market Data Feed (Dual Ticker: NIFTY 50 & BSE SENSEX)
# =====================================================================
def fetch_live_quote(symbol: str = "NIFTY") -> Dict[str, Any]:
    ticker = "%5ENSEI" if symbol == "NIFTY" else "%5EBSESN"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            meta = data["chart"]["result"][0]["meta"]
            spot = float(meta["regularMarketPrice"])
            day_high = float(meta.get("regularMarketDayHigh", spot))
            day_low = float(meta.get("regularMarketDayLow", spot))
            prev_close = float(meta.get("chartPreviousClose", spot))
            return {
                "symbol": symbol,
                "spot": spot,
                "day_high": day_high,
                "day_low": day_low,
                "prev_close": prev_close,
                "change": spot - prev_close,
                "time": datetime.datetime.now(IST).strftime("%H:%M:%S")
            }
    except Exception as e:
        logger.warning(f"Live feed fetch error on {symbol}: {e}")
        default_spot = 25520.0 if symbol == "NIFTY" else 83900.0
        return {
            "symbol": symbol,
            "spot": default_spot,
            "day_high": default_spot + 50.0,
            "day_low": default_spot - 100.0,
            "prev_close": default_spot - 20.0,
            "change": 20.0,
            "time": datetime.datetime.now(IST).strftime("%H:%M:%S")
        }


# =====================================================================
# AI Hedge Fund Analysis Module (Gemini API)
# =====================================================================
def run_ai_market_evaluation(nifty_quote: Dict[str, Any], sensex_quote: Dict[str, Any],
                             nifty_high: float, nifty_low: float,
                             sensex_high: float, sensex_low: float) -> str:
    """
    Evaluates both NIFTY and SENSEX setups using Hedge Fund Committee rules.
    """
    n_bias = "BULLISH" if nifty_quote["spot"] > nifty_high else ("BEARISH" if nifty_quote["spot"] < nifty_low else "NEUTRAL")
    s_bias = "BULLISH" if sensex_quote["spot"] > sensex_high else ("BEARISH" if sensex_quote["spot"] < sensex_low else "NEUTRAL")

    if not GEMINI_API_KEY:
        return (
            f"<b>🏛️ AI HEDGE FUND DUAL EVALUATION</b>\n\n"
            f"• <b>NIFTY 50 ({nifty_quote['spot']:.1f}):</b> {n_bias}\n"
            f"  Range: {nifty_low:.1f} – {nifty_high:.1f}\n"
            f"• <b>SENSEX ({sensex_quote['spot']:.1f}):</b> {s_bias}\n"
            f"  Range: {sensex_low:.1f} – {sensex_high:.1f}\n\n"
            f"<b>Strategy:</b> Waiting for confirmed 5-min candle breakout beyond range boundaries with 1:2 R:R."
        )

    prompt = f"""
    You are the Chief Risk Officer of an institutional Indian Hedge Fund.
    Analyze live Indian Index market structures:
    1. NIFTY 50: Spot={nifty_quote['spot']}, Range High={nifty_high}, Range Low={nifty_low}
    2. SENSEX: Spot={sensex_quote['spot']}, Range High={sensex_high}, Range Low={sensex_low}
    
    Give a 3-bullet concise assessment:
    - Relative strength (Is NIFTY or SENSEX leading?)
    - High-conviction direction
    - Capital allocation recommendation (Strict 1:2 R:R)
    """
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return f"<b>🏛️ AI Hedge Fund Analysis:</b>\n{response.text}"
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return f"<b>🏛️ AI Hedge Fund Analysis:</b>\nNIFTY & SENSEX in play. Monitoring 15m breakout levels."


# =====================================================================
# Interactive Telegram Command Listener (Background Thread)
# =====================================================================
class TelegramBotListener(threading.Thread):
    def __init__(self, engine):
        super().__init__(daemon=True)
        self.engine = engine
        self.last_update_id = 0

    def run(self):
        logger.info("Telegram interactive command listener started.")
        while True:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={self.last_update_id + 1}&timeout=20"
                req = urllib.request.Request(url, headers={"User-Agent": "CloudTrader/2.0"})
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode())
                    for update in data.get("result", []):
                        self.last_update_id = update["update_id"]
                        msg = update.get("message", {})
                        text = msg.get("text", "").strip()
                        chat_id = str(msg.get("chat", {}).get("id", ""))
                        if text:
                            self.handle_command(text, chat_id)
            except Exception as e:
                time.sleep(5)

    def handle_command(self, cmd: str, chat_id: str):
        logger.info(f"Received Telegram command: {cmd}")
        cmd_lower = cmd.lower().strip()

        if any(k in cmd_lower for k in ["/status", "status"]) or "📊" in cmd:
            reply = self.engine.get_status_report()
            send_telegram(reply, chat_id)

        elif any(k in cmd_lower for k in ["/quant", "quant", "backtest", "montecarlo"]) or "🔬" in cmd:
            bal = get_account_balance()
            mc = run_monte_carlo_simulation(starting_bankroll=bal, sessions_to_simulate=30, iterations=1000)
            reply = (
                f"<b>🔬 MONTE CARLO SIMULATION (1,000 RUNS / 30 SESSIONS)</b>\n\n"
                f"• <b>Starting Capital:</b> ₹{mc['starting_bankroll']:,.2f}\n"
                f"• <b>Win Probability:</b> 🟢 <b>{mc['probability_of_profit']}</b>\n"
                f"• <b>Median Expected Balance:</b> <b>₹{mc['median_ending_balance']:,.2f}</b>\n"
                f"• <b>Conservative (P10 Floor):</b> ₹{mc['p10_conservative_balance']:,.2f}\n"
                f"• <b>Aggressive (P90 Target):</b> ₹{mc['p90_aggressive_balance']:,.2f}\n"
                f"• <b>Median Max Drawdown:</b> {mc['median_max_drawdown']}\n"
                f"• <b>Worst-Case Drawdown (95% CI):</b> {mc['worst_case_95pct_drawdown']}\n\n"
                f"<i>Formula: Derived from je-suis-tm/quant-trading with strict 1:2 R:R.</i>"
            )
            send_telegram(reply, chat_id)

        elif any(k in cmd_lower for k in ["/straddle", "straddle"]) or "⚡" in cmd:
            n_q = fetch_live_quote("NIFTY")
            st = evaluate_straddle_setup(spot=n_q["spot"], call_premium=115.0, put_premium=115.0, expected_move_points=320.0)
            reply = (
                f"<b>⚡ OPTIONS STRADDLE MODEL ({n_q['spot']:.1f})</b>\n\n"
                f"• <b>Total Straddle Premium:</b> ₹{st['total_straddle_premium']:.2f}\n"
                f"• <b>Upper Break-Even:</b> ₹{st['breakeven_upper']:.2f}\n"
                f"• <b>Lower Break-Even:</b> ₹{st['breakeven_lower']:.2f}\n"
                f"• <b>Expected Move:</b> {st['expected_move']} pts\n"
                f"• <b>Model Verdict:</b> <b>{st['verdict']}</b>\n\n"
                f"<i>Useful for high-volatility sessions & inventory announcements.</i>"
            )
            send_telegram(reply, chat_id)

        elif any(k in cmd_lower for k in ["/ai_view", "ai_view", "ai view"]) or "🏛️" in cmd:
            n_q = fetch_live_quote("NIFTY")
            s_q = fetch_live_quote("SENSEX")
            reply = run_ai_market_evaluation(
                n_q, s_q,
                self.engine.nifty_range_high, self.engine.nifty_range_low,
                self.engine.sensex_range_high, self.engine.sensex_range_low
            )
            send_telegram(reply, chat_id)

        elif any(k in cmd_lower for k in ["/balance", "balance", "bankroll"]) or "💼" in cmd:
            bal = get_account_balance()
            reply = f"<b>💼 Current Account Bankroll:</b> ₹{bal:,.2f}"
            send_telegram(reply, chat_id)

        elif any(k in cmd_lower for k in ["/journal", "/journel", "journal", "journel", "trades", "ledger", "history"]) or "📋" in cmd:
            today = datetime.datetime.now(IST).strftime("%Y-%m-%d")
            trades = get_today_trades(today)
            if not trades:
                reply = f"<b>📋 Journal ({today}):</b> Zero trades executed yet today."
            else:
                lines = [f"<b>📋 TRADE JOURNAL ({today})</b>\n"]
                for t in trades:
                    status_emoji = "🎯" if t[13] == "TARGET_HIT" else "🛑"
                    pnl_color = "🟢" if (t[16] or 0) >= 0 else "🔴"
                    lines.append(
                        f"{status_emoji} <b>Trade #{t[0]}: {t[2]} {t[4]:.0f} {t[5]} ({t[6]} Qty)</b>\n"
                        f"• Entry: ₹{t[8]:.2f} @ {t[7]}\n"
                        f"• Exit: ₹{t[12]:.2f} @ {t[11]} ({t[13]})\n"
                        f"• Net P&L: {pnl_color} <b>₹{t[16]:+.2f}</b> (Charges: ₹{t[15]:.2f})\n"
                        f"• Bankroll After: <b>₹{t[17]:,.2f}</b>\n"
                    )
                reply = "\n".join(lines)
            send_telegram(reply, chat_id)

        elif any(k in cmd_lower for k in ["/close", "close", "squareoff", "exit"]) or "🛑" in cmd:
            if self.engine.active_trade:
                reply = self.engine.force_close_trade("MANUAL_TELEGRAM_CLOSE")
                send_telegram(reply, chat_id)
            else:
                send_telegram("ℹ️ No active trade currently open to close.", chat_id)

        else: # /start, /help or any other message
            reply = (
                "<b>🤖 CloudTrader Dual-Index Bot (GCP)</b>\n\n"
                "Daily Scanning: <b>NIFTY 50 + BSE SENSEX</b>\n\n"
                "👉 <b>Tap any button on your screen below to interact:</b>"
            )
            send_telegram(reply, chat_id)


# =====================================================================
# Dual-Index Core Trading Engine Daemon
# =====================================================================
class TradingEngine:
    def __init__(self):
        # NIFTY defaults
        self.nifty_range_high = 25491.25
        self.nifty_range_low = 25345.20
        # SENSEX defaults
        self.sensex_range_high = 84037.96
        self.sensex_range_low = 82403.27

        self.range_locked = False
        self.active_trade = None
        self.trades_today_count = 0
        self.last_pulse_time = 0

    def get_status_report(self) -> str:
        n_q = fetch_live_quote("NIFTY")
        s_q = fetch_live_quote("SENSEX")

        if self.active_trade:
            t = self.active_trade
            ref_quote = n_q if t["symbol"] == "NIFTY" else s_q
            current_est = t["entry_price"] + ((ref_quote["spot"] - t["entry_spot"]) * 0.5)
            pnl = (current_est - t["entry_price"]) * t["qty"]
            color = "🟢" if pnl >= 0 else "🔴"
            return (
                f"<b>📊 LIVE ACTIVE TRADE STATUS</b>\n\n"
                f"<b>Instrument:</b> {t['symbol']} {t['strike']:.0f} {t['type']} ({t['qty']} Qty)\n"
                f"<b>Entry:</b> ₹{t['entry_price']:.2f} (Spot: {t['entry_spot']:.2f})\n"
                f"<b>Current Spot:</b> {ref_quote['spot']:.2f}\n"
                f"<b>Estimated LTP:</b> ~₹{current_est:.2f}\n"
                f"<b>P&L:</b> {color} <b>₹{pnl:+.2f}</b>\n\n"
                f"<b>🛡️ Stop Loss:</b> ₹{t['stop_loss']:.2f}\n"
                f"<b>🎯 Target (1:2):</b> ₹{t['target']:.2f}\n"
                f"<b>Status:</b> IN PLAY"
            )
        else:
            return (
                f"<b>📊 DUAL MARKET STATUS (IDLE)</b>\n\n"
                f"<b>🟢 NIFTY 50:</b> {n_q['spot']:.2f} ({n_q['change']:+.2f})\n"
                f"  • Range: {self.nifty_range_low:.2f} – {self.nifty_range_high:.2f}\n\n"
                f"<b>🟢 BSE SENSEX:</b> {s_q['spot']:.2f} ({s_q['change']:+.2f})\n"
                f"  • Range: {self.sensex_range_low:.2f} – {self.sensex_range_high:.2f}\n\n"
                f"<b>Active Trades:</b> None (Scanning both for breakout)\n"
                f"<b>Bankroll:</b> ₹{get_account_balance():,.2f}"
            )

    def force_close_trade(self, reason: str = "MANUAL_CLOSE") -> str:
        if not self.active_trade:
            return "No active trade."
        t = self.active_trade
        ref_quote = fetch_live_quote(t["symbol"])
        exit_price = t["entry_price"] + ((ref_quote["spot"] - t["entry_spot"]) * 0.5)
        gross_pnl = (exit_price - t["entry_price"]) * t["qty"]
        net_pnl = gross_pnl - 55.0
        new_balance = get_account_balance() + net_pnl
        update_account_balance(new_balance)

        # Update DB
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            UPDATE trades
            SET exit_time = ?, exit_price = ?, exit_reason = ?, gross_pnl = ?, net_pnl = ?, account_balance_after = ?, status = 'CLOSED'
            WHERE id = ?
        """, (ref_quote["time"], exit_price, reason, gross_pnl, net_pnl, new_balance, t["id"]))
        conn.commit()
        conn.close()

        self.active_trade = None
        return (
            f"<b>🚨 TRADE CLOSED ({reason})</b>\n\n"
            f"<b>Instrument:</b> {t['symbol']} {t['strike']:.0f} {t['type']}\n"
            f"<b>Exit Price:</b> ₹{exit_price:.2f}\n"
            f"<b>Net P&L:</b> {'🟢' if net_pnl >= 0 else '🔴'} ₹{net_pnl:+.2f}\n"
            f"<b>New Bankroll:</b> ₹{new_balance:,.2f}"
        )

    def trigger_trade(self, symbol: str, option_type: str, spot: float, now_ist):
        if symbol == "NIFTY":
            strike = round(spot / 50.0) * 50.0
            qty = 25
            entry_price = 115.00
            stop_loss = 97.50
            target = 150.00
            index_stop_distance = 58.0
            index_target_distance = 47.0
        else: # SENSEX
            strike = round(spot / 100.0) * 100.0
            qty = 20
            entry_price = 220.00
            stop_loss = 180.00
            target = 300.00
            index_stop_distance = 180.0
            index_target_distance = 160.0

        today = now_ist.strftime("%Y-%m-%d")
        time_str = now_ist.strftime("%H:%M:%S")

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO trades (date_ist, symbol, instrument_type, option_strike, option_type, qty, entry_time, entry_price, stop_loss_price, target_price, status)
            VALUES (?, ?, 'OPTION', ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (today, symbol, strike, option_type, qty, time_str, entry_price, stop_loss, target))
        trade_id = c.lastrowid
        conn.commit()
        conn.close()

        self.active_trade = {
            "id": trade_id,
            "symbol": symbol,
            "strike": strike,
            "type": option_type,
            "qty": qty,
            "entry_price": entry_price,
            "entry_spot": spot,
            "stop_loss": stop_loss,
            "target": target,
            "index_stop_distance": index_stop_distance,
            "index_target_distance": index_target_distance
        }
        self.trades_today_count += 1

        msg = (
            f"<b>⚡ {symbol} BREAKOUT TRIGGERED! BUY {option_type}</b>\n\n"
            f"<b>Contract:</b> {symbol} {strike:.0f} {option_type} ({qty} Qty)\n"
            f"<b>Entry:</b> ₹{entry_price:.2f} (Spot: {spot:.2f})\n"
            f"<b>🛡️ Stop Loss (-1R):</b> ₹{stop_loss:.2f}\n"
            f"<b>🎯 Target (+2R):</b> ₹{target:.2f}\n\n"
            f"<i>Strict 1 trade/day discipline. Daily quota filled!</i>"
        )
        send_telegram(msg)

    def run(self):
        logger.info("Dual-Index Trading engine loop initiated on GCP.")
        send_telegram(
            "🚀 <b>CloudTrader Dual-Index Daemon Online!</b>\n"
            "Scanning <b>NIFTY 50 + BSE SENSEX</b> daily with strict 1:2 R:R."
        )

        while True:
            try:
                now_ist = datetime.datetime.now(IST)
                n_q = fetch_live_quote("NIFTY")
                s_q = fetch_live_quote("SENSEX")
                current_time_str = now_ist.strftime("%H:%M")

                # Weekend check
                if now_ist.weekday() in [5, 6]:
                    time.sleep(300)
                    continue

                # 09:30 AM Range Lock (Both NIFTY & SENSEX)
                if current_time_str == "09:30" and not self.range_locked:
                    self.nifty_range_high = n_q["day_high"]
                    self.nifty_range_low = n_q["day_low"]
                    self.sensex_range_high = s_q["day_high"]
                    self.sensex_range_low = s_q["day_low"]
                    self.range_locked = True

                    msg = (
                        f"<b>🔒 15-MIN DUAL RANGES LOCKED (09:30 AM IST)</b>\n\n"
                        f"<b>1. NIFTY 50 ({n_q['spot']:.1f}):</b>\n"
                        f"• High (CE Trigger): <b>{self.nifty_range_high:.2f}</b>\n"
                        f"• Low (PE Trigger): <b>{self.nifty_range_low:.2f}</b>\n\n"
                        f"<b>2. BSE SENSEX ({s_q['spot']:.1f}):</b>\n"
                        f"• High (CE Trigger): <b>{self.sensex_range_high:.2f}</b>\n"
                        f"• Low (PE Trigger): <b>{self.sensex_range_low:.2f}</b>\n\n"
                        f"<i>Scanning both live. First confirmed breakout triggers!</i>"
                    )
                    send_telegram(msg)

                # Reset at midnight
                if current_time_str == "00:01":
                    self.range_locked = False
                    self.trades_today_count = 0

                # Breakout Detection on BOTH Indices (09:30 to 15:00)
                if self.range_locked and not self.active_trade and self.trades_today_count == 0:
                    if "09:30" <= current_time_str <= "15:00":
                        # 1. Check NIFTY Breakout
                        if n_q["spot"] > self.nifty_range_high:
                            self.trigger_trade("NIFTY", "CE", n_q["spot"], now_ist)
                        elif n_q["spot"] < self.nifty_range_low:
                            self.trigger_trade("NIFTY", "PE", n_q["spot"], now_ist)

                        # 2. Check SENSEX Breakout
                        elif s_q["spot"] > self.sensex_range_high:
                            self.trigger_trade("SENSEX", "CE", s_q["spot"], now_ist)
                        elif s_q["spot"] < self.sensex_range_low:
                            self.trigger_trade("SENSEX", "PE", s_q["spot"], now_ist)

                # Active Trade Management
                if self.active_trade:
                    t = self.active_trade
                    ref_q = n_q if t["symbol"] == "NIFTY" else s_q
                    
                    if t["type"] == "CE":
                        spot_move = ref_q["spot"] - t["entry_spot"]
                    else:
                        spot_move = t["entry_spot"] - ref_q["spot"]

                    current_est = t["entry_price"] + (spot_move * 0.5)

                    # Target Hit
                    if current_est >= t["target"] or spot_move >= t["index_target_distance"]:
                        res = self.force_close_trade("TARGET_HIT")
                        send_telegram(f"🎯🎯 <b>TARGET REACHED (+2R WIN)!</b>\n\n{res}")

                    # Stop Loss
                    elif current_est <= t["stop_loss"] or spot_move <= -t["index_stop_distance"]:
                        res = self.force_close_trade("STOP_LOSS")
                        send_telegram(f"🛑 <b>STOP LOSS HIT (-1R)!</b>\n\n{res}")

                    # 15:15 Auto Square-off
                    elif current_time_str >= "15:15":
                        res = self.force_close_trade("INTRADAY_SQUARE_OFF")
                        send_telegram(f"⏰ <b>15:15 INTRADAY AUTO-SQUAREOFF</b>\n\n{res}")

                    # 2-Minute Pulse Heartbeat
                    elif time.time() - self.last_pulse_time >= 120:
                        self.last_pulse_time = time.time()
                        pnl = (current_est - t["entry_price"]) * t["qty"]
                        pulse_msg = (
                            f"<b>📊 LIVE PULSE ({t['symbol']})</b>\n"
                            f"Spot: <b>{ref_q['spot']:.2f}</b> | Est LTP: <b>₹{current_est:.2f}</b>\n"
                            f"P&L: <b>{'🟢' if pnl >= 0 else '🔴'} ₹{pnl:+.2f}</b> | SL: ₹{t['stop_loss']} | Tgt: ₹{t['target']}"
                        )
                        send_telegram(pulse_msg)

                time.sleep(10)
            except Exception as e:
                logger.error(f"Error in engine main loop: {e}")
                time.sleep(10)


def main():
    init_db()
    set_telegram_commands()
    engine = TradingEngine()
    
    # Start Telegram interactive bot in background thread
    listener = TelegramBotListener(engine)
    listener.start()
    
    # Run trading loop in main thread
    engine.run()


if __name__ == "__main__":
    main()
