"""
Solar PV generation model.

Loads the NREL PVWatts hourly CSV (data/solar/pvwatts_100kw_socal.csv)
and provides a 15-min interpolated AC output series for any requested
system size.  Timestamps are aligned to DATA_YEAR (2023) so the index
matches the meter data.

See PLAN.md -- Core Models section for design rationale.
"""
import numpy as np
import pandas as pd
from pathlib import Path

_SOLAR_CSV = (
    Path(__file__).parents[1] / "data" / "solar" / "pvwatts_100kw_socal.csv"
)
_BASE_CAPACITY_KW = 100.0  # kW at which PVWatts data was generated


def load_solar_profile(system_capacity_kw: float = 100.0) -> pd.DataFrame:
    """
    Load PVWatts hourly data and interpolate to 15-min resolution.

    Uses linear interpolation (not forward-fill) so that the transition
    from daylight to darkness is smooth.

    Args:
        system_capacity_kw: Desired system size. Output is scaled linearly
                            from the 100 kW base profile.

    Returns:
        DataFrame with columns 'timestamp' (DatetimeTZNaive) and
        'solar_kw' at 15-min frequency, sorted by timestamp.
    """
    if not _SOLAR_CSV.exists():
        raise FileNotFoundError(
            f"Solar CSV not found: {_SOLAR_CSV}\n"
            "Run: uv run python scripts/download_data.py"
        )

    df = pd.read_csv(_SOLAR_CSV, parse_dates=["timestamp"])
    df = df[["timestamp", "ac_output_kw"]].sort_values("timestamp")
    df = df.set_index("timestamp")

    # Resample hourly -> 15-min with linear interpolation
    df_15min = df.resample("15min").interpolate(method="linear")
    df_15min = df_15min.reset_index()
    df_15min.columns = ["timestamp", "solar_kw"]

    # Clip negatives (rounding artefacts from interpolation)
    df_15min["solar_kw"] = df_15min["solar_kw"].clip(lower=0.0)

    # Scale to requested system size
    scale = system_capacity_kw / _BASE_CAPACITY_KW
    df_15min["solar_kw"] = (df_15min["solar_kw"] * scale).round(3)

    return df_15min


def get_annual_generation_kwh(system_capacity_kw: float = 100.0) -> float:
    """Return total annual AC generation in kWh for the given system size."""
    df = load_solar_profile(system_capacity_kw)
    # 15-min intervals: each row represents 0.25 hr
    return round(float(df["solar_kw"].sum() * 0.25), 0)


def get_peak_output_kw(system_capacity_kw: float = 100.0) -> float:
    """Return the maximum AC output across the year (kW)."""
    df = load_solar_profile(system_capacity_kw)
    return float(df["solar_kw"].max())


def get_daily_profile(
    system_capacity_kw: float = 100.0,
    month: int = 7,
) -> pd.DataFrame:
    """
    Return the average daily generation profile for a given month.

    Useful for visualising the solar contribution shape.

    Returns:
        DataFrame with 'hour' (0-23.75 in 0.25 steps) and
        'solar_kw' columns.
    """
    df = load_solar_profile(system_capacity_kw)
    df = df[df["timestamp"].dt.month == month].copy()
    df["hour"] = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60
    daily = df.groupby("hour")["solar_kw"].mean().reset_index()
    return daily


if __name__ == "__main__":
    print("Loading solar profile (100 kW system, SoCal)...")
    profile = load_solar_profile(100.0)
    annual_kwh = get_annual_generation_kwh(100.0)
    peak_kw = get_peak_output_kw(100.0)

    print(f"  Rows:              {len(profile):,}")
    print(
        f"  Date range:        "
        f"{profile['timestamp'].min().date()} "
        f"to {profile['timestamp'].max().date()}"
    )
    print(f"  Annual generation: {annual_kwh:,.0f} kWh")
    print(f"  Yield:             {annual_kwh/100:.0f} kWh/kW")
    print(f"  Peak output:       {peak_kw:.1f} kW")
    print(f"  (SoCal target:     ~1,500-1,700 kWh/kW)")

    # July daily profile
    july = get_daily_profile(100.0, month=7)
    july_peak = july["solar_kw"].max()
    july_noon = july.loc[july["hour"] == 12.0, "solar_kw"].values
    print(f"\n  July avg peak output:     {july_peak:.1f} kW")
    if len(july_noon):
        print(f"  July avg noon output:     {july_noon[0]:.1f} kW")
