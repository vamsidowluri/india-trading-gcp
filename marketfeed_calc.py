#!/usr/bin/env python3
"""
Marketfeed Telugu Quantitative Toolkit
Implements:
1. 1-2% Position Sizer & 50-25-25 Pyramiding Tranche Builder
2. VCP (Volume Contraction Pattern) Mathematical Filter
3. Open = High / Open = Low Intraday Qualifier
"""

import sys
import argparse
from typing import Dict, Any, List

def calculate_position_and_pyramid(capital: float, risk_pct: float, entry: float, stop_loss: float) -> Dict[str, Any]:
    """
    Calculates exact share count using Marketfeed's 1-2% risk rule
    and splits it into the 50-25-25 pyramiding structure.
    """
    if stop_loss >= entry:
        raise ValueError("Stop loss must be below entry price for long positions.")
    
    risk_rupees = capital * (risk_pct / 100.0)
    risk_per_share = entry - stop_loss
    total_qty = int(risk_rupees / risk_per_share)
    total_capital_required = total_qty * entry

    # 50-25-25 Tranches
    t1_qty = int(total_qty * 0.50)
    t2_qty = int(total_qty * 0.25)
    t3_qty = total_qty - (t1_qty + t2_qty)

    t2_add_price = round(entry * 1.035, 2) # +3.5% advance
    t3_add_price = round(entry * 1.075, 2) # +7.5% advance

    avg_price_after_t2 = round(((t1_qty * entry) + (t2_qty * t2_add_price)) / (t1_qty + t2_qty), 2)

    return {
        "capital": capital,
        "risk_budget_rupees": risk_rupees,
        "risk_per_share": risk_per_share,
        "total_shares": total_qty,
        "total_investment": total_capital_required,
        "tranche_1_pilot": {
            "percentage": "50%",
            "shares": t1_qty,
            "entry_price": entry,
            "cost": t1_qty * entry,
            "stop_loss": stop_loss
        },
        "tranche_2_confirmation": {
            "percentage": "25%",
            "shares": t2_qty,
            "entry_price": t2_add_price,
            "cost": t2_qty * t2_add_price,
            "rule": f"Move ALL stops to breakeven (avg: ₹{avg_price_after_t2:.2f})"
        },
        "tranche_3_expansion": {
            "percentage": "25%",
            "shares": t3_qty,
            "entry_price": t3_add_price,
            "cost": t3_qty * t3_add_price,
            "rule": "Trail stop below 20 EMA or recent swing low"
        }
    }

def verify_vcp_contractions(depths: List[float], volumes: List[float]) -> Dict[str, Any]:
    """
    Validates if price contractions and volume profile match the VCP framework.
    """
    is_price_contracting = all(depths[i] < depths[i-1] for i in range(1, len(depths)))
    is_volume_drying = all(volumes[i] < volumes[i-1] for i in range(1, len(volumes)))
    
    score = 0
    if is_price_contracting: score += 50
    if is_volume_drying: score += 50
    
    return {
        "depths": depths,
        "volumes": volumes,
        "is_price_contracting": is_price_contracting,
        "is_volume_drying": is_volume_drying,
        "vcp_quality_score": f"{score}/100",
        "verdict": "VALID VCP SETUP" if score == 100 else "IMPERFECT CONTRACTION"
    }

def check_open_high_low(open_p: float, high_p: float, low_p: float, current_p: float) -> str:
    """
    Determines Open=High or Open=Low intent in opening 15m.
    """
    tolerance = 0.0005 # 0.05%
    if abs(open_p - low_p) / open_p <= tolerance:
        return f"🟢 OPEN = LOW DETECTED (Open: {open_p}, Low: {low_p}). Strong Bullish Institutional Bidding. Focus on LONG / CE."
    elif abs(open_p - high_p) / open_p <= tolerance:
        return f"🔴 OPEN = HIGH DETECTED (Open: {open_p}, High: {high_p}). Strong Bearish Institutional Distribution. Focus on SHORT / PE."
    else:
        return f"⚪ NEUTRAL OPEN (Open: {open_p}, High: {high_p}, Low: {low_p}). Wait for 15-minute range breakout."

def main():
    parser = argparse.ArgumentParser(description="Marketfeed Telugu Trading Calculator")
    parser.add_argument("--capital", type=float, default=100000.0, help="Total Trading Capital in Rupees")
    parser.add_argument("--risk", type=float, default=1.5, help="Risk Percentage per trade (1.0 to 2.0 pct)")
    parser.add_argument("--entry", type=float, default=500.0, help="Entry Price (₹)")
    parser.add_argument("--stop", type=float, default=485.0, help="Stop Loss Price (₹)")
    args = parser.parse_args()

    plan = calculate_position_and_pyramid(args.capital, args.risk, args.entry, args.stop)
    print("=" * 60)
    print("🏛️ MARKETFEED TELUGU: 1-2% SIZING & 50-25-25 PYRAMIDING PLAN")
    print("=" * 60)
    print(f"Total Capital: ₹{plan['capital']:,.2f} | Risk Budget ({args.risk}%): ₹{plan['risk_budget_rupees']:,.2f}")
    print(f"Entry: ₹{args.entry:.2f} | Stop Loss: ₹{args.stop:.2f} (Risk/Share: ₹{plan['risk_per_share']:.2f})")
    print(f"Maximum Total Allocation: {plan['total_shares']} Shares (₹{plan['total_investment']:,.2f})\n")
    print("--- PYRAMID EXECUTION STAGES ---")
    print(f"1. Tranche 1 (50% Pilot): {plan['tranche_1_pilot']['shares']} shares @ ₹{plan['tranche_1_pilot']['entry_price']:.2f} | Stop: ₹{plan['tranche_1_pilot']['stop_loss']:.2f}")
    print(f"2. Tranche 2 (25% Add):   {plan['tranche_2_confirmation']['shares']} shares @ ₹{plan['tranche_2_confirmation']['entry_price']:.2f} | {plan['tranche_2_confirmation']['rule']}")
    print(f"3. Tranche 3 (25% Final): {plan['tranche_3_expansion']['shares']} shares @ ₹{plan['tranche_3_expansion']['entry_price']:.2f} | {plan['tranche_3_expansion']['rule']}")
    print("=" * 60)

if __name__ == "__main__":
    main()
