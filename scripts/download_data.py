"""
Data download script for Elexity building energy analysis.
Run once before starting analysis: uv run python scripts/download_data.py

All data is standardised to calendar year 2023 so that meter load,
CAISO prices, and solar output share the same timestamp index.
This enables direct year-on-year savings verification.

Note on NREL ComStock: the real S3 dataset is labelled
`comstock_amy2018_release_1` (AMY = Actual Meteorological Year 2018).
If the S3 download ever succeeds the raw timestamps will be 2018; the
synthetic fallback re-stamps everything to 2023 for consistency.

Downloads:
  1. NREL ComStock building meter data (secondary school, CA)
  2. Los Angeles TMY3 weather file (EnergyPlus EPW)
  3. CAISO day-ahead LMP prices (2023, SP15/SCE zone)
  4. NREL PVWatts solar generation (100kW, Mission Viejo CA)
  5. SCE TOU-GS-3 tariff JSON
"""
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# Force UTF-8 output on Windows cp1252 consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
for sub in ("meter", "weather", "prices", "solar", "tariff"):
    (DATA / sub).mkdir(parents=True, exist_ok=True)

DATA_YEAR = 2023  # single source of truth for all timestamp generation


# ── 1. NREL ComStock Building Meter Data ─────────────────────────────────
def download_nrel_comstock():
    """
    Downloads 15-min interval meter data for a secondary school in SoCal.
    Uses AWS S3 public dataset (no credentials).

    Falls back to physics-based synthetic data with DATA_YEAR timestamps
    if S3 is unreachable or column names have changed.
    """
    output_path = DATA / "meter" / "school_ca_15min.parquet"
    if output_path.exists():
        print(f"  [OK] Meter data already exists: {output_path}")
        return

    print("  Attempting NREL ComStock S3 download...")
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.client import Config

        s3 = boto3.client(
            "s3",
            config=Config(signature_version=UNSIGNED),
            region_name="us-west-2",
        )

        meta_path = DATA / "metadata.parquet"
        if not meta_path.exists():
            print("  Downloading metadata (~50MB)...")
            s3.download_file(
                "oedi-data-lake",
                "nrel-pds-building-stock/end-use-load-profiles-for-us"
                "-building-stock/2021/comstock_amy2018_release_1/"
                "metadata/metadata.parquet",
                str(meta_path),
            )

        meta = pd.read_parquet(meta_path)
        cols = meta.columns.tolist()

        state_col = next(
            (c for c in cols if c in
             ("in.state", "state", "in.state_abbreviation")), None
        )
        btype_col = next(
            (c for c in cols if c in
             ("in.building_type", "building_type")), None
        )
        if state_col is None or btype_col is None:
            raise ValueError(
                f"Cannot find state/building_type columns. "
                f"Available: {cols[:20]}"
            )

        mask = (
            (meta[btype_col] == "SecondarySchool")
            & (meta[state_col] == "CA")
        )
        cz_col = next(
            (c for c in cols if "climate_zone" in c.lower()), None
        )
        if cz_col:
            mask = mask & meta[cz_col].isin(["3B", "3C"])
        schools = meta[mask]

        if len(schools) == 0:
            raise ValueError("No matching buildings found in metadata")

        id_col = next(
            (c for c in cols if c in ("bldg_id", "building_id", "id")),
            cols[0],
        )
        bldg_id = schools.iloc[0][id_col]
        sqft = schools.iloc[0].get("in.sqft", "unknown")
        print(f"  Found building: {bldg_id} ({sqft} sqft)")

        s3_key = (
            "nrel-pds-building-stock/end-use-load-profiles-for-us"
            "-building-stock/2021/comstock_amy2018_release_1/"
            f"timeseries_individual_buildings/by_state/upgrade=0/"
            f"state=CA/{bldg_id}-up00.parquet"
        )
        print("  Downloading timeseries (~5MB)...")
        s3.download_file("oedi-data-lake", s3_key, str(output_path))
        print(f"  [OK] Downloaded: {output_path}")

    except Exception as e:
        print(f"  S3 download failed ({e})")
        print("  Falling back to physics-based synthetic data...")
        _generate_synthetic_meter_data(output_path)


def _generate_synthetic_meter_data(output_path: Path):
    """
    Generates realistic 15-min interval meter data for a SoCal secondary
    school. All timestamps use DATA_YEAR for calendar consistency.

    Key parameters (NREL ComStock + Elexity JSerra case study):
      Peak demand : 150-200 kW on hot days (HVAC dominated)
      HVAC        : 60-70% of summer load
      Baseline    : ~52 kW (lighting + plug loads + water heating)
      Building    : ~85,000 sqft
      Occupancy   : Mon-Fri 7am-6pm, all months except July
    """
    import numpy as np

    print(f"  Generating 15-min data for {DATA_YEAR} (35,040 timesteps)...")
    np.random.seed(42)

    # Full year of 15-min timestamps
    ts_start = f"{DATA_YEAR}-01-01"
    ts_end = f"{DATA_YEAR}-12-31 23:45"
    timestamps = pd.date_range(ts_start, ts_end, freq="15min")
    n = len(timestamps)

    # ── Outdoor temperature (LA TMY3 approximation) ───────────────────
    day_of_year = timestamps.dayofyear.to_numpy(dtype=float)
    hour = timestamps.hour.to_numpy(dtype=float) + \
        timestamps.minute.to_numpy(dtype=float) / 60

    T_seasonal = 72 + 18 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
    T_diurnal = 10 * np.sin(2 * np.pi * (hour - 6) / 24)
    T_noise = np.random.normal(0, 2, n)
    T_outdoor = T_seasonal + T_diurnal + T_noise  # degrees F

    # ── School occupancy ──────────────────────────────────────────────
    is_weekday = timestamps.dayofweek < 5
    is_school_month = ~timestamps.month.isin([7])  # closed July
    is_school_hours = (timestamps.hour >= 7) & (timestamps.hour < 18)
    is_occupied = is_weekday & is_school_month & is_school_hours

    # ── Baseline load ─────────────────────────────────────────────────
    baseline_occupied = 52.0    # kW
    baseline_unoccupied = 18.0  # kW (servers, security, fridges)
    load_baseline = np.where(is_occupied, baseline_occupied,
                             baseline_unoccupied)

    # ── HVAC load (temperature-driven RC model) ───────────────────────
    T_setpoint = 72.0   # F indoor setpoint
    COP = 3.2           # coefficient of performance
    # UA calibrated: peak summer (T~95F, dT~23F) -> ~110 kW HVAC
    # UA = Q_peak * COP / dT = 110 * 3.2 / 23 ~ 15.3 kW/F
    building_UA = 15.3  # kW/F (overall heat transfer coefficient)

    cooling_load_kw = np.maximum(
        0, building_UA * (T_outdoor - T_setpoint) / COP
    )
    hvac_load = np.where(
        is_occupied, cooling_load_kw, cooling_load_kw * 0.2
    )
    hvac_load = hvac_load * (1 + np.random.normal(0, 0.08, n))
    hvac_load = np.maximum(0, hvac_load)

    # ── Total demand ──────────────────────────────────────────────────
    demand_kw = load_baseline + hvac_load
    demand_kw = np.minimum(demand_kw, 210.0)  # service limit
    demand_kw += np.random.normal(0, 0.5, n)
    demand_kw = np.maximum(0, demand_kw)

    # ── End-use breakdown ─────────────────────────────────────────────
    lighting_kw = load_baseline * 0.35 * np.where(is_occupied, 1.0, 0.3)
    plug_loads_kw = load_baseline * 0.45 * np.where(is_occupied, 1.0, 0.4)
    water_heating_kw = load_baseline * 0.15 * \
        np.where(is_school_hours, 1.2, 0.5)
    other_kw = np.maximum(
        0, demand_kw - hvac_load - lighting_kw - plug_loads_kw
        - water_heating_kw
    )

    df = pd.DataFrame({
        "timestamp": timestamps,
        "demand_kw": demand_kw.round(2),
        "T_outdoor_f": T_outdoor.round(1),
        "is_occupied": is_occupied,
        "out.electricity.total.demand_kw": demand_kw.round(2),
        "out.electricity.hvac.demand_kw": hvac_load.round(2),
        "out.electricity.lighting.demand_kw": lighting_kw.round(2),
        "out.electricity.plug_loads.demand_kw": plug_loads_kw.round(2),
        "out.electricity.water_heating.demand_kw": water_heating_kw.round(2),
    })
    df.to_parquet(output_path, index=False)

    summer = df[df["timestamp"].dt.month.isin([6, 7, 8, 9])]
    summer_hvac_pct = (
        summer["out.electricity.hvac.demand_kw"].mean()
        / summer["demand_kw"].mean() * 100
    )
    print(f"  [OK] Generated {len(df):,} rows of 15-min interval data")
    print(f"    Year:            {DATA_YEAR}")
    print(f"    Peak demand:     {df['demand_kw'].max():.1f} kW")
    print(f"    Avg demand:      {df['demand_kw'].mean():.1f} kW")
    print(
        f"    Annual energy:   "
        f"{(df['demand_kw'] * 0.25).sum() / 1000:.0f} MWh"
    )
    print(f"    HVAC % (summer): {summer_hvac_pct:.0f}%")
    print(f"    Saved: {output_path}")


# ── 2. Los Angeles TMY3 Weather File ─────────────────────────────────────
def download_weather():
    """
    Downloads LA International Airport TMY3 EPW weather file.
    TMY = Typical Meteorological Year (not year-specific).
    """
    output_path = DATA / "weather" / "USA_CA_Los.Angeles.TMY3.epw"
    if output_path.exists():
        print(f"  [OK] Weather data already exists: {output_path}")
        return

    # Try EnergyPlus climate.onebuilding.org mirror (updated URL)
    urls = [
        (
            "https://climate.onebuilding.org/WMO_Region_4_North_and_Central"
            "_America/USA_California/USA_CA_Los.Angeles.Intl.AP.722950"
            "_TMY3/USA_CA_Los.Angeles.Intl.AP.722950_TMY3.epw"
        ),
        (
            "https://energyplus.net/weather-download/"
            "north_and_central_america_wmo_region_4/USA/CA/"
            "USA_CA_Los.Angeles.Intl.AP.722950_TMY3/"
            "USA_CA_Los.Angeles.Intl.AP.722950_TMY3.epw"
        ),
    ]
    print("  Downloading LA TMY3 EPW weather file...")
    for url in urls:
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            output_path.write_bytes(r.content)
            print(
                f"  [OK] Downloaded: {output_path} "
                f"({len(r.content)/1024:.0f} KB)"
            )
            return
        except Exception as e:
            print(f"  EPW attempt failed: {e}")

    print(
        "  Weather EPW unavailable. T_outdoor_f column in meter parquet"
        " is used as the temperature source for all models."
    )
    print("  Manual download: https://climate.onebuilding.org/")


# ── 3. CAISO Day-Ahead LMP Prices ────────────────────────────────────────
def download_caiso_prices():
    """
    Downloads CAISO day-ahead LMP prices for SP15 zone (SCE territory).
    Source: CAISO OASIS public API -- no account needed.
    Node: TH_SP15_GEN-APND (SP15 trading hub, SCE/SDG&E area)
    Year: DATA_YEAR (2023) -- consistent with all other data sources.
    """
    output_path = DATA / "prices" / f"caiso_dam_lmp_{DATA_YEAR}.csv"
    if output_path.exists():
        print(f"  [OK] CAISO prices already exist: {output_path}")
        return

    print(
        f"  Downloading CAISO day-ahead LMP prices "
        f"({DATA_YEAR}, SP15 zone)..."
    )
    print("  Note: CAISO OASIS rate-limits -- downloading month by month...")

    base_url = "http://oasis.caiso.com/oasisapi/SingleZip"
    all_data = []

    for month in range(1, 13):
        start = datetime(DATA_YEAR, month, 1)
        if month == 12:
            end = datetime(DATA_YEAR, 12, 31)
        else:
            end = datetime(DATA_YEAR, month + 1, 1) - timedelta(days=1)

        params = {
            "queryname": "PRC_LMP",
            "startdatetime": start.strftime("%Y%m%dT00:00-0800"),
            "enddatetime": end.strftime("%Y%m%dT23:00-0800"),
            "version": "1",
            "market_run_id": "DAM",
            "node": "TH_SP15_GEN-APND",
            "resultformat": "6",
        }

        try:
            r = requests.get(base_url, params=params, timeout=60)
            z = zipfile.ZipFile(io.BytesIO(r.content))
            csv_name = [f for f in z.namelist() if f.endswith(".csv")][0]
            df = pd.read_csv(z.open(csv_name))
            all_data.append(df)
            print(f"    [OK] {start.strftime('%B %Y')}: {len(df)} rows")
            time.sleep(2)
        except Exception as e:
            print(f"    [FAIL] {start.strftime('%B %Y')}: {e}")
            continue

    if all_data:
        prices = pd.concat(all_data, ignore_index=True)
        prices.to_csv(output_path, index=False)
        print(f"  [OK] Saved {len(prices):,} rows to {output_path}")
    else:
        print("  CAISO download failed -- generating synthetic price data")
        _generate_synthetic_prices(output_path)


def _generate_synthetic_prices(output_path: Path):
    """
    Generates synthetic CAISO SP15 day-ahead LMP prices for DATA_YEAR.

    Shaped to match 2023 CAISO price statistics:
      Annual average: ~$47/MWh (higher than 2018 due to gas/demand)
      Summer on-peak (2pm-9pm): ~$80/MWh
      Winter off-peak (10pm-7am): ~$28/MWh
      Spring duck curve: negative prices midday (solar oversupply)
    """
    import numpy as np

    np.random.seed(123)
    ts_start = f"{DATA_YEAR}-01-01"
    ts_end = f"{DATA_YEAR}-12-31 23:00"
    timestamps = pd.date_range(ts_start, ts_end, freq="h")
    n = len(timestamps)

    hour = timestamps.hour.to_numpy(dtype=float)
    month = timestamps.month.to_numpy(dtype=int)
    dow = timestamps.dayofweek.to_numpy(dtype=int)

    # 2023 base higher than 2018 due to gas/demand growth
    base = 47.0

    tou_shape = np.where(
        (hour >= 14) & (hour < 21), 33.0,    # on-peak premium
        np.where(hour < 7, -9.0, 5.0),        # off-peak discount
    )
    seasonal = np.where(
        (month >= 6) & (month <= 9), 18.0,
        np.where((month == 12) | (month <= 2), 7.0, 0.0),
    )
    # Duck curve: spring solar oversupply drives negative prices midday
    duck_curve = np.where(
        ((month >= 3) & (month <= 5)) & (hour >= 10) & (hour <= 14),
        -25.0, 0.0,
    )
    weekend = np.where(dow >= 5, -5.0, 0.0)

    lmp = base + tou_shape + seasonal + duck_curve + weekend
    lmp += np.random.normal(0, 6, n)

    df = pd.DataFrame({
        "INTERVALSTARTTIME_GMT": timestamps.strftime(
            f"{DATA_YEAR}-%m-%dT%H:00:00Z"
        ).str.replace(str(DATA_YEAR), str(DATA_YEAR), regex=False),
        "NODE": "TH_SP15_GEN-APND",
        "LMP_TYPE": "LMP",
        "MW": lmp.round(2),
    })
    # Fix the timestamp format — use proper ISO format
    df["INTERVALSTARTTIME_GMT"] = timestamps.strftime("%Y-%m-%dT%H:00:00Z")
    df.to_csv(output_path, index=False)

    summer_mask = ((month >= 6) & (month <= 9)) & (hour >= 14) & (hour < 21)
    print(f"  [OK] Synthetic CAISO {DATA_YEAR} prices: {output_path}")
    print(
        f"    Annual avg: ${lmp.mean():.1f}/MWh, "
        f"Summer on-peak avg: ${lmp[summer_mask].mean():.1f}/MWh"
    )


# ── 4. Solar Generation -- NREL PVWatts ──────────────────────────────────
def download_solar():
    """
    Downloads PVWatts hourly AC output for a 100kW system in Mission Viejo.
    All timestamps use DATA_YEAR for calendar consistency with meter data.
    """
    output_path = DATA / "solar" / "pvwatts_100kw_socal.csv"
    if output_path.exists():
        print(f"  [OK] Solar data already exists: {output_path}")
        return

    print("  Downloading PVWatts solar (100kW, Mission Viejo CA)...")
    api_key = os.getenv("NREL_API_KEY", "DEMO_KEY")
    url = "https://developer.nrel.gov/api/pvwatts/v8.json"
    params = {
        "api_key": api_key,
        "lat": 33.60,
        "lon": -117.67,
        "system_capacity": 100,
        "azimuth": 180,
        "tilt": 20,
        "array_type": 1,
        "module_type": 0,
        "losses": 14,
        "timeframe": "hourly",
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if "outputs" not in data:
            raise ValueError(f"PVWatts error: {data.get('errors', data)}")

        ac_kwh = [x / 1000 for x in data["outputs"]["ac"]]
        timestamps = pd.date_range(
            f"{DATA_YEAR}-01-01", periods=8760, freq="h"
        )
        solar_df = pd.DataFrame({
            "timestamp": timestamps,
            "ac_output_kw": ac_kwh,
            "system_capacity_kw": 100,
            "location": "Mission Viejo, CA",
            "lat": 33.60,
            "lon": -117.67,
            "data_year": DATA_YEAR,
        })
        solar_df.to_csv(output_path, index=False)
        print(f"  [OK] Saved: {output_path}")
        print(
            f"    Annual generation: {sum(ac_kwh):.0f} kWh"
            f" ({sum(ac_kwh)/100:.0f} kWh/kW)"
        )
    except Exception as e:
        print(f"  PVWatts download failed ({e})")
        print("  Generating synthetic solar profile...")
        _generate_synthetic_solar(output_path)


def _generate_synthetic_solar(output_path: Path):
    """
    Generates realistic hourly PV output for Southern California.
    Timestamps use DATA_YEAR. Based on PVWatts stats for Mission Viejo:
      Annual yield: ~1,650 kWh/kW (excellent SoCal site)
      For 100 kW system: ~165,000 kWh/year
    """
    import numpy as np

    np.random.seed(456)
    timestamps = pd.date_range(
        f"{DATA_YEAR}-01-01", periods=8760, freq="h"
    )
    hour = timestamps.hour.to_numpy(dtype=float)
    doy = timestamps.dayofyear.to_numpy(dtype=float)

    declination = 23.45 * np.sin(2 * np.pi * (doy - 81) / 365)
    latitude = 33.6  # Mission Viejo, CA
    hour_angle = (hour - 12) * 15  # degrees

    dec_rad = np.radians(declination)
    lat_rad = np.radians(latitude)
    ha_rad = np.radians(hour_angle)

    cos_zenith = (
        np.sin(lat_rad) * np.sin(dec_rad)
        + np.cos(lat_rad) * np.cos(dec_rad) * np.cos(ha_rad)
    )
    cos_zenith = np.maximum(0.0, cos_zenith)

    ghi = 1000.0 * cos_zenith * 0.75  # W/m^2 (75% atmospheric transmission)
    # DC output: at STC (1000 W/m²) the system produces its rated kW.
    # Scale linearly: dc = (GHI / 1000) * system_capacity_kw
    dc = (ghi / 1000.0) * 100.0   # kW, 100 kW rated system
    ac = dc * 0.96                 # 96% inverter efficiency

    cloud_factor = np.maximum(0.2, np.random.beta(8, 2, len(timestamps)))
    ac = np.maximum(0.0, ac * cloud_factor)

    solar_df = pd.DataFrame({
        "timestamp": timestamps,
        "ac_output_kw": ac.round(2),
        "system_capacity_kw": 100,
        "location": f"Mission Viejo, CA (synthetic {DATA_YEAR})",
        "data_year": DATA_YEAR,
    })
    solar_df.to_csv(output_path, index=False)
    annual = float(ac.sum())
    print(f"  [OK] Synthetic solar generated: {output_path}")
    print(
        f"    Year: {DATA_YEAR}  |  "
        f"Annual: {annual:.0f} kWh ({annual/100:.0f} kWh/kW)"
    )


# ── 5. SCE TOU-GS-3 Tariff JSON ──────────────────────────────────────────
def write_tariff_json():
    """
    Writes SCE TOU-GS-3 tariff parameters as JSON.
    Rates from SCE Schedule TOU-GS-3 (effective 2023-01-01).
    Verify at: https://www.sce.com/regulatory/tariff-books
    """
    output_path = DATA / "tariff" / "sce_tou_gs3.json"
    if output_path.exists():
        print(f"  [OK] Tariff JSON already exists: {output_path}")
        return

    tariff = {
        "name": "SCE TOU-GS-3",
        "description": "Time-of-Use General Service, Large Commercial",
        "utility": "Southern California Edison",
        "market": "CAISO",
        "currency": "USD",
        "effective_date": "2023-01-01",
        "data_year": DATA_YEAR,
        "source": (
            "https://www.sce.com/regulatory/tariff-books/"
            "rates-general-service"
        ),
        "demand_charges": {
            "summer": {
                "months": [6, 7, 8, 9],
                "on_peak_kw": 19.10,
                "mid_peak_kw": 5.80,
                "all_time_kw": 8.85,
                "on_peak_hours": "14:00-20:00 weekdays",
                "mid_peak_hours": "10:00-14:00 and 20:00-21:00 weekdays",
            },
            "winter": {
                "months": [1, 2, 3, 4, 5, 10, 11, 12],
                "mid_peak_kw": 5.80,
                "all_time_kw": 8.85,
                "mid_peak_hours": "10:00-21:00 weekdays",
            },
        },
        "energy_charges_per_kwh": {
            "summer": {
                "on_peak": {
                    "hours": "14:00-20:00",
                    "weekdays_only": True,
                    "rate": 0.28317,
                },
                "mid_peak": {
                    "hours": "10:00-14:00 and 20:00-21:00",
                    "weekdays_only": True,
                    "rate": 0.15498,
                },
                "off_peak": {
                    "hours": "all other hours",
                    "weekdays_only": False,
                    "rate": 0.09871,
                },
            },
            "winter": {
                "mid_peak": {
                    "hours": "10:00-21:00",
                    "weekdays_only": True,
                    "rate": 0.13245,
                },
                "off_peak": {
                    "hours": "all other hours",
                    "weekdays_only": False,
                    "rate": 0.09871,
                },
            },
        },
        "fixed_charges": {
            "customer_charge_monthly_usd": 302.72,
        },
        "notes": {
            "demand_charge_basis": (
                "Highest single 15-minute average kW in billing period"
            ),
            "summer_on_peak_demand": (
                "Additional $19.10/kW for highest kW during on-peak hours"
            ),
            "dsgs_program": (
                "DSGS (Demand Side Grid Support) available for DR revenue"
            ),
            "dsgs_rate_per_kwh": 2.00,
        },
    }

    with open(output_path, "w") as f:
        json.dump(tariff, f, indent=2)
    print(f"  [OK] Written: {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n=== Elexity Analysis -- Data Download (year={DATA_YEAR}) ===\n")

    print("1. Building meter data (NREL ComStock):")
    download_nrel_comstock()

    print("\n2. Weather data (LA TMY3 EPW):")
    download_weather()

    print(f"\n3. CAISO day-ahead prices (SP15/SCE zone, {DATA_YEAR}):")
    download_caiso_prices()

    print("\n4. Solar generation (PVWatts, 100kW, Mission Viejo CA):")
    download_solar()

    print("\n5. SCE TOU-GS-3 tariff JSON:")
    write_tariff_json()

    print("\n=== Download complete ===")
    print("\nData files:")
    for f in sorted(DATA.rglob("*")):
        if f.is_file() and "metadata" not in f.name:
            size_kb = f.stat().st_size / 1024
            print(f"  {f.relative_to(ROOT)}  ({size_kb:.0f} KB)")

    print(f"\nAll data aligned to year: {DATA_YEAR}")
    print("Next step: uv run python analysis/bill_calculator.py")
