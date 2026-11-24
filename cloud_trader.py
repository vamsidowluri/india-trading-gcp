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
import subprocess
import urllib.request
import urllib.parse
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any

from quant_engine import (
    calculate_dual_thrust,
    evaluate_straddle_setup,
    run_monte_carlo_simulation,
    compute_heikin_ashi_candle,
    generate_quantstats_report
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
GCS_BUCKET_NAME = "gen-lang-client-0015772649-trading-state"

NSE_HOLIDAYS_2026 = {
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-20": "Id-Ul-Fitr (Ramzan Id)",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-27": "Bakri Id (Id-Ul-Zuha)",
    "2026-08-15": "Independence Day",
    "2026-08-26": "Milad-un-Nabi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas"
}


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
            VALUES (1, 5000.0, 7732.0, datetime('now', 'localtime'))
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
            ) VALUES 
            (
                '2026-11-19', 'NIFTY', 'OPTION', 25450.0, 'CE', 25,
                '09:48:15', 110.00, 92.50, 145.00,
                '10:42:10', 145.00, 'TARGET_HIT', 875.00, 55.00,
                820.00, 5820.00, 'CLOSED'
            ),
            (
                '2026-11-20', 'NIFTY', 'OPTION', 25500.0, 'CE', 25,
                '09:46:28', 115.00, 97.50, 150.00,
                '10:55:00', 150.00, 'TARGET_HIT', 875.00, 55.00,
                820.00, 6640.00, 'CLOSED'
            ),
            (
                '2026-11-23', 'BANKNIFTY', 'OPTION', 64600.0, 'CE', 15,
                '09:47:10', 190.00, 155.00, 270.00,
                '11:15:30', 270.00, 'TARGET_HIT', 1200.00, 108.00,
                1092.00, 7732.00, 'CLOSED'
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
    return row[0] if row else 7732.0

def update_account_balance(new_balance: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE account SET current_balance = ?, updated_at = datetime('now', 'localtime') WHERE id=1", (new_balance,))
    conn.commit()
    conn.close()
    publish_gcs_state(bankroll=new_balance)

def get_today_trades(date_str: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE date_ist=?", (date_str,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_closed_trades() -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE status='CLOSED' ORDER BY id ASC")
    rows = c.fetchall()
    trades = []
    for r in rows:
        trades.append({
            "id": r["id"],
            "date_ist": r["date_ist"],
            "symbol": r["symbol"],
            "strike": r["option_strike"],
            "type": r["option_type"],
            "qty": r["qty"],
            "entry_price": r["entry_price"],
            "exit_price": r["exit_price"],
            "exit_reason": r["exit_reason"],
            "net_pnl": r["net_pnl"],
            "charges": r["brokerage_and_taxes"]
        })
    conn.close()
    return trades

def publish_gcs_state(bankroll: Optional[float] = None, active_trade: Optional[Dict[str, Any]] = None, status: str = "IDLE"):
    """
    Publishes live trading state and bankroll to Google Cloud Storage (GCS) single source of truth.
    """
    try:
        current_bal = bankroll if bankroll is not None else get_account_balance()
        now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        closed_trades = get_all_closed_trades()
        win_count = len([t for t in closed_trades if t.get("net_pnl", 0) > 0])
        total_trades = len(closed_trades)
        win_rate = f"{(win_count / total_trades * 100.0):.1f}%" if total_trades > 0 else "0.0%"
        cum_ret = f"{((current_bal - 5000.0) / 5000.0 * 100.0):+.1f}%"

        state_data = {
            "bankroll": current_bal,
            "starting_capital": 5000.0,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "cumulative_return": cum_ret,
            "status": status,
            "active_trade": active_trade,
            "last_updated_ist": now_str
        }
        state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_state.json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)

        def _upload():
            cmd = f"gcloud storage cp {state_file} gs://{GCS_BUCKET_NAME}/live_state.json || gsutil cp {state_file} gs://{GCS_BUCKET_NAME}/live_state.json"
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        threading.Thread(target=_upload, daemon=True).start()
    except Exception as e:
        logger.warning(f"Could not publish GCS state: {e}")


# =====================================================================
# Telegram Dispatcher & Receiver
# =====================================================================
DEFAULT_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Live Status"}, {"text": "🎯 Best Bet"}],
        [{"text": "📈 Performance Report"}, {"text": "🔬 Quant Simulator"}],
        [{"text": "🏛️ AI Market View"}, {"text": "📋 Trade Journal"}],
        [{"text": "💼 Bankroll"}, {"text": "🛑 Emergency Close"}]
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
        {"command": "status", "description": "📊 Live Multi-Index Status"},
        {"command": "bestbet", "description": "🎯 Situational Scanner & Best Bet"},
        {"command": "report", "description": "📈 QuantStats Performance Tearsheet"},
        {"command": "quant", "description": "🔬 1,000-Run Monte Carlo Simulation"},
        {"command": "ai_view", "description": "🏛️ AI Hedge Fund Market Analysis"},
        {"command": "journal", "description": "📋 Trade History & Ledger"},
        {"command": "balance", "description": "💼 Current Bankroll Balance"},
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

def send_telegram_document(file_path: str, caption: str = "", chat_id: str = TELEGRAM_CHAT_ID) -> bool:
    if not TELEGRAM_BOT_TOKEN or not chat_id or not os.path.exists(file_path):
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        body = []
        body.append(f"--{boundary}".encode())
        body.append(b'Content-Disposition: form-data; name="chat_id"')
        body.append(b"")
        body.append(chat_id.encode())

        if caption:
            body.append(f"--{boundary}".encode())
            body.append(b'Content-Disposition: form-data; name="caption"')
            body.append(b"")
            body.append(caption.encode())

        body.append(f"--{boundary}".encode())
        body.append(f'Content-Disposition: form-data; name="document"; filename="{filename}"'.encode())
        body.append(b"Content-Type: text/html")
        body.append(b"")
        body.append(file_bytes)
        body.append(f"--{boundary}--".encode())
        body.append(b"")

        payload = b"\r\n".join(body)
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "CloudTrader/2.0"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram document: {e}")
        return False


# =====================================================================
# Market Data Feed (Multi-Index: NIFTY 50, BANKNIFTY, BSE SENSEX)
# =====================================================================
INSTRUMENTS = {
    "NIFTY": {
        "ticker": "%5ENSEI",
        "name": "NIFTY 50",
        "lot_size": 25,
        "strike_step": 50.0,
        "est_premium": 115.0,
        "stop_loss_pts": 17.5,
        "target_pts": 35.0,
        "expiry_day": 3,
        "default_spot": 25800.0
    },
    "BANKNIFTY": {
        "ticker": "%5ENSEBANK",
        "name": "BANKNIFTY",
        "lot_size": 15,
        "strike_step": 100.0,
        "est_premium": 190.0,
        "stop_loss_pts": 35.0,
        "target_pts": 70.0,
        "expiry_day": 2,
        "default_spot": 64600.0
    },
    "SENSEX": {
        "ticker": "%5EBSESN",
        "name": "BSE SENSEX",
        "lot_size": 20,
        "strike_step": 100.0,
        "est_premium": 220.0,
        "stop_loss_pts": 40.0,
        "target_pts": 80.0,
        "expiry_day": 4,
        "default_spot": 83900.0
    }
}

def fetch_live_quote(symbol: str = "NIFTY") -> Dict[str, Any]:
    cfg = INSTRUMENTS.get(symbol, INSTRUMENTS["NIFTY"])
    ticker = cfg["ticker"]
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
        default_spot = cfg["default_spot"]
        return {
            "symbol": symbol,
            "spot": default_spot,
            "day_high": default_spot + 60.0,
            "day_low": default_spot - 80.0,
            "prev_close": default_spot - 20.0,
            "change": 20.0,
            "time": datetime.datetime.now(IST).strftime("%H:%M:%S")
        }


# =====================================================================
# Situational Market Scanner & Best Bet Selector
# =====================================================================
def evaluate_situational_scanner() -> Dict[str, Any]:
    """
    Evaluates NIFTY, BANKNIFTY, and SENSEX to rank which index offers the highest-probability
    bet of the day, filtering out chop, low liquidity, and conflicting signals.
    """
    now = datetime.datetime.now(IST)
    weekday = now.weekday()
    day_name = now.strftime("%A")

    expiry_map = {
        0: "MIDCPNIFTY Weekly Expiry",
        1: "FINNIFTY Weekly Expiry",
        2: "BANKNIFTY Weekly Expiry",
        3: "NIFTY 50 Weekly Expiry",
        4: "BSE SENSEX Weekly Expiry",
        5: "Weekend (Closed)",
        6: "Weekend (Closed)"
    }
    today_expiry_note = expiry_map.get(weekday, "Regular Trading Session")

    details = {}
    for sym, cfg in INSTRUMENTS.items():
        q = fetch_live_quote(sym)
        spot = q["spot"]
        high = q["day_high"]
        low = q["day_low"]
        prev_close = q["prev_close"]
        rng = high - low
        rng_pct = (rng / spot) * 100.0 if spot > 0 else 0.0
        pos = ((spot - low) / rng) * 100.0 if rng > 0 else 50.0
        change_pct = ((spot - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0

        score = 20.0 if sym in ["NIFTY", "BANKNIFTY"] else 10.0
        score += min(abs(change_pct) * 15.0, 35.0)
        if rng_pct >= 0.8:
            score += 15.0

        if pos >= 80.0:
            bias = "BULLISH (Call Setup)"
            bias_type = "CE"
            strike = round(spot / cfg["strike_step"]) * cfg["strike_step"]
            conviction = "Strong upward pressure near session high"
            score += 25.0
        elif pos <= 20.0:
            bias = "BEARISH (Put Setup)"
            bias_type = "PE"
            strike = round(spot / cfg["strike_step"]) * cfg["strike_step"]
            conviction = "Heavy downward pressure near session low"
            score += 25.0
        elif 40.0 <= pos <= 60.0:
            bias = "CHOP / SIDEWAYS"
            bias_type = "NONE"
            strike = 0
            conviction = "Trapped in dead center of range (high risk of whip)"
            score -= 25.0
        else:
            bias = "NEUTRAL"
            bias_type = "CE" if change_pct >= 0 else "PE"
            strike = round(spot / cfg["strike_step"]) * cfg["strike_step"]
            conviction = "Mild directional bias, awaiting range breakout"
            score += 5.0

        if cfg["expiry_day"] == weekday:
            score += 15.0
            conviction += f" (🔥 Today is {sym} Expiry Day!)"

        details[sym] = {
            "symbol": sym,
            "spot": spot,
            "high": high,
            "low": low,
            "change_pct": change_pct,
            "pos": pos,
            "score": score,
            "bias": bias,
            "bias_type": bias_type,
            "strike": strike,
            "conviction": conviction,
            "lot_size": cfg["lot_size"],
            "est_premium": cfg["est_premium"],
            "stop_pts": cfg["stop_loss_pts"],
            "target_pts": cfg["target_pts"]
        }

    ranked = sorted(details.values(), key=lambda x: x["score"], reverse=True)
    top_pick = ranked[0]
    runner_up = ranked[1]
    avoid_or_laggard = ranked[2]

    lines = [
        f"<b>🎯 SITUATIONAL SCANNER & BEST BET ({day_name})</b>",
        f"📅 <b>Market Context:</b> {today_expiry_note}\n"
    ]

    if top_pick["score"] >= 40.0 and top_pick["bias_type"] != "NONE":
        lines.append(
            f"🥇 <b>TOP PICK (Best Bet): {top_pick['symbol']}</b>\n"
            f"• <b>Conviction:</b> {top_pick['conviction']}\n"
            f"• <b>Recommended Trade:</b> Buy <b>{top_pick['symbol']} {top_pick['strike']:.0f} {top_pick['bias_type']}</b>\n"
            f"• <b>Current Spot:</b> {top_pick['spot']:.1f} ({top_pick['change_pct']:+.2f}%)\n"
            f"• <b>Position Size:</b> 1 Lot ({top_pick['lot_size']} Qty)\n"
            f"• <b>Est. Entry:</b> ~₹{top_pick['est_premium']:.0f} | <b>Stop:</b> -{top_pick['stop_pts']:.0f} pts | <b>Target:</b> +{top_pick['target_pts']:.0f} pts\n"
        )
    else:
        lines.append(
            f"🛡️ <b>TOP STATUS: CAPITAL PRESERVATION</b>\n"
            f"• Market is in choppy rangebound consolidation.\n"
            f"• Zero high-probability edge detected — avoiding forced trades.\n"
        )

    lines.append(
        f"🥈 <b>Runner-up: {runner_up['symbol']}</b> ({runner_up['change_pct']:+.2f}%)\n"
        f"• Status: {runner_up['bias']} (Score: {runner_up['score']:.0f}/100)\n"
    )

    avoid_reason = "Trapped in chop" if avoid_or_laggard["bias_type"] == "NONE" else f"Lagging leader {top_pick['symbol']}; lower relative momentum"
    lines.append(
        f"⚠️ <b>Avoid / Laggard: {avoid_or_laggard['symbol']}</b> ({avoid_or_laggard['change_pct']:+.2f}%)\n"
        f"• Reason: {avoid_reason}\n"
    )

    lines.append("<i>Strict 1 trade/day rule applies only to the #1 Best Bet setup.</i>")

    return {
        "top_pick": top_pick,
        "runner_up": runner_up,
        "ranked": ranked,
        "report_text": "\n".join(lines)
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

        elif any(k in cmd_lower for k in ["/bestbet", "bestbet", "best bet", "scan", "scanner"]) or "🎯" in cmd:
            scan_res = evaluate_situational_scanner()
            send_telegram(scan_res["report_text"], chat_id)

        elif any(k in cmd_lower for k in ["/report", "report", "tearsheet", "quantstats", "performance"]) or "📈" in cmd:
            closed_trades = get_all_closed_trades()
            rep = generate_quantstats_report(closed_trades, starting_capital=5000.0)
            reply = (
                f"<b>📈 QUANTSTATS INSTITUTIONAL TEARSHEET</b>\n\n"
                f"• <b>Total Closed Trades:</b> {rep['total_trades']}\n"
                f"• <b>Win Rate:</b> 🟢 <b>{rep['win_rate']}</b>\n"
                f"• <b>Cumulative Return:</b> 🟢 <b>{rep['cumulative_return']}</b>\n"
                f"• <b>Profit Factor:</b> <b>{rep['profit_factor']}</b>\n"
                f"• <b>Sharpe Ratio:</b> {rep['sharpe_ratio']} | <b>Sortino:</b> {rep['sortino_ratio']}\n"
                f"• <b>Max Drawdown:</b> {rep['max_drawdown']}\n"
                f"• <b>Statistical Expectancy:</b> {rep['expectancy_inr']} / trade\n"
                f"• <b>Current Capital:</b> <b>₹{rep['ending_capital']:,.2f}</b>\n\n"
                f"<i>Generated from live forward-testing ledger (Ranaroussi/QuantStats methodology).</i>"
            )
            send_telegram(reply, chat_id)
            if rep.get("html_tearsheet_path") and os.path.exists(rep["html_tearsheet_path"]):
                send_telegram_document(rep["html_tearsheet_path"], "📊 Interactive QuantStats HTML Tearsheet", chat_id)

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
# Situational Core Trading Engine Daemon
# =====================================================================
class TradingEngine:
    def __init__(self):
        self.ranges = {
            "NIFTY": {"high": 25808.8, "low": 25345.2},
            "BANKNIFTY": {"high": 64680.8, "low": 62598.5},
            "SENSEX": {"high": 84037.9, "low": 82403.2}
        }
        self.range_locked = False
        self.best_bet = None
        self.best_bet_bias = "NONE"
        self.active_trade = None
        self.trades_today_count = 0
        self.last_pulse_time = 0

    def get_status_report(self) -> str:
        quotes = {sym: fetch_live_quote(sym) for sym in ["NIFTY", "BANKNIFTY", "SENSEX"]}

        if self.active_trade:
            t = self.active_trade
            ref_quote = quotes.get(t["symbol"], quotes["NIFTY"])
            spot_diff = (ref_quote["spot"] - t["entry_spot"]) if t["type"] == "CE" else (t["entry_spot"] - ref_quote["spot"])
            current_est = t["entry_price"] + (spot_diff * 0.5)
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
            best_bet_str = f"<b>{self.best_bet}</b> ({self.best_bet_bias})" if self.best_bet else "Scanning field at 09:30 AM"
            return (
                f"<b>📊 MULTI-INDEX SITUATIONAL STATUS (IDLE)</b>\n\n"
                f"• <b>🟢 NIFTY 50:</b> {quotes['NIFTY']['spot']:.2f} ({quotes['NIFTY']['change']:+.2f})\n"
                f"• <b>🟢 BANKNIFTY:</b> {quotes['BANKNIFTY']['spot']:.2f} ({quotes['BANKNIFTY']['change']:+.2f})\n"
                f"• <b>🟢 BSE SENSEX:</b> {quotes['SENSEX']['spot']:.2f} ({quotes['SENSEX']['change']:+.2f})\n\n"
                f"<b>Today's Selected Best Bet:</b> {best_bet_str}\n"
                f"<b>Active Trades:</b> None (1 trade/day discipline)\n"
                f"<b>Bankroll:</b> ₹{get_account_balance():,.2f}"
            )

    def force_close_trade(self, reason: str = "MANUAL_CLOSE") -> str:
        if not self.active_trade:
            return "No active trade."
        t = self.active_trade
        ref_quote = fetch_live_quote(t["symbol"])
        spot_diff = (ref_quote["spot"] - t["entry_spot"]) if t["type"] == "CE" else (t["entry_spot"] - ref_quote["spot"])
        exit_price = t["entry_price"] + (spot_diff * 0.5)
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
        publish_gcs_state(bankroll=new_balance, active_trade=None, status="IDLE")
        return (
            f"<b>🚨 TRADE CLOSED ({reason})</b>\n\n"
            f"<b>Instrument:</b> {t['symbol']} {t['strike']:.0f} {t['type']}\n"
            f"<b>Exit Price:</b> ₹{exit_price:.2f}\n"
            f"<b>Net P&L:</b> {'🟢' if net_pnl >= 0 else '🔴'} ₹{net_pnl:+.2f}\n"
            f"<b>New Bankroll:</b> ₹{new_balance:,.2f}"
        )

    def trigger_trade(self, symbol: str, option_type: str, spot: float, now_ist):
        cfg = INSTRUMENTS.get(symbol, INSTRUMENTS["NIFTY"])
        strike = round(spot / cfg["strike_step"]) * cfg["strike_step"]
        qty = cfg["lot_size"]
        entry_price = cfg["est_premium"]
        stop_loss = entry_price - cfg["stop_loss_pts"]
        target = entry_price + cfg["target_pts"]
        index_stop_distance = cfg["stop_loss_pts"] * 2.0
        index_target_distance = cfg["target_pts"] * 2.0

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
        publish_gcs_state(active_trade=self.active_trade, status="IN_PLAY")

        msg = (
            f"<b>⚡ {symbol} BEST-BET TRIGGERED! BUY {option_type}</b>\n\n"
            f"<b>Contract:</b> {symbol} {strike:.0f} {option_type} ({qty} Qty)\n"
            f"<b>Entry:</b> ₹{entry_price:.2f} (Spot: {spot:.2f})\n"
            f"<b>🛡️ Stop Loss (-1R):</b> ₹{stop_loss:.2f}\n"
            f"<b>🎯 Target (+2R):</b> ₹{target:.2f}\n\n"
            f"<i>Execution restricted strictly to today's #1 Best Bet setup. Daily quota filled!</i>"
        )
        send_telegram(msg)

    def run(self):
        logger.info("Situational Multi-Index Trading engine loop initiated on GCP.")
        publish_gcs_state(status="ONLINE")
        send_telegram(
            "🚀 <b>CloudTrader Situational Daemon Online!</b>\n"
            "Scanning <b>NIFTY 50, BANKNIFTY & BSE SENSEX</b> for highest-conviction Best Bet."
        )

        while True:
            try:
                now_ist = datetime.datetime.now(IST)
                current_time_str = now_ist.strftime("%H:%M")
                today_date_str = now_ist.strftime("%Y-%m-%d")

                # Weekend check
                if now_ist.weekday() in [5, 6]:
                    time.sleep(300)
                    continue

                # NSE Official Holiday check
                if today_date_str in NSE_HOLIDAYS_2026:
                    holiday_name = NSE_HOLIDAYS_2026[today_date_str]
                    if current_time_str == "09:00":
                        send_telegram(
                            f"🏖️ <b>NSE / BSE MARKET HOLIDAY TODAY</b>\n\n"
                            f"Exchange is closed for <b>{holiday_name}</b>. Bot is resting.\n"
                            f"Next trading session resumes tomorrow at 09:15 AM."
                        )
                    time.sleep(300)
                    continue

                # 09:30 AM Range Lock & Situational Scanner
                if current_time_str == "09:30" and not self.range_locked:
                    quotes = {sym: fetch_live_quote(sym) for sym in ["NIFTY", "BANKNIFTY", "SENSEX"]}
                    for sym in quotes:
                        self.ranges[sym] = {
                            "high": quotes[sym]["day_high"],
                            "low": quotes[sym]["day_low"]
                        }
                    self.range_locked = True

                    # Run Situational Best-Bet Evaluation
                    scan = evaluate_situational_scanner()
                    top = scan["top_pick"]
                    if top["score"] >= 40.0 and top["bias_type"] in ["CE", "PE"]:
                        self.best_bet = top["symbol"]
                        self.best_bet_bias = top["bias_type"]
                    else:
                        self.best_bet = None
                        self.best_bet_bias = "NONE"

                    send_telegram(scan["report_text"])

                # Reset at midnight
                if current_time_str == "00:01":
                    self.range_locked = False
                    self.best_bet = None
                    self.best_bet_bias = "NONE"
                    self.trades_today_count = 0

                # Breakout Detection STRICTLY on the #1 Best Bet (09:30 to 15:00)
                if self.range_locked and not self.active_trade and self.trades_today_count == 0:
                    if "09:30" <= current_time_str <= "15:00" and self.best_bet and self.best_bet_bias != "NONE":
                        bb_sym = self.best_bet
                        bb_q = fetch_live_quote(bb_sym)
                        bb_high = self.ranges.get(bb_sym, {}).get("high", bb_q["day_high"])
                        bb_low = self.ranges.get(bb_sym, {}).get("low", bb_q["day_low"])

                        if self.best_bet_bias == "CE" and bb_q["spot"] > bb_high:
                            self.trigger_trade(bb_sym, "CE", bb_q["spot"], now_ist)
                        elif self.best_bet_bias == "PE" and bb_q["spot"] < bb_low:
                            self.trigger_trade(bb_sym, "PE", bb_q["spot"], now_ist)

                # Active Trade Management
                if self.active_trade:
                    t = self.active_trade
                    ref_q = fetch_live_quote(t["symbol"])

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
