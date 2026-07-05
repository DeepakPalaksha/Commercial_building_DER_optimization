"""
SCE TOU-GS-3 bill calculator.

Reconstructs a monthly bill from 15-min interval meter data.

Bill components:
  1. Energy charges  — $/kWh by TOU period (summer/winter)
  2. Demand charges  — $/kW applied to peak 15-min interval in month
       - All-time demand: highest kW in any interval during the month
       - On-peak demand:  highest kW during on-peak hours (summer only)
  3. Fixed charge    — flat customer charge per month ($302.72)

See PLAN.md — Bill Calculator section for SCE TOU-GS-3 rate tables.
"""

import pandas as pd

from analysis.tariff import (
    classify_period,
    get_customer_charge,
    get_demand_rates,
    load_tariff,
)


def calculate_monthly_bill(df: pd.DataFrame, month: int) -> dict:
    """
    Reconstruct one month's SCE TOU-GS-3 bill.

    Args:
        df:    DataFrame with columns:
                 'timestamp' (datetime64) and 'demand_kw' (float).
               The timestamp column must already be parsed as datetime.
        month: integer 1–12.

    Returns:
        dict with keys:
          month, energy_charge, demand_charge, fixed_charge, total,
          peak_demand_kw, on_peak_demand_kw, total_kwh.
    """
    dm = df[df["timestamp"].dt.month == month].copy()
    if dm.empty:
        raise ValueError(f"No data found for month {month}")

    # kWh per 15-min interval
    dm["kwh"] = dm["demand_kw"] * 0.25
    dm["period"] = dm["timestamp"].apply(classify_period)

    # ── Energy charges ───────────────────────────────────────────────
    tariff_data = load_tariff()
    season = "summer" if month in (6, 7, 8, 9) else "winter"
    rates = tariff_data["energy_charges_per_kwh"][season]

    energy_charge = 0.0
    for period, group in dm.groupby("period"):
        rate_key = period if period in rates else "off_peak"
        energy_charge += group["kwh"].sum() * rates[rate_key]["rate"]

    # ── Demand charges ───────────────────────────────────────────────
    dc_rates = get_demand_rates(month)

    # All-time peak: highest single 15-min average kW in the month
    peak_demand_kw = float(dm["demand_kw"].max())
    demand_charge = peak_demand_kw * dc_rates.get("all_time_kw", 0.0)

    # On-peak demand: highest kW during on-peak hours (summer only)
    on_peak_demand_kw = 0.0
    if "on_peak_kw" in dc_rates:
        on_peak_rows = dm[dm["period"] == "on_peak"]
        if not on_peak_rows.empty:
            on_peak_demand_kw = float(on_peak_rows["demand_kw"].max())
        demand_charge += on_peak_demand_kw * dc_rates["on_peak_kw"]

    # Mid-peak demand (applies in both seasons)
    if "mid_peak_kw" in dc_rates:
        mid_peak_rows = dm[dm["period"] == "mid_peak"]
        if not mid_peak_rows.empty:
            mid_peak_demand_kw = float(mid_peak_rows["demand_kw"].max())
            demand_charge += mid_peak_demand_kw * dc_rates["mid_peak_kw"]

    # ── Fixed charge ─────────────────────────────────────────────────
    fixed_charge = get_customer_charge()

    total = energy_charge + demand_charge + fixed_charge
    return {
        "month": month,
        "energy_charge": round(energy_charge, 2),
        "demand_charge": round(demand_charge, 2),
        "fixed_charge": round(fixed_charge, 2),
        "total": round(total, 2),
        "peak_demand_kw": round(peak_demand_kw, 1),
        "on_peak_demand_kw": round(on_peak_demand_kw, 1),
        "total_kwh": round(float(dm["kwh"].sum()), 1),
    }


def calculate_annual_bill(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate bill for all 12 months.

    Args:
        df: DataFrame with 'timestamp' and 'demand_kw' columns.

    Returns:
        DataFrame with one row per month plus summary printed to stdout.
    """
    rows = [calculate_monthly_bill(df, m) for m in range(1, 13)]
    annual = pd.DataFrame(rows)
    annual_total = annual["total"].sum()
    print(f"Annual bill: ${annual_total:,.0f}")
    print(
        f"  Energy:  ${annual['energy_charge'].sum():>10,.0f}"
        f"  ({annual['energy_charge'].sum()/annual_total*100:.0f}%)"
    )
    print(
        f"  Demand:  ${annual['demand_charge'].sum():>10,.0f}"
        f"  ({annual['demand_charge'].sum()/annual_total*100:.0f}%)"
    )
    print(
        f"  Fixed:   ${annual['fixed_charge'].sum():>10,.0f}"
        f"  ({annual['fixed_charge'].sum()/annual_total*100:.0f}%)"
    )
    return annual


def _load_meter() -> pd.DataFrame:
    """Convenience loader for the project's standard meter parquet."""
    from pathlib import Path

    path = Path(__file__).parents[1] / "data" / "meter" / "school_ca_15min.parquet"
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        df = df.rename(columns={df.columns[0]: "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


if __name__ == "__main__":
    df = _load_meter()
    annual = calculate_annual_bill(df)
    print()
    print(
        annual[
            ["month", "total", "energy_charge", "demand_charge", "peak_demand_kw"]
        ].to_string(index=False)
    )
