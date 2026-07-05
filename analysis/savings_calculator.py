"""
Savings calculator: computes the DER value-stack waterfall.

Runs five scenarios in sequence, each building on the previous:
  1. Baseline      -- no DER, raw meter data
  2. Solar only    -- 100 kW PV subtracts from net load
  3. Solar + HVAC  -- pre-cooling shifts morning HVAC; reduces afternoon peak
  4. Solar+HVAC+Bat-- battery discharges during on-peak to flatten demand
  5. Full stack    -- above + DSGS grid services revenue

Returns bill reductions, incremental savings, simple payback, and NPV.

See PLAN.md -- Engineering Tradeoffs and Output Format sections.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from analysis.bill_calculator import calculate_annual_bill
from models.solar_model import load_solar_profile

# ── Capital cost assumptions ──────────────────────────────────────────────
CAPEX: dict[str, float] = {
    "solar_100kw": 280_000,          # $2.80/W installed (2023 C&I average)
    "hvac_controls": 5_000,          # incremental BMS upgrade
    "battery_125kw_250kwh": 150_000, # $600/kWh installed
    "full_stack": 435_000,           # solar + HVAC + battery
}

# DSGS annual revenue estimate based on SCE program rules
DSGS_ANNUAL_REVENUE: float = 8_000  # $/year (conservative, 4 events/yr)

_DISCOUNT_RATE = 0.08   # 8% for NPV
_ANALYSIS_YEARS = 20


# ── Scenario runners ──────────────────────────────────────────────────────

def run_baseline(df: pd.DataFrame) -> pd.DataFrame:
    """Annual bill with no interventions (raw meter load)."""
    return calculate_annual_bill(df)


def run_solar_only(
    df: pd.DataFrame,
    solar_kw: float = 100.0,
) -> pd.DataFrame:
    """
    Subtract solar generation from meter load; recalculate annual bill.

    Solar reduces both energy charges (less kWh drawn from grid) and
    demand charges (lower net peak during midday/afternoon).
    """
    solar = load_solar_profile(solar_kw)
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    solar["timestamp"] = pd.to_datetime(solar["timestamp"])

    df_merged = df.merge(
        solar[["timestamp", "solar_kw"]], on="timestamp", how="left"
    )
    df_merged["solar_kw"] = df_merged["solar_kw"].fillna(0.0)
    # Net load: solar first offsets building load; no export to grid
    df_merged["demand_kw"] = np.maximum(
        0.0, df_merged["demand_kw"] - df_merged["solar_kw"]
    )
    return calculate_annual_bill(df_merged)


def run_solar_hvac(
    df: pd.DataFrame,
    solar_kw: float = 100.0,
    precool_shift_pct: float = 0.30,
) -> pd.DataFrame:
    """
    Solar + HVAC pre-cooling control.

    Pre-cooling shifts a portion of HVAC load from 2pm-8pm on-peak window
    to 10am-2pm (mid-peak/off-peak). This reduces the afternoon demand peak.

    Args:
        precool_shift_pct: Fraction of on-peak HVAC load shifted earlier.
                           Conservatively set to 30% for a school building.
    """
    solar = load_solar_profile(solar_kw)
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    solar["timestamp"] = pd.to_datetime(solar["timestamp"])

    df_merged = df.merge(
        solar[["timestamp", "solar_kw"]], on="timestamp", how="left"
    )
    df_merged["solar_kw"] = df_merged["solar_kw"].fillna(0.0)
    df_merged["demand_kw"] = np.maximum(
        0.0, df_merged["demand_kw"] - df_merged["solar_kw"]
    )

    ts = df_merged["timestamp"]
    hour = ts.dt.hour
    month = ts.dt.month
    weekday = ts.dt.dayofweek < 5

    # Summer on-peak hours: 14:00-20:00 weekdays Jun-Sep
    on_peak = (
        weekday
        & month.isin([6, 7, 8, 9])
        & (hour >= 14) & (hour < 20)
    )
    # Pre-cool hours: 10:00-14:00 weekdays Jun-Sep
    precool = (
        weekday
        & month.isin([6, 7, 8, 9])
        & (hour >= 10) & (hour < 14)
    )

    # Estimate HVAC fraction of load for occupied summer hours
    hvac_col = "out.electricity.hvac.demand_kw"
    if hvac_col in df_merged.columns:
        hvac_on_peak = df_merged.loc[on_peak, hvac_col].values
    else:
        # Fallback: estimate HVAC as 55% of on-peak load
        hvac_on_peak = df_merged.loc[on_peak, "demand_kw"].values * 0.55

    # Load shifted away from on-peak: distributed equally into precool window
    total_shift = float(hvac_on_peak.sum() * precool_shift_pct)
    n_precool = int(precool.sum())
    shift_per_interval = total_shift / n_precool if n_precool > 0 else 0.0

    df_merged.loc[on_peak, "demand_kw"] -= (
        hvac_on_peak * precool_shift_pct
    )
    df_merged.loc[precool, "demand_kw"] += shift_per_interval
    df_merged["demand_kw"] = np.maximum(0.0, df_merged["demand_kw"])

    return calculate_annual_bill(df_merged)


def run_solar_hvac_battery(
    df: pd.DataFrame,
    solar_kw: float = 100.0,
    battery_kw: float = 125.0,
    battery_kwh: float = 250.0,
    precool_shift_pct: float = 0.30,
) -> pd.DataFrame:
    """
    Solar + HVAC pre-cooling + battery dispatch.

    Battery is charged during off-peak (00:00-10:00) using demand-aware
    power capping (charge power limited so total grid demand stays below
    the target demand ceiling), then discharged during on-peak (14:00-20:00)
    to flatten peak demand.

    Key insight: uncapped charging at night creates new all-time demand
    charge peaks. Capping charge to ``target_kw - current_load`` avoids
    this while still filling the battery during the deep off-peak valley.
    """
    df_sim = df.copy()
    df_sim["timestamp"] = pd.to_datetime(df_sim["timestamp"])
    solar = load_solar_profile(solar_kw)
    solar["timestamp"] = pd.to_datetime(solar["timestamp"])
    df_sim = df_sim.merge(
        solar[["timestamp", "solar_kw"]], on="timestamp", how="left"
    )
    df_sim["solar_kw"] = df_sim["solar_kw"].fillna(0.0)
    # Apply solar offset and HVAC pre-cooling (same as scenario 3)
    df_sim["net_kw"] = np.maximum(
        0.0, df_sim["demand_kw"] - df_sim["solar_kw"]
    )

    # Apply HVAC pre-cooling shift to net load
    ts = df_sim["timestamp"]
    hour = ts.dt.hour
    month = ts.dt.month
    weekday = ts.dt.dayofweek < 5

    on_peak = (
        weekday & month.isin([6, 7, 8, 9])
        & (hour >= 14) & (hour < 20)
    )
    precool = (
        weekday & month.isin([6, 7, 8, 9])
        & (hour >= 10) & (hour < 14)
    )
    hvac_col = "out.electricity.hvac.demand_kw"
    if hvac_col in df_sim.columns:
        hvac_on_peak = df_sim.loc[on_peak, hvac_col].values
    else:
        hvac_on_peak = df_sim.loc[on_peak, "net_kw"].values * 0.55
    total_shift = float(hvac_on_peak.sum() * precool_shift_pct)
    n_precool = int(precool.sum())
    shift_per_interval = total_shift / n_precool if n_precool > 0 else 0.0
    df_sim.loc[on_peak, "net_kw"] -= hvac_on_peak * precool_shift_pct
    df_sim.loc[precool, "net_kw"] += shift_per_interval
    df_sim["net_kw"] = np.maximum(0.0, df_sim["net_kw"])

    # ── Per-month target demand ceiling ───────────────────────────────
    # Set a target peak per month so battery charging never exceeds it.
    # This avoids creating new all-time demand charge spikes overnight.
    # Target = seasonal reduction fraction applied to each month's peak.
    month_arr = df_sim["timestamp"].dt.month.values
    monthly_peaks = (
        df_sim.groupby(df_sim["timestamp"].dt.month)["net_kw"].max()
    )
    # Summer: target 40% of peak; shoulder: 70%; winter: 85%
    def _target(m: int) -> float:
        pk = float(monthly_peaks.get(m, 150.0))
        if m in [6, 7, 8, 9]:
            return pk * 0.40
        if m in [4, 5, 10, 11]:
            return pk * 0.70
        return pk * 0.85

    dt = 0.25
    eta = np.sqrt(0.92)
    soc = battery_kwh * 0.50
    soc_min = battery_kwh * 0.10
    soc_max = battery_kwh * 0.95

    bat_dispatch = np.zeros(len(df_sim))

    for i in range(len(df_sim)):
        h = int(hour.iloc[i])
        m = int(month.iloc[i])
        is_wd = bool(weekday.iloc[i])
        is_summer = m in [6, 7, 8, 9]
        current_load = float(df_sim["net_kw"].iloc[i])
        target = _target(m)

        if (0 <= h < 10) or (not is_summer and 0 <= h < 8):
            # Charge window: demand-capped to avoid new demand peaks
            headroom = soc_max - soc
            demand_room = max(0.0, target - current_load)
            p_charge = min(battery_kw, demand_room, headroom / (dt * eta))
            p_charge = max(0.0, p_charge)
            soc += p_charge * dt * eta
            bat_dispatch[i] = -p_charge   # negative = charging

        elif (14 <= h < 20) and is_wd and is_summer:
            # Summer on-peak discharge
            available = soc - soc_min
            p_discharge = min(battery_kw, available * eta / dt)
            p_discharge = max(0.0, p_discharge)
            soc -= p_discharge * dt / eta
            bat_dispatch[i] = p_discharge  # positive = discharging

        elif (10 <= h < 21) and is_wd and not is_summer:
            # Shoulder/winter mid-peak discharge
            available = soc - soc_min
            p_discharge = min(battery_kw * 0.5, available * eta / dt)
            p_discharge = max(0.0, p_discharge)
            soc -= p_discharge * dt / eta
            bat_dispatch[i] = p_discharge

    # Apply battery: discharge reduces load, charge adds to load
    df_sim["demand_kw"] = np.maximum(
        0.0, df_sim["net_kw"] - bat_dispatch
    )
    return calculate_annual_bill(df_sim)


# ── Waterfall + financial metrics ────────────────────────────────────────

def build_waterfall(
    baseline_annual: float,
    solar_annual: float,
    solar_hvac_annual: float,
    solar_hvac_bat_annual: float,
    full_stack_annual: float,
) -> list[dict]:
    """
    Build waterfall chart data (each step shows its incremental saving).

    Returns a list of dicts suitable for plotting or JSON serialisation.
    """
    return [
        {
            "label": "Baseline bill",
            "value": round(baseline_annual, 0),
            "incremental": 0,
            "cumulative_savings": 0,
        },
        {
            "label": "Solar (100 kW)",
            "value": round(solar_annual, 0),
            "incremental": round(baseline_annual - solar_annual, 0),
            "cumulative_savings": round(baseline_annual - solar_annual, 0),
        },
        {
            "label": "+ HVAC pre-cool",
            "value": round(solar_hvac_annual, 0),
            "incremental": round(solar_annual - solar_hvac_annual, 0),
            "cumulative_savings": round(
                baseline_annual - solar_hvac_annual, 0
            ),
        },
        {
            "label": "+ Battery (125kW/250kWh)",
            "value": round(solar_hvac_bat_annual, 0),
            "incremental": round(
                solar_hvac_annual - solar_hvac_bat_annual, 0
            ),
            "cumulative_savings": round(
                baseline_annual - solar_hvac_bat_annual, 0
            ),
        },
        {
            "label": "+ DSGS grid services",
            "value": round(full_stack_annual - DSGS_ANNUAL_REVENUE, 0),
            "incremental": round(DSGS_ANNUAL_REVENUE, 0),
            "cumulative_savings": round(
                baseline_annual - (full_stack_annual - DSGS_ANNUAL_REVENUE),
                0,
            ),
        },
    ]


def calculate_payback(
    annual_savings: float,
    capex: float,
    years: int = _ANALYSIS_YEARS,
    discount_rate: float = _DISCOUNT_RATE,
) -> dict:
    """
    Compute simple payback period and discounted NPV.

    Args:
        annual_savings:  Annual bill reduction ($/year).
        capex:           Upfront capital cost ($).
        years:           Analysis horizon for NPV (default 20).
        discount_rate:   Annual discount rate (default 8%).

    Returns:
        dict with simple_payback_years, npv (over analysis horizon),
        irr_approx (simplified estimate).
    """
    if annual_savings <= 0 or capex <= 0:
        return {
            "simple_payback_years": None,
            "npv": None,
            "irr_approx": None,
        }
    payback = capex / annual_savings
    npv = (
        sum(annual_savings / (1 + discount_rate) ** t for t in range(1, years + 1))
        - capex
    )
    # Approximate IRR via bisection (good enough for project screening)
    lo, hi = 0.0, 5.0
    for _ in range(50):
        mid = (lo + hi) / 2
        npv_mid = sum(
            annual_savings / (1 + mid) ** t for t in range(1, years + 1)
        ) - capex
        if npv_mid > 0:
            lo = mid
        else:
            hi = mid
    irr = round((lo + hi) / 2 * 100, 1)  # as percent

    return {
        "simple_payback_years": round(payback, 2),
        "npv": round(npv, 0),
        "irr_approx": irr,
    }


# ── Pretty-print summary ──────────────────────────────────────────────────

def print_savings_summary(
    waterfall: list[dict],
    paybacks: dict[str, dict],
) -> None:
    """Print a formatted savings and payback summary to stdout."""
    print("\n=== DER Value-Stack Savings Summary ===\n")
    print(f"  {'Scenario':<30}  {'Annual Bill':>12}  {'Incremental':>12}")
    print("  " + "-" * 58)
    for step in waterfall:
        print(
            f"  {step['label']:<30}  "
            f"${step['value']:>10,.0f}  "
            f"${step['incremental']:>10,.0f}"
        )

    print("\n=== Payback Analysis ===\n")
    for name, pb in paybacks.items():
        if pb["simple_payback_years"] is None:
            print(f"  {name}: no savings")
        else:
            print(
                f"  {name:<28}  "
                f"Payback: {pb['simple_payback_years']:.1f} yr  "
                f"NPV: ${pb['npv']:>10,.0f}  "
                f"IRR: {pb['irr_approx']:.1f}%"
            )


if __name__ == "__main__":
    _ROOT = Path(__file__).parent.parent
    print("Loading meter data...")
    df = pd.read_parquet(_ROOT / "data" / "meter" / "school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # ── Run all scenarios ─────────────────────────────────────────────
    print("Running scenario 1: Baseline...")
    baseline = run_baseline(df)
    baseline_total = float(baseline["total"].sum())

    print("Running scenario 2: Solar only (100 kW)...")
    solar = run_solar_only(df, solar_kw=100.0)
    solar_total = float(solar["total"].sum())

    print("Running scenario 3: Solar + HVAC pre-cooling...")
    solar_hvac = run_solar_hvac(df, solar_kw=100.0)
    solar_hvac_total = float(solar_hvac["total"].sum())

    print("Running scenario 4: Solar + HVAC + Battery (125kW/250kWh)...")
    solar_hvac_bat = run_solar_hvac_battery(df, solar_kw=100.0)
    solar_hvac_bat_total = float(solar_hvac_bat["total"].sum())

    # Full stack = solar+HVAC+battery bill minus DSGS revenue
    full_stack_total = solar_hvac_bat_total + DSGS_ANNUAL_REVENUE

    # ── Waterfall ─────────────────────────────────────────────────────
    waterfall = build_waterfall(
        baseline_total,
        solar_total,
        solar_hvac_total,
        solar_hvac_bat_total,
        full_stack_total,
    )

    # ── Paybacks ──────────────────────────────────────────────────────
    paybacks = {
        "Solar only": calculate_payback(
            baseline_total - solar_total,
            CAPEX["solar_100kw"],
        ),
        "Solar + HVAC": calculate_payback(
            baseline_total - solar_hvac_total,
            CAPEX["solar_100kw"] + CAPEX["hvac_controls"],
        ),
        "Solar + HVAC + Battery": calculate_payback(
            baseline_total - solar_hvac_bat_total + DSGS_ANNUAL_REVENUE,
            CAPEX["full_stack"],
        ),
    }

    print_savings_summary(waterfall, paybacks)
