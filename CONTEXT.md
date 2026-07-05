# Elexity Building Energy Analysis — Cursor Project Context

## What This Project Is

This is a production-grade commercial building energy analysis tool built for a
technical interview exercise at Elexity (elexity.io) — a Portland, Oregon-based
company that builds predictive energy control software for C&I buildings.

The exercise: given a commercial building's 15-minute interval meter data, identify
what is driving electricity costs, recommend investments that would save money, and
quantify the savings and payback period.

This goes beyond the basic exercise — it implements the full Elexity methodology
(load control + storage + solar + grid services "value stack"), includes a thermal
model for HVAC pre-cooling simulation, a MILP optimizer for battery dispatch, and
a Streamlit dashboard for real-time interactive savings simulation.

**Target building:** Secondary school, Southern California (SCE territory, CAISO market)
This mirrors Elexity's published JSerra Catholic High School case study exactly.

---

## Market / Geography Consistency — Critical

Everything must be geographically consistent:
- **Building location:** Southern California (Mission Viejo / Orange County area)
- **Utility:** Southern California Edison (SCE)
- **Tariff:** SCE TOU-GS-3 (Time-of-Use General Service, demand charge tariff)
- **Wholesale market:** CAISO (California ISO)
- **Grid services:** DSGS (Demand Side Grid Support) — California-specific DR program
- **Weather:** Los Angeles TMY3 (dry, hot summers, mild winters)

Do NOT mix Oregon tariffs with California buildings. Do NOT use PG&E rates for SCE territory.

---

## Project Structure

```
elexity-analysis/
│
├── CONTEXT.md                  ← This file. Read before touching anything.
│
├── pyproject.toml              ← uv package management (NOT pip, NOT poetry)
├── .python-version             ← pin to 3.11
├── .env                        ← API keys (NREL_API_KEY, never commit)
├── .gitignore
│
├── data/
│   ├── README_DATA.md          ← Data download instructions (see below)
│   ├── meter/
│   │   └── school_ca_15min.parquet   ← NREL ComStock 15-min interval data
│   ├── weather/
│   │   └── USA_CA_Los.Angeles.TMY3.epw   ← EnergyPlus weather file
│   ├── prices/
│   │   └── caiso_dam_lmp_2023.csv    ← CAISO day-ahead LMPs ($/MWh)
│   ├── tariff/
│   │   └── sce_tou_gs3.json          ← SCE tariff parameters (hand-encoded)
│   └── solar/
│       └── pvwatts_100kw_socal.csv   ← NREL PVWatts hourly AC output
│
├── models/
│   ├── thermal_model.py        ← RC building thermal model
│   ├── battery_model.py        ← Battery SoC, charge/discharge constraints
│   ├── solar_model.py          ← PV generation profile
│   └── optimizer.py            ← MILP dispatch optimizer (cvxpy)
│
├── analysis/
│   ├── bill_calculator.py      ← Reconstruct SCE bill from interval data
│   ├── cost_driver.py          ← Decompose energy vs demand charges, plot load profile
│   ├── control_strategy.py     ← Seasonal control strategies (summer/winter/shoulder)
│   └── savings_calculator.py   ← Bill with/without each intervention, waterfall chart
│
├── agents/
│   ├── orchestrator.py         ← LangGraph orchestrator agent
│   ├── data_agent.py           ← Loads and validates all data sources
│   ├── tariff_agent.py         ← Parses tariff, reconstructs bill
│   ├── thermal_agent.py        ← Fits RC model, runs pre-cooling simulation
│   ├── optimizer_agent.py      ← Runs MILP dispatch for each scenario
│   └── report_agent.py         ← Generates savings narrative and charts
│
├── streamlit_app/
│   └── app.py                  ← Interactive Streamlit dashboard
│
├── outputs/
│   └── {run_timestamp}/
│       ├── params.json
│       ├── bill_baseline.json
│       ├── bill_optimized.json
│       ├── savings_summary.json
│       └── figures/
│
├── notebooks/
│   └── analysis.ipynb          ← The 90-minute exercise deliverable
│
└── Dockerfile
```

---

## Package Management — uv Only

Use `uv` exclusively. No pip, no poetry, no conda.

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create project
uv init elexity-analysis
cd elexity-analysis
uv python pin 3.11

# Add all dependencies
uv add pandas numpy scipy matplotlib seaborn plotly
uv add cvxpy pulp                    # MILP optimization
uv add pvlib                         # Solar/PV modelling
uv add streamlit                     # Dashboard
uv add langgraph langchain-anthropic # Agent orchestration
uv add boto3                         # S3 data access
uv add pyarrow fastparquet           # Parquet file handling
uv add python-dotenv
uv add requests

# Run anything with
uv run python analysis/bill_calculator.py
uv run streamlit run streamlit_app/app.py
```

---

## Data Download Instructions

### 1. NREL ComStock Building Meter Data (15-min interval)

> **Data year policy:** All project data is standardised to calendar
> year **2023** for timestamp consistency. Meter, CAISO prices, and
> solar output must share the same year so savings calculations can be
> directly verified. The NREL ComStock S3 dataset is internally named
> `comstock_amy2018_release_1` (AMY = Actual Meteorological Year 2018)
> — this is a fixed dataset label, not a choice. If real NREL data is
> downloaded, its timestamps will be 2018 and must be reindexed to 2023
> before use. The synthetic fallback already generates 2023 timestamps.

The data is on AWS S3 as a public dataset — no AWS account needed.

**Step 1: Install AWS CLI**
```bash
# Mac
brew install awscli

# Linux
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install
```

**Step 2: Download the metadata file to find secondary school building IDs**
```bash
aws s3 cp --no-sign-request \
  s3://oedi-data-lake/nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021/comstock_amy2018_release_1/metadata/metadata.parquet \
  data/metadata.parquet
```

**Step 3: Run this Python script to find the right building IDs**
```python
import pandas as pd

meta = pd.read_parquet('data/metadata.parquet')
print(meta.columns.tolist())  # See all available columns first

schools_ca = meta[
    (meta['in.building_type'] == 'SecondarySchool') &
    (meta['in.state'] == 'CA') &
    (meta['in.climate_zone_ashrae_2006'].isin(['3B', '3C']))
]
print(f"Found {len(schools_ca)} secondary schools in SoCal climate zones")
print(schools_ca[['bldg_id', 'in.sqft', 'in.climate_zone_ashrae_2006',
                   'in.hvac_system_type', 'in.heating_fuel']].head(10))

# Save the building IDs
schools_ca[['bldg_id']].to_csv('data/school_building_ids.csv', index=False)
```

**Step 4: Download the timeseries for one building**
```bash
# Replace bldg0000001 with actual ID from Step 3
aws s3 cp --no-sign-request \
  s3://oedi-data-lake/nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021/comstock_amy2018_release_1/timeseries_individual_buildings/by_state/upgrade=0/state=CA/bldg0000001-up00.parquet \
  data/meter/school_ca_15min.parquet
```

**Alternative: Use Python directly (no AWS CLI needed)**
```python
import boto3
from botocore import UNSIGNED
from botocore.client import Config

s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED), region_name='us-west-2')

# Download metadata
s3.download_file(
    'oedi-data-lake',
    'nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021/comstock_amy2018_release_1/metadata/metadata.parquet',
    'data/metadata.parquet'
)
```

**What the data looks like once loaded:**
```
timestamp                    object  (15-min intervals, full year = 35,040 rows)
out.electricity.total.energy_consumption  float64  (kWh per 15-min interval)
out.electricity.hvac.energy_consumption   float64  (HVAC subset)
out.electricity.lighting.energy_consumption float64
out.electricity.plug_loads.energy_consumption float64
out.electricity.water_heating.energy_consumption float64
```

Convert kWh per 15-min to kW demand: multiply by 4.

---

### 2. Weather Data — Los Angeles TMY3 EPW

**Direct download (no account needed):**
```bash
# EnergyPlus weather file — Los Angeles International Airport TMY3
curl -L -o data/weather/USA_CA_Los.Angeles.TMY3.epw \
  "https://energyplus.net/weather-download/north_and_central_america_wmo_region_4/USA/CA/USA_CA_Los.Angeles.Intl.AP.722950_TMY3/USA_CA_Los.Angeles.Intl.AP.722950_TMY3.epw"
```

**Parse it with pvlib:**
```python
import pvlib

weather, metadata = pvlib.iotools.read_epw('data/weather/USA_CA_Los.Angeles.TMY3.epw')
# weather is a DataFrame with columns: temp_air, wind_speed, ghi, dni, dhi, etc.
# temp_air is in °C — convert to °F: temp_f = weather['temp_air'] * 9/5 + 32
```

---

### 3. CAISO Day-Ahead LMP Prices

CAISO OASIS — free, no account, but the API is rate-limited so download month by month.

**Python download script:**
```python
import requests
import zipfile
import io
import pandas as pd
from datetime import datetime, timedelta

def download_caiso_lmp(start_date, end_date, node='TH_SP15_GEN-APND'):
    """
    Downloads CAISO day-ahead LMP prices for SCE zone (SP15 aggregation point).
    TH_SP15_GEN-APND = SP15 trading hub, which represents SCE/SDG&E territory.
    """
    url = "http://oasis.caiso.com/oasisapi/SingleZip"
    params = {
        "queryname": "PRC_LMP",
        "startdatetime": start_date.strftime("%Y%m%dT00:00-0800"),
        "enddatetime": end_date.strftime("%Y%m%dT23:00-0800"),
        "version": "1",
        "market_run_id": "DAM",
        "node": node,
        "resultformat": "6"  # CSV format
    }
    r = requests.get(url, params=params, timeout=30)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    csv_name = [f for f in z.namelist() if f.endswith('.csv')][0]
    df = pd.read_csv(z.open(csv_name))
    return df

# Download full year 2023 month by month (consistent with all other data)
all_months = []
for month in range(1, 13):
    start = datetime(2023, month, 1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    print(f"Downloading {start.strftime('%B %Y')}...")
    df = download_caiso_lmp(start, end)
    all_months.append(df)

prices = pd.concat(all_months)
prices.to_csv('data/prices/caiso_dam_lmp_2023.csv', index=False)
print(f"Downloaded {len(prices)} rows of CAISO LMP data")
```

**What the data looks like:**
```
INTERVALSTARTTIME_GMT      INTERVALENDTIME_GMT   NODE   LMP_TYPE   MW
2023-04-01T08:00:00-00:00  2023-04-01T09:00:00  TH_SP15_GEN-APND  LMP  65.96
```
LMP is in $/MWh. Convert to $/kWh by dividing by 1000.

---

### 4. SCE TOU-GS-3 Tariff (hand-encoded as JSON)

Create this file manually — rates are from SCE's published tariff schedule.
Current rates as of 2023 (verify at sce.com/regulatory/tariff-books):

```json
{
  "name": "SCE TOU-GS-3",
  "description": "Time-of-Use General Service, Large, Option B",
  "currency": "USD",
  "demand_charges": {
    "summer": {
      "months": [6, 7, 8, 9],
      "on_peak_kw": 19.10,
      "mid_peak_kw": 5.80,
      "all_time_kw": 8.85
    },
    "winter": {
      "months": [1, 2, 3, 4, 5, 10, 11, 12],
      "mid_peak_kw": 5.80,
      "all_time_kw": 8.85
    }
  },
  "energy_charges": {
    "summer": {
      "on_peak": {
        "hours": "14:00-20:00",
        "weekdays_only": true,
        "rate_kwh": 0.28317
      },
      "mid_peak": {
        "hours": "10:00-14:00 and 20:00-21:00",
        "weekdays_only": true,
        "rate_kwh": 0.15498
      },
      "off_peak": {
        "rate_kwh": 0.09871
      }
    },
    "winter": {
      "mid_peak": {
        "hours": "10:00-21:00",
        "weekdays_only": true,
        "rate_kwh": 0.13245
      },
      "off_peak": {
        "rate_kwh": 0.09871
      }
    }
  },
  "fixed_charges": {
    "customer_charge_monthly": 302.72,
    "power_factor_adjustment": "1% per 1% below 90% pf"
  },
  "demand_charge_note": "Demand charge based on highest 15-min kW reading in billing period"
}
```

---

### 5. Solar Generation — NREL PVWatts API

```python
import requests

# DEMO_KEY works for low-volume use (no account needed)
# For production: register free at developer.nrel.gov
url = "https://developer.nrel.gov/api/pvwatts/v8.json"
params = {
    "api_key": "DEMO_KEY",
    "lat": 33.60,          # Mission Viejo, CA (near JSerra school)
    "lon": -117.67,
    "system_capacity": 100, # 100 kW system
    "azimuth": 180,         # South-facing
    "tilt": 20,
    "array_type": 1,        # Fixed roof mount
    "module_type": 0,       # Standard
    "losses": 14,
    "timeframe": "hourly"
}
r = requests.get(url, params=params)
data = r.json()

import pandas as pd
solar_df = pd.DataFrame({
    'ac_output_kw': data['outputs']['ac']  # Hourly AC output in Wh, divide by 1000 for kWh
})
# This is 8760 rows (one per hour for a typical year)
solar_df['ac_output_kw'] = solar_df['ac_output_kw'] / 1000  # Convert Wh to kWh
solar_df.to_csv('data/solar/pvwatts_100kw_socal.csv', index=False)
```

---

## Core Models — How They Work

### Thermal Model (RC Model)

The building is modelled as a simple first-order RC (Resistor-Capacitor) circuit,
which is the standard approach in building energy literature and what Elexity uses.

**Physics:**
```
dT_indoor/dt = (T_outdoor - T_indoor) / (R * C) - Q_hvac / C

Where:
  T_indoor  = indoor air temperature (°F)
  T_outdoor = outdoor air temperature (°F)
  R         = thermal resistance (°F·h/kWh) — how well insulated the building is
  C         = thermal capacitance (kWh/°F) — how much heat the building can absorb
  Q_hvac    = HVAC cooling power (kWh/h), positive = cooling
```

**Parameter calibration from meter data:**
```python
# R and C are estimated from the load-vs-temperature scatter plot
# using linear regression — no separate measurements needed.
# This is the Bayesian calibration work done at Elvy Energy.

from scipy.optimize import curve_fit
import numpy as np

def thermal_model(T_outdoor, R, C, T_setpoint=72):
    """Steady-state HVAC power needed to maintain setpoint"""
    delta_T = T_outdoor - T_setpoint
    return np.maximum(0, delta_T / R)  # Only cooling load, no negative

# Fit R from scatter of HVAC load vs outdoor temperature
popt, pcov = curve_fit(thermal_model, T_outdoor_array, hvac_kw_array)
R_fitted, = popt
```

**Pre-cooling simulation:**
```python
def simulate_precooling(T_outdoor_series, R, C,
                         precool_start=10,  # 10am
                         precool_end=14,    # 2pm (before on-peak)
                         T_precool=70,      # Cool to 70°F
                         T_comfort_max=76,  # Max comfort limit
                         dt=0.25):          # 15-min timestep
    """
    Simulates indoor temperature drift after HVAC is switched off.
    Returns: how long before comfort limit is hit (= free load-shed window)
    """
    T = T_precool  # Start at pre-cooled temperature
    times_until_comfort_violation = []

    for t, T_out in enumerate(T_outdoor_series):
        dT = (T_out - T) / (R * C) * dt
        T = T + dT
        if T >= T_comfort_max:
            times_until_comfort_violation.append(t * dt)
            break

    return times_until_comfort_violation
```

**Key engineering tradeoff #1:**
Deeper pre-cooling (lower T_precool) → longer free load-shed window but higher
morning energy consumption. Optimal T_precool depends on the TOU rate differential
between morning off-peak and afternoon on-peak. This is a core finding to show.

---

### Battery Model

```python
class BatteryModel:
    """
    Simple battery model with SoC constraints.
    Sized based on Elexity's published CPS partnership: 125kW / 250kWh (2hr)
    """
    def __init__(self, power_kw=125, energy_kwh=250,
                 efficiency_rt=0.92,   # Round-trip efficiency
                 soc_min=0.10,         # Never discharge below 10%
                 soc_max=0.95):        # Never charge above 95%
        self.power_kw = power_kw
        self.energy_kwh = energy_kwh
        self.efficiency_rt = efficiency_rt
        self.soc_min = soc_min
        self.soc_max = soc_max
        self.soc = 0.50  # Start at 50%

    def charge(self, power_kw, dt=0.25):
        """dt in hours. Returns actual power charged."""
        power_kw = min(power_kw, self.power_kw)
        energy = power_kw * dt * np.sqrt(self.efficiency_rt)
        if self.soc + energy / self.energy_kwh > self.soc_max:
            energy = (self.soc_max - self.soc) * self.energy_kwh
        self.soc += energy / self.energy_kwh
        return energy / dt

    def discharge(self, power_kw, dt=0.25):
        """Returns actual power discharged to building."""
        power_kw = min(power_kw, self.power_kw)
        energy = power_kw * dt / np.sqrt(self.efficiency_rt)
        if self.soc - energy / self.energy_kwh < self.soc_min:
            energy = (self.soc - self.soc_min) * self.energy_kwh
        self.soc -= energy / self.energy_kwh
        return (energy / dt) * np.sqrt(self.efficiency_rt)
```

**Key engineering tradeoff #2:**
Battery sized for demand charge management vs TOU arbitrage vs grid services
are different optimal sizes. Demand charge management needs high power (kW),
TOU arbitrage needs high energy (kWh), grid services need both but with SoC
headroom reserved. The MILP optimizer resolves this conflict. Show this tradeoff.

---

### MILP Optimizer (cvxpy)

```python
import cvxpy as cp
import numpy as np

def optimize_dispatch(load_kw, solar_kw, prices_kwh, tariff,
                       battery_power=125, battery_energy=250,
                       T_outdoor=None, R=None, C=None,
                       T_comfort_min=70, T_comfort_max=76,
                       T_setpoint=72):
    """
    Mixed-Integer Linear Program for optimal dispatch.

    Decision variables:
      p_charge[t]    : battery charge power at each timestep (kW)
      p_discharge[t] : battery discharge power at each timestep (kW)
      soc[t]         : battery state of charge at each timestep (kWh)
      p_hvac[t]      : HVAC power (kW) — controllable load
      T_indoor[t]    : indoor temperature at each timestep (°F)
      p_grid[t]      : net grid import at each timestep (kW)
      p_demand        : monthly peak demand (kW) — scalar

    Objective: minimize monthly electricity bill
      = demand_charge * p_demand
      + sum(energy_rate[t] * p_grid[t] * dt)
      - sum(grid_services_revenue[t])
    """
    T = len(load_kw)
    dt = 0.25  # 15-min intervals

    # Variables
    p_charge    = cp.Variable(T, nonneg=True)
    p_discharge = cp.Variable(T, nonneg=True)
    soc         = cp.Variable(T + 1, nonneg=True)
    p_hvac      = cp.Variable(T, nonneg=True)
    T_indoor    = cp.Variable(T + 1)
    p_grid      = cp.Variable(T)
    p_demand    = cp.Variable(nonneg=True)  # Monthly peak

    # Energy rates ($/kWh) at each timestep
    energy_rate = np.array([tariff.get_rate(t) for t in range(T)])
    demand_rate = tariff.get_demand_rate()

    constraints = [
        # Power balance: grid + solar + discharge = load + charge
        p_grid == load_kw - solar_kw + p_charge - p_discharge + p_hvac - tariff.hvac_baseline_kw,

        # Battery SoC dynamics
        soc[0] == battery_energy * 0.5,  # Start at 50%
        soc[1:] == soc[:-1] + (p_charge * 0.96 - p_discharge / 0.96) * dt,
        soc >= battery_energy * 0.10,
        soc <= battery_energy * 0.95,
        p_charge  <= battery_power,
        p_discharge <= battery_power,

        # Thermal model constraints
        T_indoor[0] == T_setpoint,
        T_indoor[1:] == T_indoor[:-1] + ((T_outdoor - T_indoor[:-1]) / (R * C) - p_hvac / C) * dt,
        T_indoor >= T_comfort_min,
        T_indoor <= T_comfort_max,

        # Peak demand tracking
        p_grid <= p_demand,
        p_demand >= 0,
    ]

    # Objective: minimize bill
    energy_cost  = cp.sum(cp.multiply(energy_rate, p_grid)) * dt
    demand_cost  = demand_rate * p_demand
    objective    = cp.Minimize(energy_cost + demand_cost)

    prob = cp.Problem(objective, constraints)
    prob.solve(solver=cp.GLPK_MI, verbose=False)

    return {
        'status': prob.status,
        'total_cost': prob.value,
        'p_grid': p_grid.value,
        'p_charge': p_charge.value,
        'p_discharge': p_discharge.value,
        'soc': soc.value,
        'T_indoor': T_indoor.value,
        'peak_demand_kw': p_demand.value,
    }
```

**Key engineering tradeoff #3:**
Grid services (DSGS in California) require the battery to respond to utility
dispatch signals — meaning you must hold SoC headroom for grid events.
This conflicts with demand charge management which wants the battery fully
charged before the afternoon peak. The optimizer handles this with a reserved
SoC constraint. Show this conflict and how it's resolved.

---

### Seasonal Control Strategies

Different months require different strategies because HVAC load varies dramatically:

```python
SEASONAL_STRATEGIES = {
    "summer": {
        "months": [6, 7, 8, 9],
        "description": "HVAC 60-70% of load. Pre-cool 10am-2pm. Battery for afternoon peak.",
        "precool_window": ("10:00", "14:00"),
        "precool_temp": 70,          # °F — cool aggressively in morning
        "battery_mode": "demand_charge_management",
        "battery_charge_window": ("00:00", "10:00"),  # Charge overnight + morning
        "battery_discharge_window": ("14:00", "20:00"), # Discharge during on-peak
        "target_demand_reduction_pct": 0.60,  # Target 60% peak reduction
    },
    "shoulder": {
        "months": [4, 5, 10, 11],
        "description": "Moderate HVAC. Battery for TOU arbitrage primarily.",
        "precool_window": None,      # No pre-cooling needed
        "battery_mode": "tou_arbitrage",
        "battery_charge_window": ("22:00", "08:00"),   # Cheap off-peak
        "battery_discharge_window": ("14:00", "21:00"), # Mid/on-peak discharge
        "target_demand_reduction_pct": 0.30,
    },
    "winter": {
        "months": [1, 2, 3, 12],
        "description": "Minimal HVAC. Grid services + TOU arbitrage only.",
        "precool_window": None,
        "battery_mode": "grid_services_plus_tou",
        "battery_charge_window": ("22:00", "08:00"),
        "battery_discharge_window": ("10:00", "21:00"),
        "target_demand_reduction_pct": 0.15,
        "dsgs_enrollment": True,     # Enroll in DSGS for winter revenue
    }
}
```

---

## Bill Calculator — How SCE Bills Are Reconstructed

This is the most important function. It must be exact.

```python
def calculate_sce_bill(interval_df, tariff_json, month):
    """
    Reconstruct monthly SCE TOU-GS-3 bill from 15-min interval data.

    interval_df columns: timestamp (datetime), demand_kw (float)
    Returns: dict with energy_charge, demand_charge, fixed_charge, total
    """
    import json
    tariff = json.load(open(tariff_json))

    df = interval_df[interval_df['timestamp'].dt.month == month].copy()
    df['hour'] = df['timestamp'].dt.hour
    df['is_weekday'] = df['timestamp'].dt.dayofweek < 5
    df['is_summer'] = month in [6, 7, 8, 9]
    df['kwh'] = df['demand_kw'] * 0.25  # 15-min interval → kWh

    # Classify each interval into rate period
    def classify_period(row):
        if row['is_summer']:
            if row['is_weekday'] and 14 <= row['hour'] < 20:
                return 'on_peak'
            elif row['is_weekday'] and (10 <= row['hour'] < 14 or 20 <= row['hour'] < 21):
                return 'mid_peak'
            else:
                return 'off_peak'
        else:  # Winter
            if row['is_weekday'] and 10 <= row['hour'] < 21:
                return 'mid_peak'
            else:
                return 'off_peak'

    df['period'] = df.apply(classify_period, axis=1)

    # Energy charges
    rates = tariff['energy_charges']['summer' if month in [6,7,8,9] else 'winter']
    energy_charge = 0
    for period, group in df.groupby('period'):
        rate_key = period  # 'on_peak', 'mid_peak', 'off_peak'
        if rate_key in rates:
            energy_charge += group['kwh'].sum() * rates[rate_key]['rate_kwh']

    # Demand charge — maximum 15-min kW reading in the month
    peak_demand_kw = df['demand_kw'].max()
    dc = tariff['demand_charges']['summer' if month in [6,7,8,9] else 'winter']

    demand_charge = peak_demand_kw * dc.get('all_time_kw', 0)
    if 'on_peak_kw' in dc:
        on_peak_demand = df[df['period'] == 'on_peak']['demand_kw'].max()
        demand_charge += on_peak_demand * dc['on_peak_kw']

    # Fixed charges
    fixed_charge = tariff['fixed_charges']['customer_charge_monthly']

    return {
        'month': month,
        'energy_charge': round(energy_charge, 2),
        'demand_charge': round(demand_charge, 2),
        'fixed_charge': round(fixed_charge, 2),
        'total': round(energy_charge + demand_charge + fixed_charge, 2),
        'peak_demand_kw': round(peak_demand_kw, 1),
        'total_kwh': round(df['kwh'].sum(), 1),
    }
```

---

## Agent Architecture (LangGraph)

Five agents, one orchestrator. This mirrors the VPP system architecture
from Elvy Energy — 7-agent system adapted for building analysis.

```
User Input (building data path, tariff, scenario params)
         ↓
    Orchestrator Agent
    /    |    |    |    \
   DA   TA   ThA  OA   RA
   ↓    ↓    ↓    ↓    ↓
  Data Tariff Thermal MILP Report
```

**Orchestrator** (`agents/orchestrator.py`):
- Receives building data path and analysis parameters
- Routes to agents in order: Data → Tariff → Thermal → Optimizer → Report
- Handles errors (missing data, infeasible optimization) gracefully
- Uses LangGraph StateGraph with typed state

**Data Agent** (`agents/data_agent.py`):
- Loads meter data, validates timestamps, fills gaps (<2hr interpolation, >2hr flag)
- Loads weather data, aligns timestamps to meter data
- Loads CAISO prices, aligns to meter data
- Returns: cleaned DataFrames ready for analysis

**Tariff Agent** (`agents/tariff_agent.py`):
- Loads SCE TOU-GS-3 JSON
- Classifies every 15-min interval into rate period
- Calculates baseline bill (no interventions)
- Returns: baseline bill breakdown, rate schedule array

**Thermal Agent** (`agents/thermal_agent.py`):
- Fits RC model parameters from load-vs-temperature scatter
- Validates fit (R² > 0.7 required, otherwise flag as non-HVAC-dominated building)
- Simulates pre-cooling for each day in summer months
- Returns: R, C parameters, pre-cooling schedule, HVAC reduction profile

**Optimizer Agent** (`agents/optimizer_agent.py`):
- Runs MILP for each month using seasonal strategy
- Calculates optimized bill for each intervention scenario:
  1. Baseline (no changes)
  2. Solar only
  3. Solar + HVAC load control
  4. Solar + HVAC + Battery
  5. Solar + HVAC + Battery + Grid services (DSGS)
- Returns: optimized dispatch schedules, bill for each scenario

**Report Agent** (`agents/report_agent.py`):
- Generates waterfall chart (baseline → solar → hvac → battery → grid → future bill)
- Generates daily/monthly load profile charts (before vs after)
- Generates load-vs-temperature scatter with RC model fit overlay
- Generates payback table (capex, annual savings, simple payback, NPV at 8%)
- Writes outputs/{timestamp}/savings_summary.json
- Returns: narrative summary (uses Claude API for natural language summary)

---

## Streamlit Dashboard

**File:** `streamlit_app/app.py`

The dashboard has three panels:

**Panel 1 — Building Overview**
- Monthly load profile heatmap (hour of day × month)
- Load vs outdoor temperature scatter plot
- Monthly bill breakdown (energy vs demand charges, stacked bar)
- Key stats: peak demand kW, annual kWh, annual bill $

**Panel 2 — Scenario Simulator (Interactive)**
Sliders that update the analysis in real time:
- Solar system size (0–500 kW)
- Battery size (0–500 kW / 0–1000 kWh)
- Comfort band (±1°F to ±6°F from setpoint)
- DSGS enrollment (on/off toggle)

On slider change → re-run optimizer → update:
- Waterfall chart showing bill reduction per intervention
- Day-by-day savings chart (animated, shows how savings change across year)
- Month-by-month savings bar chart
- Updated payback table

**Panel 3 — Engineering Tradeoffs**
Static analysis charts that show the interesting engineering decisions:
- Pre-cooling depth vs free load-shed window (thermal model output)
- Battery size vs demand charge savings (diminishing returns curve)
- Grid services revenue vs demand charge savings conflict (when they compete)
- Seasonal strategy comparison (summer vs winter vs shoulder month dispatch)

---

## Output Format — Savings Summary JSON

Every run saves this to `outputs/{timestamp}/savings_summary.json`:

```json
{
  "run_id": "2024-01-15T10:32:00",
  "building": {
    "type": "SecondarySchool",
    "location": "Mission Viejo, CA",
    "climate_zone": "3B",
    "sqft": 85000,
    "peak_demand_kw": 187.3,
    "annual_kwh": 1842000
  },
  "tariff": "SCE TOU-GS-3",
  "baseline_annual_bill": 185420,
  "scenarios": {
    "solar_only": {
      "annual_bill": 143200,
      "annual_savings": 42220,
      "capex": 280000,
      "simple_payback_years": 6.6
    },
    "solar_plus_hvac": {
      "annual_bill": 120800,
      "annual_savings": 64620,
      "capex": 285000,
      "simple_payback_years": 4.4
    },
    "solar_hvac_battery": {
      "annual_bill": 93400,
      "annual_savings": 92020,
      "capex": 435000,
      "simple_payback_years": 4.7
    },
    "full_stack": {
      "annual_bill": 74200,
      "annual_savings": 111220,
      "capex": 435000,
      "simple_payback_years": 3.9,
      "grid_services_revenue": 19200
    }
  },
  "engineering_tradeoffs": {
    "optimal_precool_temp_summer_f": 70,
    "free_loadshed_window_hours": 2.5,
    "battery_demand_charge_savings": 26400,
    "battery_tou_arbitrage_savings": 9800,
    "dsgs_grid_services_revenue": 19200,
    "thermal_model_r2": 0.84,
    "rc_resistance": 0.42,
    "rc_capacitance": 180
  }
}
```

---

## Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml .
COPY . .

# Install dependencies via uv
RUN uv sync

# Expose Streamlit port
EXPOSE 8501

# Default: run Streamlit dashboard
CMD ["uv", "run", "streamlit", "run", "streamlit_app/app.py",
     "--server.port=8501", "--server.address=0.0.0.0"]
```

```bash
# Build and run
docker build -t elexity-analysis .
docker run -p 8501:8501 -v $(pwd)/data:/app/data elexity-analysis

# For analysis notebook only
docker run elexity-analysis uv run jupyter notebook notebooks/analysis.ipynb
```

---

## Key Engineering Tradeoffs to Highlight in Review

These are the findings that demonstrate domain depth. Make sure each one
appears explicitly in the notebook and the dashboard.

**Tradeoff 1: Pre-cooling depth vs morning energy cost**
- Deeper pre-cooling = longer free afternoon load-shed window
- But morning energy is not free — it's mid-peak rate in summer
- Optimal pre-cool temperature minimizes: (morning energy cost) - (afternoon demand charge avoided)
- Show the optimization curve. Typical optimum: 70°F pre-cool, 2.5hr free window.

**Tradeoff 2: Battery sizing — power vs energy**
- Demand charge management needs high power (kW) for short bursts
- TOU arbitrage needs high energy (kWh) for sustained discharge
- Grid services (DSGS) need SoC headroom = can't fully commit to either
- Show: demand charge savings vs battery size curve (flat after ~125kW for this building)
- Show: that HVAC load control reduces required battery size by 33% (the Elexity result)

**Tradeoff 3: Grid services vs demand charge conflict**
- DSGS events often coincide with afternoon peak (that's why the grid needs help)
- If battery is discharged for DSGS, it may not be available for demand charge management
- Resolution: hold minimum SoC reserve for demand charge during DSGS events
- Show this conflict with a specific day example where they overlap

**Tradeoff 4: Seasonal strategy differences**
- Summer: HVAC pre-cooling is the dominant value lever, battery amplifies it
- Winter: no HVAC load to control, battery does TOU arbitrage + grid services only
- Shoulder months: moderate everything, focus on demand charge reduction
- Show month-by-month savings contribution breakdown (stacked bar, color by intervention type)

---

## What the 90-Minute Exercise Deliverable Looks Like

When Mike emails the actual building data, the workflow is:

```bash
# 1. Drop the CSV into data/meter/
cp ~/Downloads/building_data.csv data/meter/

# 2. Run the full analysis pipeline
uv run python analysis/bill_calculator.py --input data/meter/building_data.csv

# 3. Output is in outputs/{timestamp}/
# 4. Open the notebook for the written narrative
uv run jupyter notebook notebooks/analysis.ipynb

# 5. Launch the dashboard to show interactive simulation
uv run streamlit run streamlit_app/app.py
```

The notebook structure:
1. **Data Loading & Validation** — what we received, data quality checks
2. **Cost Driver Analysis** — what's driving the bill, load profile, scatter plot
3. **Thermal Model Calibration** — RC parameters, R² fit, pre-cooling window
4. **Investment Recommendations** — waterfall chart, each intervention explained
5. **Payback Analysis** — capex assumptions, simple payback, NPV at 8% discount rate
6. **Engineering Tradeoffs** — the four tradeoffs listed above
7. **Next Steps** — what data would improve the analysis, what Elexity's platform adds

---

## Cursor-Specific Instructions

- Always use `uv run` to execute Python, never `python` directly
- Never use pip — always `uv add` for new packages
- All file paths are relative to project root
- Data files are not committed to git (they are in .gitignore)
- The `.env` file holds NREL_API_KEY and ANTHROPIC_API_KEY — never hardcode these
- When writing the MILP optimizer, use cvxpy with GLPK_MI solver (free, no license)
- When in doubt about tariff rates, the SCE tariff JSON in data/tariff/ is authoritative
- The thermal model R and C parameters must be calibrated from data, never hardcoded
- All monetary values in USD, all power in kW, all energy in kWh, all temperatures in °F

---

## Reference — Elexity Case Study Numbers (from white paper)

Use these as sanity checks. If your analysis produces very different numbers,
something is wrong with the model.

Southern California Secondary School (JSerra-type building):
- Baseline HVAC load: 60–70% of total building load
- Peak demand: 150–200 kW on hot days
- Battery system savings: ~$27,000/year (125kW, 2hr = 250kWh battery)
- HVAC load control additional savings: ~$17,000/year (+50% on top of battery)
- Grid services (day-ahead pricing pilot): ~$8,000/year revenue
- Total value stack: ~$52,000/year
- System payback: ~3.5 years

Value stack breakdown from white paper:
- HVAC solar smart load control: $15,000/year (equivalent to 75kW, 1.5hr battery)
- Battery TOU arbitrage (125kW, 2hr): $25,000/year
- Grid services day-ahead pricing: $8,000/year
- Total: ~$48,000/year, 3.5-year payback
