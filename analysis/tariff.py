"""
SCE TOU-GS-3 tariff parser.

Loads data/tariff/sce_tou_gs3.json and exposes helper functions.
All rate lookups across the project must go through this module —
never hard-code rates elsewhere.

See PLAN.md — Bill Calculator section for rate tables.
"""

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

_TARIFF_PATH = (
    Path(__file__).parents[1] / "data" / "tariff" / "sce_tou_gs3.json"
)


@lru_cache(maxsize=1)
def load_tariff() -> dict:
    """Load and cache the SCE TOU-GS-3 tariff JSON."""
    with open(_TARIFF_PATH) as f:
        return json.load(f)


def classify_period(ts: datetime) -> str:
    """
    Classify a 15-min timestamp into a SCE TOU-GS-3 rate period.

    TOU windows are utility-defined fixed time blocks from the tariff
    schedule — they do NOT depend on actual consumption levels.

    Summer (Jun–Sep):
      On-peak:  weekdays 14:00–20:00
      Mid-peak: weekdays 10:00–14:00 and 20:00–21:00
      Off-peak: all other hours

    Winter (Oct–May):
      Mid-peak: weekdays 10:00–21:00
      Off-peak: all other hours (no on-peak period in winter)

    Returns: 'on_peak', 'mid_peak', or 'off_peak'
    """
    month = ts.month
    hour = ts.hour
    is_weekday = ts.weekday() < 5
    is_summer = month in (6, 7, 8, 9)

    if is_summer:
        if is_weekday and 14 <= hour < 20:
            return "on_peak"
        if is_weekday and (10 <= hour < 14 or 20 <= hour < 21):
            return "mid_peak"
        return "off_peak"
    else:
        if is_weekday and 10 <= hour < 21:
            return "mid_peak"
        return "off_peak"


def get_energy_rate(ts: datetime) -> float:
    """Return the energy rate ($/kWh) for a given timestamp."""
    tariff = load_tariff()
    season = "summer" if ts.month in (6, 7, 8, 9) else "winter"
    period = classify_period(ts)
    rates = tariff["energy_charges_per_kwh"][season]
    rate_key = period if period in rates else "off_peak"
    return rates[rate_key]["rate"]


def get_demand_rates(month: int) -> dict:
    """
    Return demand charge rates ($/kW) for a given month.

    Returned keys:
      'all_time_kw'  — applies to highest 15-min kW in the month
      'on_peak_kw'   — applies to highest 15-min kW during on-peak
                       hours (summer only)
      'mid_peak_kw'  — demand charge for mid-peak window
    """
    tariff = load_tariff()
    season = "summer" if month in (6, 7, 8, 9) else "winter"
    return tariff["demand_charges"][season]


def get_customer_charge() -> float:
    """Return the fixed monthly customer charge in USD."""
    tariff = load_tariff()
    return tariff["fixed_charges"]["customer_charge_monthly_usd"]


def get_dsgs_rate() -> float:
    """Return the DSGS demand response rate ($/kWh) for avoided energy."""
    tariff = load_tariff()
    return tariff["notes"]["dsgs_rate_per_kwh"]
