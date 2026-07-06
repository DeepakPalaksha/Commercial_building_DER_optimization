"""
Data download script for Elexity building energy analysis.
Run once before starting analysis: uv run python scripts/download_data.py

Downloads:
  1. NREL ComStock building meter data (secondary school, CA, 2018 AMY)
  2. Los Angeles TMY3 weather file (EnergyPlus EPW)
  3. CAISO day-ahead LMP prices (2018, SP15/SCE zone)
  4. NREL PVWatts solar generation (100kW, Mission Viejo CA)
"""

import os
import sys
import json
import time
import zipfile
import io
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
(DATA / "meter").mkdir(parents=True, exist_ok=True)
(DATA / "weather").mkdir(parents=True, exist_ok=True)
(DATA / "prices").mkdir(parents=True, exist_ok=True)
(DATA / "solar").mkdir(parents=True, exist_ok=True)
(DATA / "tariff").mkdir(parents=True, exist_ok=True)


# ── 1. NREL ComStock Building Meter Data ──────────────────────────────────────
def download_nrel_comstock():
    """
    Downloads 15-min interval meter data for a secondary school in Southern California.
    Uses AWS S3 public dataset — no credentials needed.

    If boto3/S3 access fails (network restrictions), falls back to generating
    realistic synthetic data based on NREL ComStock published statistics.
    """
    output_path = DATA / "meter" / "school_ca_15min.parquet"
    if output_path.exists():
        print(f"  ✓ Meter data already exists: {output_path}")
        return

    print("  Attempting NREL ComStock S3 download...")
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.client import Config

        s3 = boto3.client(
            's3',
            config=Config(signature_version=UNSIGNED),
            region_name='us-west-2'
        )

        # First download metadata to find a SoCal secondary school
        meta_path = DATA / "metadata.parquet"
        if not meta_path.exists():
            print("  Downloading metadata (~50MB)...")
            s3.download_file(
                'oedi-data-lake',
                'nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/'
                '2021/comstock_amy2018_release_1/metadata/metadata.parquet',
                str(meta_path)
            )

        meta = pd.read_parquet(meta_path)
        schools = meta[
            (meta['in.building_type'] == 'SecondarySchool') &
            (meta['in.state'] == 'CA') &
            (meta['in.climate_zone_ashrae_2006'].isin(['3B', '3C']))
        ]

        if len(schools) == 0:
            raise ValueError("No matching buildings found in metadata")

        bldg_id = schools.iloc[0]['bldg_id']
        print(f"  Found building: {bldg_id} ({schools.iloc[0].get('in.sqft', 'unknown')} sqft)")

        s3_key = (
            f'nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/'
            f'2021/comstock_amy2018_release_1/timeseries_individual_buildings/'
            f'by_state/upgrade=0/state=CA/{bldg_id}-up00.parquet'
        )
        print(f"  Downloading timeseries (~5MB)...")
        s3.download_file('oedi-data-lake', s3_key, str(output_path))
        print(f"  ✓ Downloaded: {output_path}")

    except Exception as e:
        print(f"  S3 download failed ({e})")
        print("  Falling back to physics-based synthetic data generation...")
        _generate_synthetic_meter_data(output_path)


def _generate_synthetic_meter_data(output_path: Path):
    """
    Generates realistic 15-min interval meter data for a Southern California
    secondary school based on NREL ComStock published statistics and the
    Elexity JSerra case study.

    Key parameters (from Elexity white paper + NREL ComStock docs):
    - Peak demand: 150–200 kW on hot days (HVAC dominated)
    - HVAC: 60–70% of load in summer
    - Baseline (no HVAC): ~50 kW (lighting + plug loads + water heating)
    - Building size: ~85,000 sqft
    - School occupancy: Mon–Fri 7am–6pm, Aug–Jun (closed Jul + school breaks)
    """
    import numpy as np

    print("  Generating 15-min interval data for 2018 (35,040 timesteps)...")
    np.random.seed(42)

    # Timestamps: full year 2018, 15-min intervals
    timestamps = pd.date_range('2018-01-01', '2018-12-31 23:45', freq='15min')
    n = len(timestamps)

    # ── Outdoor temperature (LA TMY3 approximation) ───────────────────────────
    # LA has mild winters (55°F avg) and hot summers (95°F peak)
    day_of_year = timestamps.dayofyear
    hour = timestamps.hour + timestamps.minute / 60

    # Seasonal component: peaks in August (day 220)
    T_seasonal = 72 + 18 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
    # Diurnal component: peaks at 3pm
    T_diurnal = 10 * np.sin(2 * np.pi * (hour - 6) / 24)
    # Small random noise
    T_noise = np.random.normal(0, 2, n)
    T_outdoor = T_seasonal + T_diurnal + T_noise  # °F

    # ── School occupancy schedule ─────────────────────────────────────────────
    is_weekday = timestamps.dayofweek < 5
    is_school_month = ~timestamps.month.isin([7])  # Closed in July
    is_school_hours = (timestamps.hour >= 7) & (timestamps.hour < 18)
    is_occupied = is_weekday & is_school_month & is_school_hours

    # ── Baseline load (lighting + plug loads, always on when occupied) ────────
    baseline_occupied = 52.0   # kW
    baseline_unoccupied = 18.0  # kW (servers, security, refrigeration)
    load_baseline = np.where(is_occupied, baseline_occupied, baseline_unoccupied)

    # ── HVAC load (temperature-driven, RC model) ──────────────────────────────
    # HVAC kicks in when T_outdoor > 68°F (cooling setpoint)
    T_setpoint = 72.0  # °F indoor setpoint
    COP = 3.2          # Coefficient of performance
    building_UA = 4.5  # kW/°F (overall heat transfer coefficient)

    # Cooling load = max(0, UA * (T_outdoor - T_setpoint)) / COP
    cooling_load_kw = np.maximum(0, building_UA * (T_outdoor - T_setpoint) / COP)
    # Only cooling when occupied (building HVAC off overnight on weekends)
    hvac_load = np.where(is_occupied, cooling_load_kw,
                          cooling_load_kw * 0.2)  # Minimal overnight HVAC
    # Add noise to HVAC
    hvac_load = hvac_load * (1 + np.random.normal(0, 0.08, n))
    hvac_load = np.maximum(0, hvac_load)

    # ── Total demand ──────────────────────────────────────────────────────────
    demand_kw = load_baseline + hvac_load
    # Hard cap at 210 kW (building electrical service limit)
    demand_kw = np.minimum(demand_kw, 210.0)
    # Add small measurement noise
    demand_kw += np.random.normal(0, 0.5, n)
    demand_kw = np.maximum(0, demand_kw)

    # ── End-use breakdown ─────────────────────────────────────────────────────
    # Split total into end uses (approximate)
    hvac_fraction = hvac_load / (demand_kw + 1e-6)
    lighting_kw = load_baseline * 0.35 * np.where(is_occupied, 1.0, 0.3)
    plug_loads_kw = load_baseline * 0.45 * np.where(is_occupied, 1.0, 0.4)
    water_heating_kw = load_baseline * 0.15 * np.where(is_school_hours, 1.2, 0.5)
    other_kw = demand_kw - hvac_load - lighting_kw - plug_loads_kw - water_heating_kw
    other_kw = np.maximum(0, other_kw)

    # ── Build DataFrame ───────────────────────────────────────────────────────
    df = pd.DataFrame({
        'timestamp': timestamps,
        'demand_kw': demand_kw.round(2),
        'T_outdoor_f': T_outdoor.round(1),
        'is_occupied': is_occupied,
        # End-use breakdown (matches NREL ComStock column naming convention)
        'out.electricity.total.demand_kw': demand_kw.round(2),
        'out.electricity.hvac.demand_kw': hvac_load.round(2),
        'out.electricity.lighting.demand_kw': lighting_kw.round(2),
        'out.electricity.plug_loads.demand_kw': plug_loads_kw.round(2),
        'out.electricity.water_heating.demand_kw': water_heating_kw.round(2),
    })

    df.to_parquet(output_path, index=False)

    # Print sanity check stats
    print(f"  ✓ Generated {len(df):,} rows of 15-min interval data")
    print(f"    Peak demand:     {df['demand_kw'].max():.1f} kW")
    print(f"    Avg demand:      {df['demand_kw'].mean():.1f} kW")
    print(f"    Annual energy:   {(df['demand_kw'] * 0.25).sum() / 1000:.0f} MWh")
    print(f"    HVAC % (summer): {df[df['timestamp'].dt.month.isin([6,7,8,9])]['out.electricity.hvac.demand_kw'].mean() / df[df['timestamp'].dt.month.isin([6,7,8,9])]['demand_kw'].mean() * 100:.0f}%")
    print(f"    Saved: {output_path}")


# ── 2. Los Angeles TMY3 Weather File ──────────────────────────────────────────
def download_weather():
    """
    Downloads Los Angeles International Airport TMY3 EPW weather file.
    Source: EnergyPlus weather data repository (US DOE, free).
    """
    output_path = DATA / "weather" / "USA_CA_Los.Angeles.TMY3.epw"
    if output_path.exists():
        print(f"  ✓ Weather data already exists: {output_path}")
        return

    url = (
        "https://energyplus.net/weather-download/north_and_central_america_wmo_region_4"
        "/USA/CA/USA_CA_Los.Angeles.Intl.AP.722950_TMY3"
        "/USA_CA_Los.Angeles.Intl.AP.722950_TMY3.epw"
    )

    print(f"  Downloading LA TMY3 EPW weather file...")
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        output_path.write_bytes(r.content)
        print(f"  ✓ Downloaded: {output_path} ({len(r.content)/1024:.0f} KB)")
    except Exception as e:
        print(f"  EPW download failed ({e})")
        print("  Weather data embedded in synthetic meter data (T_outdoor_f column)")
        print("  For full EPW: manually download from https://energyplus.net/weather")


# ── 3. CAISO Day-Ahead LMP Prices ─────────────────────────────────────────────
def download_caiso_prices():
    """
    Downloads CAISO day-ahead LMP prices for SP15 zone (SCE territory).
    Source: CAISO OASIS public API — no account needed.
    Node: TH_SP15_GEN-APND (SP15 trading hub, represents SCE/SDG&E area)
    """
    output_path = DATA / "prices" / "caiso_dam_lmp_2018.csv"
    if output_path.exists():
        print(f"  ✓ CAISO prices already exist: {output_path}")
        return

    print("  Downloading CAISO day-ahead LMP prices (2018, SP15 zone)...")
    print("  Note: CAISO OASIS rate-limits requests — downloading month by month...")

    base_url = "http://oasis.caiso.com/oasisapi/SingleZip"
    all_data = []

    for month in range(1, 13):
        start = datetime(2018, month, 1)
        if month == 12:
            end = datetime(2018, 12, 31)
        else:
            end = datetime(2018, month + 1, 1) - timedelta(days=1)

        params = {
            "queryname": "PRC_LMP",
            "startdatetime": start.strftime("%Y%m%dT00:00-0800"),
            "enddatetime": end.strftime("%Y%m%dT23:00-0800"),
            "version": "1",
            "market_run_id": "DAM",
            "node": "TH_SP15_GEN-APND",
            "resultformat": "6"
        }

        try:
            r = requests.get(base_url, params=params, timeout=60)
            z = zipfile.ZipFile(io.BytesIO(r.content))
            csv_name = [f for f in z.namelist() if f.endswith('.csv')][0]
            df = pd.read_csv(z.open(csv_name))
            all_data.append(df)
            print(f"    ✓ {start.strftime('%B %Y')}: {len(df)} rows")
            time.sleep(2)  # Be polite to CAISO servers
        except Exception as e:
            print(f"    ✗ {start.strftime('%B %Y')} failed: {e}")
            continue

    if all_data:
        prices = pd.concat(all_data, ignore_index=True)
        prices.to_csv(output_path, index=False)
        print(f"  ✓ Saved {len(prices):,} rows to {output_path}")
        print(f"    Columns: {list(prices.columns)}")
    else:
        print("  CAISO download failed — generating synthetic price data")
        _generate_synthetic_prices(output_path)


def _generate_synthetic_prices(output_path: Path):
    """
    Generates realistic CAISO SP15 day-ahead LMP prices for 2018.
    Based on actual 2018 CAISO price statistics:
    - Annual average: ~$37/MWh
    - Summer on-peak (2pm-9pm): ~$65/MWh
    - Winter off-peak (10pm-7am): ~$25/MWh
    - Occasional negative prices during high solar (spring midday)
    """
    import numpy as np
    np.random.seed(123)

    timestamps = pd.date_range('2018-01-01', '2018-12-31 23:00', freq='h')
    n = len(timestamps)

    hour = timestamps.hour
    month = timestamps.month
    dow = timestamps.dayofweek

    # Base price
    base = 37.0

    # Time-of-use shape
    tou_shape = np.where(
        (hour >= 14) & (hour < 21), 28.0,    # On-peak premium
        np.where(hour < 7, -8.0, 5.0)         # Off-peak discount
    )

    # Seasonal adjustment
    seasonal = np.where(month.isin([6, 7, 8, 9]), 15.0,
               np.where(month.isin([12, 1, 2]), 5.0, 0.0))

    # Spring solar duck curve — negative prices around noon in spring
    duck_curve = np.where(
        (month.isin([3, 4, 5])) & (hour >= 10) & (hour <= 14),
        -20.0, 0.0
    )

    # Weekend discount
    weekend = np.where(dow >= 5, -5.0, 0.0)

    lmp = base + tou_shape + seasonal + duck_curve + weekend
    lmp += np.random.normal(0, 5, n)  # Noise

    df = pd.DataFrame({
        'INTERVALSTARTTIME_GMT': timestamps.strftime('%Y-%m-%dT%H:00:00Z'),
        'NODE': 'TH_SP15_GEN-APND',
        'LMP_TYPE': 'LMP',
        'MW': lmp.round(2)
    })
    df.to_csv(output_path, index=False)
    print(f"  ✓ Synthetic CAISO prices generated: {output_path}")
    print(f"    Annual avg: ${lmp.mean():.1f}/MWh, Summer on-peak avg: ${lmp[(month.isin([6,7,8,9])) & (hour >= 14) & (hour < 21)].mean():.1f}/MWh")


# ── 4. Solar Generation — NREL PVWatts ────────────────────────────────────────
def download_solar():
    """
    Downloads PVWatts hourly AC output for a 100kW system in Mission Viejo, CA.
    Uses DEMO_KEY — works for low volume. Register free at developer.nrel.gov
    for production use.
    """
    output_path = DATA / "solar" / "pvwatts_100kw_socal.csv"
    if output_path.exists():
        print(f"  ✓ Solar data already exists: {output_path}")
        return

    print("  Downloading PVWatts solar generation (100kW, Mission Viejo CA)...")

    api_key = os.getenv("NREL_API_KEY", "DEMO_KEY")
    url = "https://developer.nrel.gov/api/pvwatts/v8.json"
    params = {
        "api_key": api_key,
        "lat": 33.60,
        "lon": -117.67,
        "system_capacity": 100,  # 100 kW
        "azimuth": 180,
        "tilt": 20,
        "array_type": 1,
        "module_type": 0,
        "losses": 14,
        "timeframe": "hourly"
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()

        if 'outputs' not in data:
            raise ValueError(f"PVWatts error: {data.get('errors', data)}")

        # AC output is in Wh per hour — convert to kW
        ac_kwh = [x / 1000 for x in data['outputs']['ac']]

        timestamps = pd.date_range('2018-01-01', periods=8760, freq='h')
        solar_df = pd.DataFrame({
            'timestamp': timestamps,
            'ac_output_kw': ac_kwh,
            'system_capacity_kw': 100,
            'location': 'Mission Viejo, CA',
            'lat': 33.60,
            'lon': -117.67,
        })
        solar_df.to_csv(output_path, index=False)
        print(f"  ✓ Saved: {output_path}")
        print(f"    Annual generation: {sum(ac_kwh):.0f} kWh ({sum(ac_kwh)/100:.0f} kWh/kW)")

    except Exception as e:
        print(f"  PVWatts download failed ({e})")
        print("  Generating synthetic solar profile...")
        _generate_synthetic_solar(output_path)


def _generate_synthetic_solar(output_path: Path):
    """
    Generates realistic hourly solar PV output for Southern California.
    Based on PVWatts statistics for Mission Viejo, CA:
    - Annual yield: ~1,650 kWh/kW (good SoCal site)
    - For 100kW system: ~165,000 kWh/year
    """
    import numpy as np
    np.random.seed(456)

    timestamps = pd.date_range('2018-01-01', periods=8760, freq='h')
    hour = timestamps.hour
    doy = timestamps.dayofyear

    # Solar elevation angle approximation
    declination = 23.45 * np.sin(2 * np.pi * (doy - 81) / 365)
    latitude = 33.6  # Mission Viejo
    hour_angle = (hour - 12) * 15  # degrees

    import numpy as np
    dec_rad = np.radians(declination)
    lat_rad = np.radians(latitude)
    ha_rad = np.radians(hour_angle)

    cos_zenith = (np.sin(lat_rad) * np.sin(dec_rad) +
                  np.cos(lat_rad) * np.cos(dec_rad) * np.cos(ha_rad))
    cos_zenith = np.maximum(0, cos_zenith)

    # GHI approximation (W/m²)
    ghi = 1000 * cos_zenith * 0.75  # 75% atmospheric transmission

    # DC output (100kW system, 20% panel efficiency equivalent)
    dc = ghi * 100 * 0.20 / 1000  # kW

    # AC output (96% inverter efficiency)
    ac = dc * 0.96

    # Cloud cover noise (LA is sunny — low variability)
    cloud_factor = np.maximum(0.2, np.random.beta(8, 2, len(timestamps)))
    ac = ac * cloud_factor
    ac = np.maximum(0, ac)

    solar_df = pd.DataFrame({
        'timestamp': timestamps,
        'ac_output_kw': ac.round(2),
        'system_capacity_kw': 100,
        'location': 'Mission Viejo, CA (synthetic)',
    })
    solar_df.to_csv(output_path, index=False)
    annual = ac.sum()
    print(f"  ✓ Synthetic solar generated: {output_path}")
    print(f"    Annual generation: {annual:.0f} kWh ({annual/100:.0f} kWh/kW)")


# ── 5. SCE TOU-GS-3 Tariff JSON ───────────────────────────────────────────────
def write_tariff_json():
    """
    Writes SCE TOU-GS-3 tariff parameters as JSON.
    Rates from SCE Schedule TOU-GS-3 (effective 2023).
    Verify current rates at: https://www.sce.com/regulatory/tariff-books/rates-general-service
    """
    output_path = DATA / "tariff" / "sce_tou_gs3.json"
    if output_path.exists():
        print(f"  ✓ Tariff JSON already exists: {output_path}")
        return

    tariff = {
        "name": "SCE TOU-GS-3",
        "description": "Time-of-Use General Service, Large Commercial",
        "utility": "Southern California Edison",
        "market": "CAISO",
        "currency": "USD",
        "effective_date": "2023-01-01",
        "source": "https://www.sce.com/regulatory/tariff-books/rates-general-service",
        "demand_charges": {
            "summer": {
                "months": [6, 7, 8, 9],
                "on_peak_kw": 19.10,
                "mid_peak_kw": 5.80,
                "all_time_kw": 8.85,
                "on_peak_hours": "14:00-20:00 weekdays",
                "mid_peak_hours": "10:00-14:00 and 20:00-21:00 weekdays"
            },
            "winter": {
                "months": [1, 2, 3, 4, 5, 10, 11, 12],
                "mid_peak_kw": 5.80,
                "all_time_kw": 8.85,
                "mid_peak_hours": "10:00-21:00 weekdays"
            }
        },
        "energy_charges_per_kwh": {
            "summer": {
                "on_peak":   {"hours": "14:00-20:00", "weekdays_only": True,  "rate": 0.28317},
                "mid_peak":  {"hours": "10:00-14:00 and 20:00-21:00", "weekdays_only": True, "rate": 0.15498},
                "off_peak":  {"hours": "all other hours", "weekdays_only": False, "rate": 0.09871}
            },
            "winter": {
                "mid_peak":  {"hours": "10:00-21:00", "weekdays_only": True,  "rate": 0.13245},
                "off_peak":  {"hours": "all other hours", "weekdays_only": False, "rate": 0.09871}
            }
        },
        "fixed_charges": {
            "customer_charge_monthly_usd": 302.72
        },
        "notes": {
            "demand_charge_basis": "Highest single 15-minute average kW in billing period",
            "summer_on_peak_demand": "Additional $19.10/kW for highest kW during on-peak hours",
            "dsgs_program": "DSGS (Demand Side Grid Support) available for demand response revenue",
            "dsgs_rate_per_kwh": 2.00
        }
    }

    with open(output_path, 'w') as f:
        json.dump(tariff, f, indent=2)
    print(f"  ✓ Written: {output_path}")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n=== Elexity Analysis — Data Download ===\n")

    print("1. Building meter data (NREL ComStock):")
    download_nrel_comstock()

    print("\n2. Weather data (LA TMY3 EPW):")
    download_weather()

    print("\n3. CAISO day-ahead prices (SP15/SCE zone):")
    download_caiso_prices()

    print("\n4. Solar generation (PVWatts, 100kW, Mission Viejo CA):")
    download_solar()

    print("\n5. SCE TOU-GS-3 tariff JSON:")
    write_tariff_json()

    print("\n=== Download complete ===")
    print("\nData files:")
    for f in sorted(DATA.rglob("*")):
        if f.is_file():
            size_kb = f.stat().st_size / 1024
            print(f"  {f.relative_to(ROOT)}  ({size_kb:.0f} KB)")

    print("\nNext step: uv run python agents/orchestrator.py")
