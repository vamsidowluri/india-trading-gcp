#!/usr/bin/env python3
"""
Quantitative Trading Engine
Distilled from je-suis-tm/quant-trading:
- Dual Thrust Dynamic Breakout Model
- Options Straddle Volatility Model
- Average True Range (ATR) Dynamic Trailing Stop
- Heikin-Ashi Noise Reduction Filter
- Monte Carlo Risk & Drawdown Simulation (1,000 Iterations)
"""

import math
import random
from typing import Dict, Any, List, Tuple


# =====================================================================
# 1. Dual Thrust Dynamic Breakout Engine
# =====================================================================
def calculate_dual_thrust(
    open_price: float,
    high_history: List[float],
    low_history: List[float],
    close_history: List[float],
    k1: float = 0.5,
    k2: float = 0.5
) -> Dict[str, float]:
    """
    Dual Thrust Breakout Formula:
    Range = Max(HH - LC, HC - LL)
    Upper Band = Open + K1 * Range
    Lower Band = Open - K2 * Range
    """
    hh = max(high_history)
    hc = max(close_history)
    ll = min(low_history)
    lc = min(close_history)

    range_val = max(hh - lc, hc - ll)
    upper_band = open_price + (k1 * range_val)
    lower_band = open_price - (k2 * range_val)

    return {
        "range": round(range_val, 2),
        "upper_band": round(upper_band, 2),
        "lower_band": round(lower_band, 2),
        "buy_trigger": round(upper_band, 2),
        "sell_trigger": round(lower_band, 2)
    }


# =====================================================================
# 2. Options Straddle Volatility Model
# =====================================================================
def evaluate_straddle_setup(
    spot: float,
    call_premium: float,
    put_premium: float,
    expected_move_points: float
) -> Dict[str, Any]:
    """
    Evaluates an ATM Long Straddle setup (simultaneous CE + PE buy).
    Total Premium = Call + Put
    Break-Even Upside = Spot + Total Premium
    Break-Even Downside = Spot - Total Premium
    """
    total_cost = call_premium + put_premium
    be_upper = spot + total_cost
    be_lower = spot - total_cost
    profit_potential = expected_move_points - total_cost

    is_viable = expected_move_points > (total_cost * 1.35)

    return {
        "spot": spot,
        "call_premium": call_premium,
        "put_premium": put_premium,
        "total_straddle_premium": round(total_cost, 2),
        "breakeven_upper": round(be_upper, 2),
        "breakeven_lower": round(be_lower, 2),
        "expected_move": expected_move_points,
        "is_viable": is_viable,
        "verdict": "HIGH CONVICTION STRADDLE" if is_viable else "AVOID (Theta Decay Exceeds Edge)"
    }


# =====================================================================
# 3. Average True Range (ATR) Dynamic Trailing Stop
# =====================================================================
def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """
    Calculates 14-period Average True Range for dynamic volatility stops.
    """
    if len(closes) < 2:
        return 15.0

    tr_list = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i-1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    effective_period = min(period, len(tr_list))
    return round(sum(tr_list[-effective_period:]) / effective_period, 2)


# =====================================================================
# 4. Heikin-Ashi Trend Noise Filter
# =====================================================================
def compute_heikin_ashi_candle(
    prev_ha_open: float,
    prev_ha_close: float,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float
) -> Dict[str, float]:
    """
    Converts standard raw candles into Heikin-Ashi candles to filter market chop.
    HA_Close = (Open + High + Low + Close) / 4
    HA_Open = (Prev_HA_Open + Prev_HA_Close) / 2
    HA_High = Max(High, HA_Open, HA_Close)
    HA_Low = Min(Low, HA_Open, HA_Close)
    """
    ha_close = (open_p + high_p + low_p + close_p) / 4.0
    ha_open = (prev_ha_open + prev_ha_close) / 2.0
    ha_high = max(high_p, ha_open, ha_close)
    ha_low = min(low_p, ha_open, ha_close)

    is_bullish = ha_close > ha_open
    has_no_lower_wick = abs(ha_low - ha_open) < 0.5 # Strong bullish trend

    return {
        "ha_open": round(ha_open, 2),
        "ha_high": round(ha_high, 2),
        "ha_low": round(ha_low, 2),
        "ha_close": round(ha_close, 2),
        "is_bullish": is_bullish,
        "is_strong_trend": has_no_lower_wick
    }


# =====================================================================
# 5. Monte Carlo Risk & Drawdown Simulation (1,000 Runs)
# =====================================================================
def run_monte_carlo_simulation(
    starting_bankroll: float = 6640.0,
    win_rate: float = 0.45,
    win_reward_pts: float = 35.0,
    loss_risk_pts: float = 17.5,
    charges_per_trade: float = 55.0,
    lot_size: int = 25,
    sessions_to_simulate: int = 30,
    iterations: int = 1000
) -> Dict[str, Any]:
    """
    Monte Carlo simulation running 1,000 iterations over a 30-session trading month.
    Computes: Median Profit, Max Drawdown Risk, Probability of Milestone Success.
    """
    final_balances = []
    max_drawdowns = []

    for _ in range(iterations):
        balance = starting_bankroll
        peak = balance
        max_dd = 0.0

        for _ in range(sessions_to_simulate):
            is_win = random.random() < win_rate
            if is_win:
                pnl = (win_reward_pts * lot_size) - charges_per_trade
            else:
                pnl = (-loss_risk_pts * lot_size) - charges_per_trade

            balance += pnl
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak * 100.0
            if dd > max_dd:
                max_dd = dd

        final_balances.append(balance)
        max_drawdowns.append(max_dd)

    final_balances.sort()
    max_drawdowns.sort()

    median_balance = final_balances[int(iterations * 0.50)]
    p10_worst_case = final_balances[int(iterations * 0.10)]
    p90_best_case = final_balances[int(iterations * 0.90)]
    median_dd = max_drawdowns[int(iterations * 0.50)]
    worst_case_dd = max_drawdowns[int(iterations * 0.95)]
    prob_profitable = sum(1 for b in final_balances if b > starting_bankroll) / iterations * 100.0

    return {
        "starting_bankroll": starting_bankroll,
        "simulated_sessions": sessions_to_simulate,
        "iterations": iterations,
        "probability_of_profit": f"{prob_profitable:.1f}%",
        "median_ending_balance": round(median_balance, 2),
        "p10_conservative_balance": round(p10_worst_case, 2),
        "p90_aggressive_balance": round(p90_best_case, 2),
        "median_max_drawdown": f"{median_dd:.1f}%",
        "worst_case_95pct_drawdown": f"{worst_case_dd:.1f}%"
    }


if __name__ == "__main__":
    print("=" * 60)
    print("🔬 QUANT TRADING ENGINE (JE-SUIS-TM INTEGRATION TEST)")
    print("=" * 60)
    
    # 1. Dual Thrust Test
    dt = calculate_dual_thrust(25500.0, [25520, 25540, 25550], [25450, 25480, 25460], [25510, 25530, 25540])
    print(f"1. Dual Thrust Bounds: Buy > ₹{dt['upper_band']} | Sell < ₹{dt['lower_band']} (Range: {dt['range']} pts)")

    # 2. Options Straddle Test
    st = evaluate_straddle_setup(spot=305.0, call_premium=3.55, put_premium=3.60, expected_move_points=12.0)
    print(f"2. Straddle Model: Total Cost ₹{st['total_straddle_premium']} | Upper: ₹{st['breakeven_upper']} | Lower: ₹{st['breakeven_lower']}")
    print(f"   Verdict: {st['verdict']}")

    # 3. Monte Carlo Test
    mc = run_monte_carlo_simulation(starting_bankroll=6640.0, sessions_to_simulate=30, iterations=1000)
    print(f"3. Monte Carlo 1,000 Runs (30 Sessions):")
    print(f"   • Win Probability: {mc['probability_of_profit']}")
    print(f"   • Median Balance: ₹{mc['median_ending_balance']:,.2f}")
    print(f"   • Conservative (P10): ₹{mc['p10_conservative_balance']:,.2f}")
    print(f"   • Median Max Drawdown: {mc['median_max_drawdown']}")
    print("=" * 60)
