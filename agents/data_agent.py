"""
Data agent: loads, validates, and aligns all data sources.

Responsibility: single point of truth for data loading. Every
downstream agent reads from state['meter'], state['solar'], etc.
Never reads files directly -- always goes through this agent.

See PLAN.md -- Agent Architecture section.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
EXPECTED_INTERVALS = 35_040   # 365 days x 24 hours x 4 (15-min)


def run_data_agent(state: dict) -> dict:
    """
    Load and validate all data sources. Populates:
      state['meter']   -- 15-min interval DataFrame
      state['weather'] -- hourly EPW DataFrame (empty if unavailable)
      state['prices']  -- CAISO hourly LMP DataFrame
      state['solar']   -- hourly PVWatts DataFrame
      state['errors']  -- list of non-fatal warning strings

    The agent never raises on individual file failures (except meter,
    which is mandatory). Missing optional sources are replaced with
    empty DataFrames and a warning is appended to state['errors'].
    """
    errors: list[str] = []

    # ── 1. Meter data (mandatory) ─────────────────────────────────────
    meter_path_override = state.get("meter_path")
    meter_path = (
        Path(meter_path_override)
        if meter_path_override
        else DATA_DIR / "meter" / "school_ca_15min.parquet"
    )
    if not meter_path.exists():
        raise FileNotFoundError(
            f"Meter data not found: {meter_path}\n"
            "Run: uv run python scripts/download_data.py"
        )
    meter = pd.read_parquet(meter_path)
    meter["timestamp"] = pd.to_datetime(meter["timestamp"])
    meter = meter.sort_values("timestamp").reset_index(drop=True)

    # Gap detection
    if len(meter) < EXPECTED_INTERVALS * 0.95:
        errors.append(
            f"Meter data sparse: {len(meter)} rows "
            f"(expected ~{EXPECTED_INTERVALS})"
        )

    # Short gaps (up to 2 hr = 8 intervals): linear interpolation
    meter["demand_kw"] = meter["demand_kw"].interpolate(
        method="linear", limit=8
    )

    # ── 2. Weather data (optional) ────────────────────────────────────
    weather_df = pd.DataFrame()
    weather_path = DATA_DIR / "weather" / "USA_CA_Los.Angeles.TMY3.epw"
    if weather_path.exists():
        try:
            import pvlib  # type: ignore
            weather_df, _ = pvlib.iotools.read_epw(str(weather_path))
            weather_df = weather_df.reset_index()
            weather_df.columns = [str(c) for c in weather_df.columns]
            if "temp_air" in weather_df.columns:
                weather_df["T_outdoor_f"] = (
                    weather_df["temp_air"] * 9 / 5 + 32
                )
        except Exception as exc:
            errors.append(f"Weather EPW load failed: {exc}")
            weather_df = pd.DataFrame()
    else:
        errors.append(
            "EPW weather file not found. "
            "T_outdoor_f from meter parquet will be used."
        )

    # ── 3. CAISO prices ───────────────────────────────────────────────
    prices_path = DATA_DIR / "prices" / "caiso_dam_lmp_2023.csv"
    if prices_path.exists():
        prices = pd.read_csv(prices_path)
        # Filter to total LMP rows only (not congestion/loss components)
        if "LMP_TYPE" in prices.columns:
            prices = prices[prices["LMP_TYPE"] == "LMP"].copy()
        prices.reset_index(drop=True, inplace=True)
    else:
        errors.append(
            f"CAISO prices not found: {prices_path}. "
            "Tariff rates will be used as proxy."
        )
        prices = pd.DataFrame()

    # ── 4. Solar profile ──────────────────────────────────────────────
    solar_path = DATA_DIR / "solar" / "pvwatts_100kw_socal.csv"
    if solar_path.exists():
        solar = pd.read_csv(solar_path, parse_dates=["timestamp"])
    else:
        errors.append(
            f"Solar data not found: {solar_path}. "
            "Zero solar will be assumed."
        )
        solar = pd.DataFrame()

    # ── Summary print ─────────────────────────────────────────────────
    n_solar = len(solar) if not solar.empty else 0
    n_prices = len(prices) if not prices.empty else 0
    n_weather = len(weather_df) if not weather_df.empty else 0
    print(
        f"[data_agent] meter={len(meter):,} rows, "
        f"solar={n_solar:,}, prices={n_prices:,}, "
        f"weather={n_weather}, errors={len(errors)}"
    )
    if errors:
        for e in errors:
            print(f"  WARNING: {e}")

    state.update({
        "meter": meter,
        "weather": weather_df,
        "prices": prices,
        "solar": solar,
        "errors": errors,
    })
    return state
