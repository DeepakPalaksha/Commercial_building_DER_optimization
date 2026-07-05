"""
Seasonal control strategy definitions for DER dispatch.

Maps each calendar month to the appropriate dispatch strategy based on
the building's HVAC load profile and SCE TOU-GS-3 tariff structure.

Strategy logic:
  Summer   (Jun-Sep) -- HVAC 60-70% of load; pre-cool 10am-2pm before
                        on-peak window; battery for afternoon demand peak.
  Shoulder (Apr-May, Oct-Nov) -- moderate HVAC; battery for TOU arbitrage.
  Winter   (Jan-Mar, Dec) -- minimal HVAC; grid services + TOU arbitrage.

See PLAN.md -- Seasonal Control Strategies section.
"""
from __future__ import annotations


# ── Strategy registry ─────────────────────────────────────────────────────

SEASONAL_STRATEGIES: dict[str, dict] = {
    "summer": {
        "months": [6, 7, 8, 9],
        "description": (
            "HVAC 60-70% of load. "
            "Pre-cool 10am-2pm. Battery for afternoon on-peak."
        ),
        "precool_window": ("10:00", "14:00"),
        "precool_temp_f": 70,
        "battery_mode": "demand_charge_management",
        "battery_charge_window": ("00:00", "10:00"),
        "battery_discharge_window": ("14:00", "20:00"),
        "target_demand_reduction_pct": 0.60,
        "dsgs_enrollment": False,
        "notes": (
            "Summer on-peak demand charge $19.10/kW. "
            "Battery discharge aligned to SCE on-peak 14:00-20:00."
        ),
    },
    "shoulder": {
        "months": [4, 5, 10, 11],
        "description": (
            "Moderate HVAC. Battery for TOU arbitrage primarily."
        ),
        "precool_window": None,
        "precool_temp_f": None,
        "battery_mode": "tou_arbitrage",
        "battery_charge_window": ("22:00", "08:00"),
        "battery_discharge_window": ("14:00", "21:00"),
        "target_demand_reduction_pct": 0.30,
        "dsgs_enrollment": False,
        "notes": (
            "No summer on-peak demand charge. "
            "Focus on energy arbitrage between off-peak and mid-peak."
        ),
    },
    "winter": {
        "months": [1, 2, 3, 12],
        "description": (
            "Minimal HVAC. Grid services + TOU arbitrage only."
        ),
        "precool_window": None,
        "precool_temp_f": None,
        "battery_mode": "grid_services_plus_tou",
        "battery_charge_window": ("22:00", "08:00"),
        "battery_discharge_window": ("10:00", "21:00"),
        "target_demand_reduction_pct": 0.15,
        "dsgs_enrollment": True,
        "notes": (
            "DSGS (Demand Side Grid Support) program enrolled. "
            "Discharge during grid stress events pays $2/kWh."
        ),
    },
}


# ── Lookup helpers ────────────────────────────────────────────────────────

def get_strategy(month: int) -> dict:
    """
    Return the seasonal strategy dict for a given month (1-12).

    Adds a 'season' key to the returned dict for convenience.

    Raises:
        ValueError: if month is not in 1-12.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be 1-12, got {month}")
    for name, strategy in SEASONAL_STRATEGIES.items():
        if month in strategy["months"]:
            return {**strategy, "season": name}
    raise ValueError(f"Month {month} not mapped to any strategy")


def is_battery_charge_hour(hour: int, minute: int, month: int) -> bool:
    """Return True if the given time is within the battery charge window."""
    strategy = get_strategy(month)
    start_str, end_str = strategy["battery_charge_window"]
    start_h, start_m = map(int, start_str.split(":"))
    end_h, end_m = map(int, end_str.split(":"))
    t = hour * 60 + minute
    s = start_h * 60 + start_m
    e = end_h * 60 + end_m
    if s <= e:
        return s <= t < e
    # Wraps midnight (e.g. 22:00-08:00)
    return t >= s or t < e


def is_battery_discharge_hour(hour: int, minute: int, month: int) -> bool:
    """Return True if the given time is within the battery discharge window."""
    strategy = get_strategy(month)
    start_str, end_str = strategy["battery_discharge_window"]
    start_h, start_m = map(int, start_str.split(":"))
    end_h, end_m = map(int, end_str.split(":"))
    t = hour * 60 + minute
    s = start_h * 60 + start_m
    e = end_h * 60 + end_m
    return s <= t < e


def is_precool_hour(hour: int, minute: int, month: int) -> bool:
    """Return True if the given time is within the pre-cooling window."""
    strategy = get_strategy(month)
    if strategy["precool_window"] is None:
        return False
    start_str, end_str = strategy["precool_window"]
    start_h, start_m = map(int, start_str.split(":"))
    end_h, end_m = map(int, end_str.split(":"))
    t = hour * 60 + minute
    s = start_h * 60 + start_m
    e = end_h * 60 + end_m
    return s <= t < e


if __name__ == "__main__":
    print("Seasonal strategy summary:")
    print("-" * 60)
    for month in [1, 4, 7, 10]:
        s = get_strategy(month)
        print(
            f"  Month {month:>2}  season={s['season']:<8}  "
            f"battery_mode={s['battery_mode']:<25}  "
            f"dsgs={s['dsgs_enrollment']}"
        )

    print("\nCharge/discharge window check (July, hour 15):")
    print(
        f"  is_charge_hour(15, 0, July):    "
        f"{is_battery_charge_hour(15, 0, 7)}"
    )
    print(
        f"  is_discharge_hour(15, 0, July): "
        f"{is_battery_discharge_hour(15, 0, 7)}"
    )
    print(
        f"  is_precool_hour(11, 0, July):   "
        f"{is_precool_hour(11, 0, 7)}"
    )
    print(
        f"  is_precool_hour(15, 0, July):   "
        f"{is_precool_hour(15, 0, 7)}"
    )

    print("\nWinter midnight charge window check (Jan, hour 23):")
    print(
        f"  is_charge_hour(23, 0, Jan):     "
        f"{is_battery_charge_hour(23, 0, 1)}"
    )
    print(
        f"  is_charge_hour(3, 0, Jan):      "
        f"{is_battery_charge_hour(3, 0, 1)}"
    )
