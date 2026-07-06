# Elexity Building Energy Analysis â€” TASKS.md
### Reference: PLAN.md

Junior engineer execution guide. Complete tasks in order. Each task has
a clear **Done when** condition â€” do not move to the next task until the
current one is verified. If a session crashes, resume from the first task
that does not yet have its Done-when condition satisfied.

---

## Phase 0 â€” Prerequisites

### Task 0.1 â€” [DONE] Verify tools

Existing repo confirms these are in place. Verify once before starting:

```bash
python --version    # must be 3.11 or higher
uv --version        # must print a version
docker --version    # required for Phase 9
```

**Done when:** all three commands print version numbers without errors.

> From this point on, never use `pip install` directly. All packages are
> managed via `uv` using `pyproject.toml` + `uv.lock`.

---

### Task 0.2 â€” [DONE] pyproject.toml exists

[pyproject.toml](pyproject.toml) already declares all required deps.
No changes needed unless a new package is added in a later task.

Current key dependencies: `pandas`, `numpy`, `scipy`, `cvxpy`, `pvlib`,
`streamlit`, `langgraph`, `langchain-anthropic`, `boto3`, `pyarrow`,
`python-dotenv`, `requests`.

**Done when:** `uv sync` completes without errors and `.venv/` is created.

```bash
uv sync
```

---

### Task 0.3 â€” [DONE] Create .env.example

Create `.env.example` at the project root:

```bash
# Copy to .env and fill in your keys before running
NREL_API_KEY=your_key_from_developer.nrel.gov
ANTHROPIC_API_KEY=your_key_from_console.anthropic.com
```

**Done when:** `.env.example` exists at root. Confirm `.env` (with real
keys) is listed in `.gitignore` and never committed.

---

### Task 0.4 â€” [DONE] Create .gitignore

Create `.gitignore` at the project root:

```
__pycache__/
*.pyc
*.egg-info/
.env
.venv/
outputs/
data/meter/
data/weather/
data/prices/
data/solar/
data/metadata.parquet
# tariff JSON stays in git:
!data/tariff/sce_tou_gs3.json
mlruns/
.ipynb_checkpoints/

# uv.lock is intentionally NOT listed â€” it must be committed
```

**Done when:** `git status` shows `.gitignore` tracked; `data/meter/`,
`data/weather/`, `data/prices/`, `data/solar/`, and `outputs/` are
ignored; `data/tariff/sce_tou_gs3.json` is NOT ignored.

---

### Task 0.5 â€” [DONE] Create directory scaffold

```bash
mkdir -p models analysis agents streamlit_app outputs notebooks scripts
# Create __init__.py files so Python treats dirs as packages
echo "" > models/__init__.py
echo "" > analysis/__init__.py
echo "" > agents/__init__.py
echo "" > streamlit_app/__init__.py
```

**Done when:** all six directories exist and `models/`, `analysis/`,
`agents/` each contain an `__init__.py`.

---

## Phase 1 â€” Data Acquisition [DONE]

### Task 1.1 â€” [DONE] Run download_data.py

[scripts/download_data.py](scripts/download_data.py) (or
[download_data.py](download_data.py) at root) downloads all 5 data
sources with synthetic fallback if APIs are unavailable.

```bash
uv run python scripts/download_data.py
```

Verify the five output files exist:

```bash
# PowerShell
Get-ChildItem data -Recurse -File | Select-Object FullName, Length
```

**Done when:** all five files exist with non-zero size:
- `data/meter/school_ca_15min.parquet`
- `data/weather/USA_CA_Los.Angeles.TMY3.epw`
- `data/prices/caiso_dam_lmp_2023.csv`
- `data/solar/pvwatts_100kw_socal.csv`
- `data/tariff/sce_tou_gs3.json`

And the meter file has exactly 35,040 rows (full year, 15-min intervals):

```python
import pandas as pd
df = pd.read_parquet("data/meter/school_ca_15min.parquet")
assert len(df) == 35040, f"Expected 35040 rows, got {len(df)}"
print(f"Peak demand: {df['demand_kw'].max():.1f} kW")
print(f"Annual energy: {(df['demand_kw'] * 0.25).sum() / 1000:.0f} MWh")
```

---

## Phase 2 â€” Tariff + Bill Calculator [DONE]

### Task 2.1 â€” [DONE] analysis/tariff.py

Create `analysis/tariff.py`. This is the single source of truth for all
rate lookups. Every other module calls this; never hard-code rates
elsewhere.

```python
"""
SCE TOU-GS-3 tariff parser.
Loads data/tariff/sce_tou_gs3.json and exposes helper functions.
See PLAN.md - Bill Calculator section for rate tables.
"""
import json
from pathlib import Path
from datetime import datetime

_TARIFF_PATH = Path(__file__).parents[1] / "data" / "tariff" / "sce_tou_gs3.json"


def load_tariff() -> dict:
    with open(_TARIFF_PATH) as f:
        return json.load(f)


def classify_period(ts: datetime) -> str:
    """
    Classify a 15-min timestamp into a TOU rate period.

    Returns: 'on_peak', 'mid_peak', or 'off_peak'.
    """
    month = ts.month
    hour = ts.hour
    is_weekday = ts.weekday() < 5
    is_summer = month in [6, 7, 8, 9]

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
    season = "summer" if ts.month in [6, 7, 8, 9] else "winter"
    period = classify_period(ts)
    rates = tariff["energy_charges_per_kwh"][season]
    if period in rates:
        return rates[period]["rate"]
    return rates["off_peak"]["rate"]


def get_demand_rates(month: int) -> dict:
    """
    Return demand charge rates ($/kW) for a given month.

    Keys: 'all_time_kw', and optionally 'on_peak_kw'.
    """
    tariff = load_tariff()
    season = "summer" if month in [6, 7, 8, 9] else "winter"
    return tariff["demand_charges"][season]


def get_customer_charge() -> float:
    """Return the fixed monthly customer charge in USD."""
    tariff = load_tariff()
    return tariff["fixed_charges"]["customer_charge_monthly_usd"]
```

**Done when:** the following runs without error:

```python
from analysis.tariff import classify_period, get_energy_rate
from datetime import datetime

ts_on_peak = datetime(2023, 7, 10, 15, 0)   # Summer weekday 3pm
ts_off_peak = datetime(2023, 7, 15, 3, 0)   # Summer weekend 3am

assert classify_period(ts_on_peak) == "on_peak"
assert classify_period(ts_off_peak) == "off_peak"
print(f"On-peak rate: ${get_energy_rate(ts_on_peak):.5f}/kWh")
print("tariff.py OK")
```

---

### Task 2.2 â€” [DONE] analysis/bill_calculator.py

Reconstruct a monthly SCE TOU-GS-3 bill from 15-min interval data.

```python
"""
SCE TOU-GS-3 bill calculator.
Reconstructs monthly bill from 15-min interval meter data.
See PLAN.md - Bill Calculator section.
"""
import pandas as pd
import numpy as np
from analysis.tariff import (
    classify_period,
    get_demand_rates,
    get_customer_charge,
)


def calculate_monthly_bill(df: pd.DataFrame, month: int) -> dict:
    """
    Reconstruct one month's SCE TOU-GS-3 bill.

    Args:
        df: DataFrame with columns 'timestamp' (datetime) and
            'demand_kw' (float).
        month: integer 1-12.

    Returns:
        dict with energy_charge, demand_charge, fixed_charge, total,
        peak_demand_kw, total_kwh.
    """
    dm = df[df["timestamp"].dt.month == month].copy()
    dm["kwh"] = dm["demand_kw"] * 0.25  # 15-min interval -> kWh
    dm["period"] = dm["timestamp"].apply(classify_period)

    # ---- Energy charges ------------------------------------------------
    tariff = __import__("analysis.tariff", fromlist=["load_tariff"])
    tariff_data = tariff.load_tariff()
    season = "summer" if month in [6, 7, 8, 9] else "winter"
    rates = tariff_data["energy_charges_per_kwh"][season]

    energy_charge = 0.0
    for period, group in dm.groupby("period"):
        rate_key = period if period in rates else "off_peak"
        energy_charge += group["kwh"].sum() * rates[rate_key]["rate"]

    # ---- Demand charges ------------------------------------------------
    dc_rates = get_demand_rates(month)
    peak_demand_kw = dm["demand_kw"].max()
    demand_charge = peak_demand_kw * dc_rates.get("all_time_kw", 0.0)

    if "on_peak_kw" in dc_rates:
        on_peak_rows = dm[dm["period"] == "on_peak"]
        if not on_peak_rows.empty:
            on_peak_demand = on_peak_rows["demand_kw"].max()
        else:
            on_peak_demand = 0.0
        demand_charge += on_peak_demand * dc_rates["on_peak_kw"]

    # ---- Fixed charges -------------------------------------------------
    fixed_charge = get_customer_charge()

    total = energy_charge + demand_charge + fixed_charge
    return {
        "month": month,
        "energy_charge": round(energy_charge, 2),
        "demand_charge": round(demand_charge, 2),
        "fixed_charge": round(fixed_charge, 2),
        "total": round(total, 2),
        "peak_demand_kw": round(peak_demand_kw, 1),
        "total_kwh": round(dm["kwh"].sum(), 1),
    }


def calculate_annual_bill(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate bill for all 12 months. Returns DataFrame."""
    rows = [calculate_monthly_bill(df, m) for m in range(1, 13)]
    annual = pd.DataFrame(rows)
    annual_total = annual["total"].sum()
    print(f"Annual bill: ${annual_total:,.0f}")
    print(
        f"  Energy: ${annual['energy_charge'].sum():,.0f}  "
        f"Demand: ${annual['demand_charge'].sum():,.0f}  "
        f"Fixed: ${annual['fixed_charge'].sum():,.0f}"
    )
    return annual


if __name__ == "__main__":
    df = pd.read_parquet("data/meter/school_ca_15min.parquet")
    if "timestamp" not in df.columns:
        df = df.rename(columns={df.columns[0]: "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    annual = calculate_annual_bill(df)
    print(annual[["month", "total", "peak_demand_kw"]].to_string())
```

**Done when:** `uv run python analysis/bill_calculator.py` prints an
annual bill in the $120,000â€“$220,000 range and a peak demand of
150â€“210 kW.

---

## Phase 3 â€” Cost Driver Analysis [DONE]

### Task 3.1 â€” [DONE] analysis/cost_driver.py

```python
"""
Cost driver decomposition for a commercial building.
Produces: energy/demand charge shares, load heatmap,
          load-vs-temperature scatter.
See PLAN.md - Engineering Tradeoffs section.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from pathlib import Path
from analysis.bill_calculator import calculate_annual_bill

matplotlib.use("Agg")  # non-interactive backend

OUTPUT_DIR = Path("outputs/cost_driver")


def decompose_bill(annual_df: pd.DataFrame) -> dict:
    """Return % share of each charge component."""
    totals = {
        "energy": annual_df["energy_charge"].sum(),
        "demand": annual_df["demand_charge"].sum(),
        "fixed": annual_df["fixed_charge"].sum(),
    }
    grand = sum(totals.values())
    return {k: round(v / grand * 100, 1) for k, v in totals.items()}


def plot_load_heatmap(df: pd.DataFrame, output_path: Path) -> None:
    """Plot hour-of-day x month load heatmap."""
    df = df.copy()
    df["hour"] = df["timestamp"].dt.hour
    df["month"] = df["timestamp"].dt.month
    pivot = df.pivot_table(
        values="demand_kw", index="hour", columns="month", aggfunc="mean"
    )
    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.imshow(pivot.values, aspect="auto", origin="lower")
    ax.set_xlabel("Month")
    ax.set_ylabel("Hour of Day")
    ax.set_title("Average Load (kW) â€” Hour of Day x Month")
    ax.set_xticks(range(12))
    ax.set_xticklabels(
        ["Jan","Feb","Mar","Apr","May","Jun",
         "Jul","Aug","Sep","Oct","Nov","Dec"]
    )
    plt.colorbar(im, ax=ax, label="kW")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {output_path}")


def plot_load_vs_temperature(df: pd.DataFrame, output_path: Path) -> None:
    """Scatter: HVAC load vs outdoor temperature with trendline."""
    has_hvac = "out.electricity.hvac.demand_kw" in df.columns
    has_temp = "T_outdoor_f" in df.columns

    if not (has_hvac and has_temp):
        print("Skipping scatter: HVAC or temperature column missing.")
        return

    df = df[df["T_outdoor_f"] > 60].copy()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(
        df["T_outdoor_f"],
        df["out.electricity.hvac.demand_kw"],
        alpha=0.05, s=2, color="steelblue",
    )
    # Simple linear trendline
    coeffs = np.polyfit(
        df["T_outdoor_f"], df["out.electricity.hvac.demand_kw"], 1
    )
    t_range = np.linspace(df["T_outdoor_f"].min(), df["T_outdoor_f"].max(), 100)
    ax.plot(t_range, np.polyval(coeffs, t_range), "r-", linewidth=2,
            label=f"slope={coeffs[0]:.2f} kW/Â°F")
    ax.set_xlabel("Outdoor Temperature (Â°F)")
    ax.set_ylabel("HVAC Load (kW)")
    ax.set_title("HVAC Load vs Outdoor Temperature")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet("data/meter/school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    annual = calculate_annual_bill(df)
    shares = decompose_bill(annual)
    print(f"\nCost driver breakdown: {shares}")

    plot_load_heatmap(df, OUTPUT_DIR / "load_heatmap.png")
    plot_load_vs_temperature(df, OUTPUT_DIR / "load_vs_temp.png")
```

**Done when:** `uv run python analysis/cost_driver.py` prints the cost
breakdown (energy / demand / fixed %) and saves two PNG files to
`outputs/cost_driver/`.

---

## Phase 4 â€” Core Models

### Task 4.1 â€” models/thermal_model.py

```python
"""
RC thermal model for a commercial building.
Calibrates R and C from HVAC load vs outdoor temperature.
See PLAN.md - Core Models section for physics equations.
"""
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.stats import pearsonr


def _steady_state_hvac(T_outdoor: np.ndarray, R: float,
                        T_setpoint: float = 72.0) -> np.ndarray:
    """Steady-state HVAC kW needed to maintain indoor setpoint."""
    return np.maximum(0.0, (T_outdoor - T_setpoint) / R)


def fit_rc_model(
    df: pd.DataFrame,
    hvac_col: str = "out.electricity.hvac.demand_kw",
    temp_col: str = "T_outdoor_f",
    T_setpoint: float = 72.0,
) -> dict:
    """
    Fit R from load-vs-temperature scatter using least squares.

    Returns dict with R, C (estimated), r_squared.
    Raises ValueError if R^2 < 0.70 (non-HVAC-dominated building).
    """
    if hvac_col not in df.columns or temp_col not in df.columns:
        raise ValueError(
            f"Required columns missing: {hvac_col}, {temp_col}"
        )

    # Filter: cooling season, occupied hours, positive HVAC load
    mask = (
        (df["timestamp"].dt.month.isin([5, 6, 7, 8, 9, 10]))
        & (df[hvac_col] > 1.0)
        & (df[temp_col] > 65.0)
    )
    sub = df[mask].dropna(subset=[hvac_col, temp_col])

    T_out = sub[temp_col].values
    hvac_kw = sub[hvac_col].values

    popt, _ = curve_fit(
        lambda T, R: _steady_state_hvac(T, R, T_setpoint),
        T_out, hvac_kw, p0=[0.4], bounds=(0.01, 10.0),
    )
    R = float(popt[0])

    predicted = _steady_state_hvac(T_out, R, T_setpoint)
    corr, _ = pearsonr(hvac_kw, predicted)
    r_squared = corr ** 2

    # Estimate C from thermal mass: 2-hr time constant => C = 2 * 1/R
    C = 2.0 / R

    result = {
        "R": round(R, 4),
        "C": round(C, 1),
        "r_squared": round(r_squared, 4),
        "n_samples": len(sub),
        "T_setpoint": T_setpoint,
    }

    if r_squared < 0.70:
        print(
            f"WARNING: R^2={r_squared:.3f} < 0.70. "
            "Building may not be HVAC-dominated. "
            "Pre-cooling savings estimates will be unreliable."
        )
    else:
        print(
            f"RC model fit: R={R:.4f} Â°FÂ·h/kWh, "
            f"C={C:.1f} kWh/Â°F, R^2={r_squared:.3f}"
        )
    return result


def simulate_precooling(
    T_outdoor_series: np.ndarray,
    R: float,
    C: float,
    T_precool: float = 70.0,
    T_comfort_max: float = 76.0,
    T_setpoint: float = 72.0,
    dt: float = 0.25,
) -> float:
    """
    Simulate indoor temperature drift after HVAC is switched off.

    Returns hours before comfort limit is reached (free load-shed window).
    """
    T = T_precool
    for i, T_out in enumerate(T_outdoor_series):
        dT = (T_out - T) / (R * C) * dt
        T = T + dT
        if T >= T_comfort_max:
            return round(i * dt, 2)
    return round(len(T_outdoor_series) * dt, 2)


if __name__ == "__main__":
    df = pd.read_parquet("data/meter/school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    params = fit_rc_model(df)
    print(f"RC params: {params}")

    # Test pre-cooling on a hot day (90Â°F outdoor)
    T_afternoon = np.full(20, 92.0)  # 5 hours at 92Â°F
    free_hrs = simulate_precooling(
        T_afternoon, params["R"], params["C"], T_precool=70.0
    )
    print(f"Free load-shed window at 70Â°F pre-cool: {free_hrs:.2f} hr")
```

**Done when:** `uv run python models/thermal_model.py` prints RC params
with R^2 (may warn if synthetic data, that is acceptable) and prints the
free load-shed window (expected ~2â€“3 hr for a hot day).

---

### Task 4.2 â€” models/battery_model.py

```python
"""
Battery state-of-charge model.
Default size: 125 kW / 250 kWh (2-hr), matching Elexity CPS partnership.
See PLAN.md - Core Models section.
"""
import numpy as np


class BatteryModel:
    """
    Simple battery model with SoC constraints.
    All power in kW, all energy in kWh, timestep dt in hours.
    """

    def __init__(
        self,
        power_kw: float = 125.0,
        energy_kwh: float = 250.0,
        efficiency_rt: float = 0.92,
        soc_min: float = 0.10,
        soc_max: float = 0.95,
        initial_soc: float = 0.50,
    ):
        self.power_kw = power_kw
        self.energy_kwh = energy_kwh
        self.efficiency_rt = efficiency_rt
        self.soc_min = soc_min
        self.soc_max = soc_max
        self.soc = initial_soc

    @property
    def soc_kwh(self) -> float:
        return self.soc * self.energy_kwh

    def charge(self, power_kw: float, dt: float = 0.25) -> float:
        """
        Charge the battery. Returns actual power drawn from grid (kW).
        dt in hours.
        """
        power_kw = min(power_kw, self.power_kw)
        energy_in = power_kw * dt * np.sqrt(self.efficiency_rt)
        headroom = (self.soc_max - self.soc) * self.energy_kwh
        energy_in = min(energy_in, headroom)
        self.soc += energy_in / self.energy_kwh
        actual_power = energy_in / dt if dt > 0 else 0.0
        return round(actual_power / np.sqrt(self.efficiency_rt), 3)

    def discharge(self, power_kw: float, dt: float = 0.25) -> float:
        """
        Discharge the battery. Returns actual power delivered (kW).
        dt in hours.
        """
        power_kw = min(power_kw, self.power_kw)
        energy_out = power_kw * dt / np.sqrt(self.efficiency_rt)
        available = (self.soc - self.soc_min) * self.energy_kwh
        energy_out = min(energy_out, available)
        self.soc -= energy_out / self.energy_kwh
        actual_power = energy_out * np.sqrt(self.efficiency_rt) / dt
        return round(actual_power, 3)

    def reset(self, soc: float = 0.50) -> None:
        self.soc = soc

    def __repr__(self) -> str:
        return (
            f"BatteryModel({self.power_kw}kW/{self.energy_kwh}kWh, "
            f"SoC={self.soc:.1%})"
        )


if __name__ == "__main__":
    bat = BatteryModel()
    print(bat)
    # Charge for 4 hours at 60 kW
    for _ in range(16):  # 16 x 15-min intervals
        bat.charge(60.0, dt=0.25)
    print(f"After 4hr charge at 60kW: {bat}")

    # Discharge at full power
    for _ in range(8):  # 2hr
        bat.discharge(125.0, dt=0.25)
    print(f"After 2hr discharge at 125kW: {bat}")
```

**Done when:** `uv run python models/battery_model.py` prints SoC state
after charge and discharge sequences without errors, with SoC values
staying within [0.10, 0.95].

---

### Task 4.3 â€” models/solar_model.py

```python
"""
Solar PV generation model.
Loads NREL PVWatts CSV and provides interpolated 15-min output.
See PLAN.md - Core Models section.
"""
import pandas as pd
import numpy as np
from pathlib import Path

_SOLAR_CSV = (
    Path(__file__).parents[1] / "data" / "solar" / "pvwatts_100kw_socal.csv"
)
_BASE_CAPACITY_KW = 100.0  # kW at which PVWatts was run


def load_solar_profile(system_capacity_kw: float = 100.0) -> pd.DataFrame:
    """
    Load PVWatts hourly profile and resample to 15-min intervals.

    Args:
        system_capacity_kw: desired system size to scale output to.

    Returns:
        DataFrame with columns 'timestamp' and 'solar_kw' at 15-min freq.
    """
    df = pd.read_csv(_SOLAR_CSV)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[["timestamp", "ac_output_kw"]].set_index("timestamp")

    # Resample hourly -> 15-min using forward fill
    df_15min = df.resample("15min").ffill()
    df_15min = df_15min.reset_index()
    df_15min.columns = ["timestamp", "solar_kw"]

    # Scale from base capacity (100 kW) to desired capacity
    scale = system_capacity_kw / _BASE_CAPACITY_KW
    df_15min["solar_kw"] = (df_15min["solar_kw"] * scale).round(3)

    return df_15min


def get_annual_generation_kwh(system_capacity_kw: float = 100.0) -> float:
    """Return total annual AC generation in kWh."""
    df = load_solar_profile(system_capacity_kw)
    return round(df["solar_kw"].sum() * 0.25, 0)  # kWh (15-min intervals)


if __name__ == "__main__":
    profile = load_solar_profile(100.0)
    annual_kwh = get_annual_generation_kwh(100.0)
    print(f"Solar profile: {len(profile)} rows")
    print(f"Annual generation (100 kW): {annual_kwh:,.0f} kWh")
    print(f"  (~{annual_kwh/100:.0f} kWh/kW, expect ~1,600-1,700 for SoCal)")
    print(f"Peak output: {profile['solar_kw'].max():.1f} kW")
```

**Done when:** `uv run python models/solar_model.py` prints annual
generation for a 100 kW system in the range 150,000â€“175,000 kWh
(~1,500â€“1,750 kWh/kW, typical for Mission Viejo CA).

---

### Task 4.4 â€” models/optimizer.py

This is the most complex module. Implements the MILP from CONTEXT.md.

```python
"""
MILP dispatch optimizer using cvxpy + GLPK_MI.
Minimizes monthly electricity bill across all DER assets.
See CONTEXT.md - MILP Optimizer and PLAN.md - Core Models.
"""
import numpy as np
import cvxpy as cp


def optimize_dispatch(
    load_kw: np.ndarray,
    solar_kw: np.ndarray,
    prices_kwh: np.ndarray,
    tariff_rates: np.ndarray,
    demand_rate: float,
    battery_power_kw: float = 125.0,
    battery_energy_kwh: float = 250.0,
    T_outdoor: np.ndarray = None,
    R: float = None,
    C: float = None,
    T_comfort_min: float = 70.0,
    T_comfort_max: float = 76.0,
    T_setpoint: float = 72.0,
    dt: float = 0.25,
) -> dict:
    """
    MILP for optimal DER dispatch over a planning horizon.

    Args:
        load_kw: baseline building load at each timestep (kW).
        solar_kw: solar PV output at each timestep (kW).
        prices_kwh: CAISO LMP at each timestep ($/kWh).
        tariff_rates: SCE energy rate at each timestep ($/kWh).
        demand_rate: demand charge rate ($/kW).
        battery_power_kw, battery_energy_kwh: battery sizing.
        T_outdoor: outdoor temperature array (Â°F). If None, skip thermal.
        R, C: RC model parameters. Required if T_outdoor is provided.
        dt: timestep length in hours (0.25 for 15-min).

    Returns:
        dict with status, total_cost, and dispatch arrays.
    """
    T = len(load_kw)
    use_thermal = T_outdoor is not None and R is not None and C is not None

    # ---- Decision variables --------------------------------------------
    p_charge = cp.Variable(T, nonneg=True)
    p_discharge = cp.Variable(T, nonneg=True)
    soc = cp.Variable(T + 1, nonneg=True)
    p_grid = cp.Variable(T)
    p_demand = cp.Variable(nonneg=True)

    eta = np.sqrt(0.92)  # one-way efficiency

    constraints = [
        # Power balance
        p_grid == load_kw - solar_kw + p_charge - p_discharge,
        # Battery dynamics
        soc[0] == battery_energy_kwh * 0.50,
        soc[1:] == soc[:-1] + (p_charge * eta - p_discharge / eta) * dt,
        soc >= battery_energy_kwh * 0.10,
        soc <= battery_energy_kwh * 0.95,
        p_charge <= battery_power_kw,
        p_discharge <= battery_power_kw,
        # Peak demand tracking
        p_grid <= p_demand,
        p_demand >= 0,
    ]

    if use_thermal:
        p_hvac = cp.Variable(T, nonneg=True)
        T_indoor = cp.Variable(T + 1)
        hvac_baseline = np.maximum(
            0.0, (T_outdoor - T_setpoint) / R
        )
        constraints += [
            p_grid == (
                load_kw - solar_kw + p_charge - p_discharge
                + p_hvac - hvac_baseline
            ),
            T_indoor[0] == T_setpoint,
            T_indoor[1:] == (
                T_indoor[:-1]
                + ((T_outdoor - T_indoor[:-1]) / (R * C) - p_hvac / C) * dt
            ),
            T_indoor >= T_comfort_min,
            T_indoor <= T_comfort_max,
        ]

    # ---- Objective: minimize monthly bill ------------------------------
    energy_cost = cp.sum(cp.multiply(tariff_rates, p_grid)) * dt
    demand_cost = demand_rate * p_demand
    objective = cp.Minimize(energy_cost + demand_cost)

    prob = cp.Problem(objective, constraints)
    prob.solve(solver=cp.GLPK_MI, verbose=False)

    result = {
        "status": prob.status,
        "total_cost": prob.value,
        "p_grid": p_grid.value,
        "p_charge": p_charge.value,
        "p_discharge": p_discharge.value,
        "soc": soc.value,
        "peak_demand_kw": float(p_demand.value) if p_demand.value else None,
    }
    if use_thermal:
        result["T_indoor"] = T_indoor.value
        result["p_hvac"] = p_hvac.value

    return result


if __name__ == "__main__":
    import pandas as pd
    from analysis.tariff import get_energy_rate

    # Quick smoke test: one week of data
    df = pd.read_parquet("data/meter/school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # July week
    week = df[
        (df["timestamp"].dt.month == 7)
        & (df["timestamp"].dt.day <= 7)
    ].copy()

    load = week["demand_kw"].values
    solar = np.zeros(len(load))  # no solar for this test
    tariff_rates = np.array([
        get_energy_rate(ts) for ts in week["timestamp"]
    ])
    prices = tariff_rates  # use tariff as proxy for CAISO

    result = optimize_dispatch(
        load_kw=load,
        solar_kw=solar,
        prices_kwh=prices,
        tariff_rates=tariff_rates,
        demand_rate=19.10 + 8.85,  # summer on-peak + all-time
    )
    print(f"Optimizer status: {result['status']}")
    print(f"Optimized cost: ${result['total_cost']:,.2f}")
    print(f"Peak demand: {result['peak_demand_kw']:.1f} kW")
```


---

### Task 4.5 [DONE] -- 3-demand MILP: models/optimizer.py

**Branch:** `MILP_three_demand_charges_optimization`

Replace single `demand_rate / p_peak` with three independent demand
peaks matching SCE TOU-GS-3:
- `p_peak_on`  -- on-peak demand peak ($19.10/kW, summer weekday 14-20h)
- `p_peak_mid` -- mid-peak demand peak ($5.80/kW)
- `p_peak_all` -- all-time demand peak ($8.85/kW, every interval)

All-time demand protection is implicit via `p_grid <= p_peak_all`
in the objective. Solver: HIGHS. August smoke test: on-peak 170 kW
-> 88.5 kW (48% reduction), status: optimal.

---

### Task 4.6 [DONE] -- Wire MILP into savings_calculator.py

Replaced rule-based battery for-loop with month-by-month MILP calls
when `use_milp=True` (default). Added helpers:
- `_apply_milp_battery()`: 12-month loop, TOU masks, 3 demand rates
- `_apply_rulebased_battery()`: original heuristic (use_milp=False)

Expected improvement: ~$423/yr (rule-based) -> $8k-$27k/yr (MILP).

---

### Task 4.7 [DONE] -- Update optimizer_agent.py

Build `on_peak_mask` / `mid_peak_mask` from August timestamps.
Call `optimize_dispatch()` with 3 rates from `get_demand_rates(8)`.
Result dict now includes `peak_on_kw`, `peak_mid_kw`, `peak_all_kw`.

---

### Task 4.8 [DONE] -- Re-run notebook; verify battery savings > $5k/yr

`ash
uv run python scripts/build_notebook.py
uv run jupyter nbconvert --to notebook --execute notebooks/analysis.ipynb
`

Done when battery row in savings waterfall shows > $5,000/yr incremental.

**Done when:** `uv run python models/optimizer.py` completes with
`status: optimal` and prints cost + peak demand without errors.

---

## Phase 5 â€” Control Strategies and Savings Calculator

### Task 5.1 â€” analysis/control_strategy.py

```python
"""
Seasonal control strategy definitions.
Maps each month to the appropriate DER dispatch strategy.
See PLAN.md - Seasonal Control Strategies section.
"""

SEASONAL_STRATEGIES = {
    "summer": {
        "months": [6, 7, 8, 9],
        "description": (
            "HVAC 60-70% of load. "
            "Pre-cool 10am-2pm. Battery for afternoon peak."
        ),
        "precool_window": ("10:00", "14:00"),
        "precool_temp_f": 70,
        "battery_mode": "demand_charge_management",
        "battery_charge_window": ("00:00", "10:00"),
        "battery_discharge_window": ("14:00", "20:00"),
        "target_demand_reduction_pct": 0.60,
        "dsgs_enrollment": False,
    },
    "shoulder": {
        "months": [4, 5, 10, 11],
        "description": "Moderate HVAC. Battery for TOU arbitrage primarily.",
        "precool_window": None,
        "battery_mode": "tou_arbitrage",
        "battery_charge_window": ("22:00", "08:00"),
        "battery_discharge_window": ("14:00", "21:00"),
        "target_demand_reduction_pct": 0.30,
        "dsgs_enrollment": False,
    },
    "winter": {
        "months": [1, 2, 3, 12],
        "description": "Minimal HVAC. Grid services + TOU arbitrage only.",
        "precool_window": None,
        "battery_mode": "grid_services_plus_tou",
        "battery_charge_window": ("22:00", "08:00"),
        "battery_discharge_window": ("10:00", "21:00"),
        "target_demand_reduction_pct": 0.15,
        "dsgs_enrollment": True,
    },
}


def get_strategy(month: int) -> dict:
    """Return the seasonal strategy dict for a given month (1-12)."""
    for name, strategy in SEASONAL_STRATEGIES.items():
        if month in strategy["months"]:
            return {**strategy, "season": name}
    raise ValueError(f"Month {month} not found in any strategy")


if __name__ == "__main__":
    for month in [1, 4, 7, 10]:
        s = get_strategy(month)
        print(
            f"Month {month}: season={s['season']}, "
            f"battery_mode={s['battery_mode']}, "
            f"dsgs={s['dsgs_enrollment']}"
        )
```

**Done when:** `uv run python analysis/control_strategy.py` prints the
strategy for months 1, 4, 7, 10 without errors.

---

### Task 5.2 â€” analysis/savings_calculator.py

```python
"""
Savings calculator: computes the value-stack waterfall.
Runs 5 scenarios and returns bill reductions + payback periods.
See PLAN.md - Engineering Tradeoffs and Output Format sections.
"""
import pandas as pd
import numpy as np
from analysis.bill_calculator import calculate_annual_bill
from models.solar_model import load_solar_profile

# Capital cost assumptions (USD)
CAPEX = {
    "solar_100kw": 280_000,       # $2.80/W installed
    "hvac_controls": 5_000,       # incremental for smart controls
    "battery_125kw_250kwh": 150_000,  # $600/kWh
}

# DSGS grid services revenue estimate ($/year)
DSGS_ANNUAL_REVENUE = 8_000


def run_baseline(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate baseline annual bill with no interventions."""
    return calculate_annual_bill(df)


def run_solar_only(
    df: pd.DataFrame, solar_kw: float = 100.0
) -> pd.DataFrame:
    """Subtract solar generation from meter load, recalculate bill."""
    solar = load_solar_profile(solar_kw)
    # Align on month to handle timestamp differences
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
    return calculate_annual_bill(df_merged)


def build_waterfall(
    baseline_annual: float,
    solar_annual: float,
    solar_hvac_annual: float,
    solar_hvac_bat_annual: float,
    full_stack_annual: float,
) -> list[dict]:
    """Build waterfall chart data (each step's incremental saving)."""
    return [
        {
            "label": "Baseline bill",
            "value": baseline_annual,
            "incremental": 0,
        },
        {
            "label": "Solar",
            "value": solar_annual,
            "incremental": baseline_annual - solar_annual,
        },
        {
            "label": "+ HVAC load control",
            "value": solar_hvac_annual,
            "incremental": solar_annual - solar_hvac_annual,
        },
        {
            "label": "+ Battery",
            "value": solar_hvac_bat_annual,
            "incremental": solar_hvac_annual - solar_hvac_bat_annual,
        },
        {
            "label": "+ Grid services (DSGS)",
            "value": full_stack_annual - DSGS_ANNUAL_REVENUE,
            "incremental": DSGS_ANNUAL_REVENUE,
        },
    ]


def calculate_payback(
    annual_savings: float, capex: float
) -> dict:
    """Simple payback and NPV at 8% discount rate over 20 years."""
    if annual_savings <= 0:
        return {"simple_payback_years": None, "npv_20yr": None}
    payback = capex / annual_savings
    # NPV: sum of (savings / (1+r)^t) for t=1..20, minus capex
    r = 0.08
    npv = sum(annual_savings / (1 + r) ** t for t in range(1, 21)) - capex
    return {
        "simple_payback_years": round(payback, 2),
        "npv_20yr": round(npv, 0),
    }


if __name__ == "__main__":
    df = pd.read_parquet("data/meter/school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    baseline = run_baseline(df)
    solar = run_solar_only(df)

    baseline_total = baseline["total"].sum()
    solar_total = solar["total"].sum()
    solar_savings = baseline_total - solar_total

    print(f"Baseline annual bill:   ${baseline_total:>10,.0f}")
    print(f"Solar only annual bill: ${solar_total:>10,.0f}")
    print(f"Solar savings:          ${solar_savings:>10,.0f}/year")
    pb = calculate_payback(solar_savings, CAPEX["solar_100kw"])
    print(f"Solar payback: {pb['simple_payback_years']:.1f} years")
    print(f"Solar NPV (20yr, 8%): ${pb['npv_20yr']:,.0f}")
```

**Done when:** `uv run python analysis/savings_calculator.py` prints
baseline and solar-only annual bills (both > $80k), solar savings
(expected $30kâ€“$60k/year), and a payback of 5â€“9 years for solar only.

---

## Phase 6 â€” Agents (LangGraph)

### Task 6.1 â€” agents/data_agent.py

```python
"""
Data agent: loads, validates, and aligns all 5 data sources.
See PLAN.md - Agent Architecture section.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import TypedDict

DATA_DIR = Path("data")


class DataState(TypedDict):
    meter: pd.DataFrame
    weather: pd.DataFrame
    prices: pd.DataFrame
    solar: pd.DataFrame
    errors: list[str]


def run_data_agent(state: dict) -> dict:
    """Load and validate all data sources. Returns updated state."""
    errors = []

    # ---- Meter data ------------------------------------------------
    meter_path = DATA_DIR / "meter" / "school_ca_15min.parquet"
    meter = pd.read_parquet(meter_path)
    meter["timestamp"] = pd.to_datetime(meter["timestamp"])
    meter = meter.sort_values("timestamp").reset_index(drop=True)

    # Gap detection
    expected_intervals = 35040
    if len(meter) < expected_intervals * 0.95:
        errors.append(
            f"Meter data has only {len(meter)} rows "
            f"(expected ~{expected_intervals})"
        )

    # Short gaps: interpolate; long gaps: flag
    meter["demand_kw"] = (
        meter["demand_kw"]
        .interpolate(method="linear", limit=8)  # up to 2 hr
    )

    # ---- Weather data ----------------------------------------------
    try:
        import pvlib
        weather_path = (
            DATA_DIR / "weather" / "USA_CA_Los.Angeles.TMY3.epw"
        )
        weather_df, _ = pvlib.iotools.read_epw(str(weather_path))
        weather_df = weather_df.reset_index()
        weather_df.columns = [str(c) for c in weather_df.columns]
        if "temp_air" in weather_df.columns:
            weather_df["T_outdoor_f"] = (
                weather_df["temp_air"] * 9 / 5 + 32
            )
    except Exception as e:
        errors.append(f"Weather load failed: {e}")
        weather_df = pd.DataFrame()

    # ---- CAISO prices ----------------------------------------------
    prices_path = DATA_DIR / "prices" / "caiso_dam_lmp_2023.csv"
    prices = pd.read_csv(prices_path)

    # ---- Solar profile ---------------------------------------------
    solar_path = DATA_DIR / "solar" / "pvwatts_100kw_socal.csv"
    solar = pd.read_csv(solar_path)
    solar["timestamp"] = pd.to_datetime(solar["timestamp"])

    state.update({
        "meter": meter,
        "weather": weather_df,
        "prices": prices,
        "solar": solar,
        "errors": errors,
    })

    print(f"Data agent: meter={len(meter)} rows, "
          f"solar={len(solar)} rows, errors={errors}")
    return state
```

**Done when:** running `run_data_agent({})` from a Python session
populates all four DataFrames and prints row counts with no fatal errors.

---

### Task 6.2 â€” agents/tariff_agent.py

```python
"""
Tariff agent: reconstructs baseline bill and builds rate schedule array.
See PLAN.md - Agent Architecture and Bill Calculator sections.
"""
import numpy as np
import pandas as pd
from analysis.bill_calculator import calculate_annual_bill
from analysis.tariff import get_energy_rate, get_demand_rates


def run_tariff_agent(state: dict) -> dict:
    """
    Reconstruct baseline annual bill and rate schedule.
    Requires state['meter'] to be populated by data_agent.
    """
    meter = state["meter"]
    annual_bill = calculate_annual_bill(meter)

    # Build per-timestep rate array ($/kWh)
    rate_schedule = np.array([
        get_energy_rate(ts) for ts in meter["timestamp"]
    ])

    state.update({
        "baseline_annual_bill": annual_bill["total"].sum(),
        "baseline_monthly_bills": annual_bill,
        "rate_schedule": rate_schedule,
    })

    total = annual_bill["total"].sum()
    peak = meter["demand_kw"].max()
    print(f"Tariff agent: baseline=${total:,.0f}/yr, peak={peak:.1f} kW")
    return state
```

**Done when:** calling `run_tariff_agent` on state with meter data prints
a baseline annual bill > $100,000 and peak demand 150â€“210 kW.

---

### Task 6.3 â€” agents/thermal_agent.py

```python
"""
Thermal agent: fits RC model and produces pre-cooling schedule.
See PLAN.md - Core Models and Seasonal Control Strategies sections.
"""
import numpy as np
import pandas as pd
from models.thermal_model import fit_rc_model, simulate_precooling


def run_thermal_agent(state: dict) -> dict:
    """
    Fit RC model from meter + weather data.
    Requires state['meter'] to be populated.
    """
    meter = state["meter"]

    # Merge weather temperature into meter if available
    weather = state.get("weather", pd.DataFrame())
    if not weather.empty and "T_outdoor_f" in weather.columns:
        # Weather is hourly; forward-fill to 15-min
        weather_ts = weather[["temp_air"]].copy()
        weather_ts.index = pd.to_datetime(weather_ts.index)
        weather_15min = weather_ts.resample("15min").ffill()
        weather_15min["T_outdoor_f"] = (
            weather_15min["temp_air"] * 9 / 5 + 32
        )
        meter = meter.copy()
        meter["T_outdoor_f"] = weather_15min["T_outdoor_f"].values[
            : len(meter)
        ]

    try:
        rc_params = fit_rc_model(meter)
    except Exception as e:
        print(f"Thermal agent: RC fit failed ({e}), using defaults")
        rc_params = {"R": 0.42, "C": 180.0, "r_squared": 0.0}

    # Simulate pre-cool window for a representative hot day
    T_test = np.full(24, 92.0)  # 6-hr afternoon at 92Â°F
    free_hrs = simulate_precooling(
        T_test, rc_params["R"], rc_params["C"], T_precool=70.0
    )

    state.update({
        "rc_params": rc_params,
        "free_loadshed_window_hours": free_hrs,
        "meter": meter,
    })

    print(
        f"Thermal agent: R={rc_params['R']}, C={rc_params['C']}, "
        f"R2={rc_params['r_squared']}, "
        f"free_loadshed={free_hrs:.2f}hr"
    )
    return state
```

**Done when:** `run_thermal_agent` populates `rc_params` and
`free_loadshed_window_hours` in state without crashing. R and C
must be positive floats.

---

### Task 6.4 â€” agents/optimizer_agent.py

```python
"""
Optimizer agent: runs MILP for each scenario and month.
Scenarios: baseline, solar, solar+hvac, solar+hvac+battery, full_stack.
See PLAN.md - Agent Architecture section.
"""
import numpy as np
import pandas as pd
from models.optimizer import optimize_dispatch
from models.solar_model import load_solar_profile
from analysis.tariff import get_energy_rate, get_demand_rates

SCENARIOS = [
    "baseline",
    "solar_only",
    "solar_hvac",
    "solar_hvac_battery",
    "full_stack",
]


def _get_solar(meter: pd.DataFrame, kw: float = 100.0) -> np.ndarray:
    solar_df = load_solar_profile(kw)
    merged = meter.merge(
        solar_df[["timestamp", "solar_kw"]], on="timestamp", how="left"
    )
    return merged["solar_kw"].fillna(0.0).values


def run_optimizer_agent(state: dict) -> dict:
    """
    Run MILP optimizer for each scenario (simplified: full-year with
    summer month as representative). Returns scenario bills.
    """
    meter = state["meter"]
    rc = state.get("rc_params", {"R": 0.42, "C": 180.0})
    rate_schedule = state["rate_schedule"]

    load = meter["demand_kw"].values
    solar_kw = _get_solar(meter)

    T_outdoor = meter.get("T_outdoor_f", pd.Series(np.full(len(meter), 75.0)))
    if isinstance(T_outdoor, pd.Series):
        T_outdoor = T_outdoor.values

    # Demand rate (summer on-peak + all-time for July)
    dr = get_demand_rates(7)
    demand_rate = dr.get("on_peak_kw", 0) + dr.get("all_time_kw", 0)

    results = {}

    # Baseline: no optimization, no solar
    baseline_bill = (load * rate_schedule * 0.25).sum() + demand_rate * load.max()
    results["baseline"] = {"bill": round(baseline_bill, 2)}

    # Solar only: subtract solar, same peak
    net_load = np.maximum(0.0, load - solar_kw)
    solar_bill = (
        (net_load * rate_schedule * 0.25).sum()
        + demand_rate * net_load.max()
    )
    results["solar_only"] = {"bill": round(solar_bill, 2)}

    # Full MILP (solar + battery, simplified to one month for smoke test)
    month_mask = meter["timestamp"].dt.month == 7
    month_load = load[month_mask.values]
    month_solar = solar_kw[month_mask.values]
    month_rates = rate_schedule[month_mask.values]
    month_T = T_outdoor[month_mask.values]

    opt_result = optimize_dispatch(
        load_kw=month_load,
        solar_kw=month_solar,
        prices_kwh=month_rates,
        tariff_rates=month_rates,
        demand_rate=demand_rate,
        T_outdoor=month_T,
        R=rc["R"],
        C=rc["C"],
    )

    results["solar_hvac_battery"] = {
        "bill": round(opt_result.get("total_cost") or 0.0, 2),
        "status": opt_result["status"],
        "peak_demand_kw": opt_result.get("peak_demand_kw"),
    }

    state["scenario_results"] = results
    print(f"Optimizer agent: {list(results.keys())} scenarios complete")
    for name, r in results.items():
        print(f"  {name}: ${r['bill']:,.0f}")
    return state
```

**Done when:** `run_optimizer_agent` populates `scenario_results` in
state. The optimized July bill should be lower than the solar-only July
bill.

---

### Task 6.5 â€” agents/report_agent.py

```python
"""
Report agent: generates charts, savings summary, and (optionally)
Claude narrative. Writes outputs/{timestamp}/savings_summary.json.
See PLAN.md - Output Format section.
"""
import json
import datetime
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from pathlib import Path
from analysis.savings_calculator import calculate_payback, CAPEX, DSGS_ANNUAL_REVENUE

matplotlib.use("Agg")


def _save_waterfall(waterfall: list[dict], fig_dir: Path) -> None:
    labels = [w["label"] for w in waterfall]
    values = [w["incremental"] for w in waterfall]
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["steelblue" if v >= 0 else "tomato" for v in values]
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("Annual Savings ($)")
    ax.set_title("Value Stack â€” Incremental Savings per Intervention")
    plt.xticks(rotation=20, ha="right")
    fig.tight_layout()
    fig.savefig(fig_dir / "waterfall.png", dpi=150)
    plt.close(fig)


def run_report_agent(state: dict) -> dict:
    """
    Write outputs/{timestamp}/ with charts and savings_summary.json.
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = Path("outputs") / ts
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    meter = state["meter"]
    baseline_bill = state.get("baseline_annual_bill", 0.0)
    scenarios = state.get("scenario_results", {})
    rc = state.get("rc_params", {})

    # Approximate annual savings from scenario bills
    baseline_annual = baseline_bill
    solar_bill = scenarios.get("solar_only", {}).get("bill", baseline_annual)
    opt_bill = scenarios.get(
        "solar_hvac_battery", {}
    ).get("bill", solar_bill)

    solar_savings = max(0.0, baseline_annual - solar_bill * 12)
    opt_savings = max(0.0, baseline_annual - opt_bill * 12)
    full_savings = opt_savings + DSGS_ANNUAL_REVENUE

    payback_solar = calculate_payback(solar_savings, CAPEX["solar_100kw"])
    payback_full = calculate_payback(
        full_savings, CAPEX["solar_100kw"] + CAPEX["battery_125kw_250kwh"]
    )

    waterfall = [
        {"label": "Baseline", "incremental": 0, "value": baseline_annual},
        {"label": "Solar", "incremental": solar_savings, "value": 0},
        {"label": "+ Battery + HVAC", "incremental": opt_savings - solar_savings,
         "value": 0},
        {"label": "+ Grid services", "incremental": DSGS_ANNUAL_REVENUE, "value": 0},
    ]
    _save_waterfall(waterfall, fig_dir)

    summary = {
        "run_id": ts,
        "building": {
            "type": "SecondarySchool",
            "location": "Mission Viejo, CA",
            "climate_zone": "3B",
            "peak_demand_kw": round(float(meter["demand_kw"].max()), 1),
            "annual_kwh": round(
                float((meter["demand_kw"] * 0.25).sum()), 0
            ),
        },
        "tariff": "SCE TOU-GS-3",
        "baseline_annual_bill": round(baseline_annual, 2),
        "scenarios": {
            "solar_only": {
                "annual_savings": round(solar_savings, 2),
                "capex": CAPEX["solar_100kw"],
                **payback_solar,
            },
            "full_stack": {
                "annual_savings": round(full_savings, 2),
                "capex": CAPEX["solar_100kw"] + CAPEX["battery_125kw_250kwh"],
                "grid_services_revenue": DSGS_ANNUAL_REVENUE,
                **payback_full,
            },
        },
        "engineering_tradeoffs": {
            "thermal_model_r2": rc.get("r_squared", None),
            "rc_resistance": rc.get("R", None),
            "rc_capacitance": rc.get("C", None),
            "free_loadshed_window_hours": state.get(
                "free_loadshed_window_hours", None
            ),
        },
    }

    json_path = out_dir / "savings_summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)

    state["output_dir"] = str(out_dir)
    state["savings_summary"] = summary
    print(f"Report agent: saved to {out_dir}")
    print(
        f"  Solar savings: ${solar_savings:,.0f}/yr, "
        f"payback={payback_solar.get('simple_payback_years')} yr"
    )
    return state
```

**Done when:** `run_report_agent` writes `savings_summary.json` and
`figures/waterfall.png` to an `outputs/{timestamp}/` directory.

---

### Task 6.6 â€” agents/orchestrator.py

```python
"""
LangGraph orchestrator agent.
Chains: data -> tariff -> thermal -> optimizer -> report.
See PLAN.md - Agent Architecture section.
"""
import argparse
from langgraph.graph import StateGraph, END
from agents.data_agent import run_data_agent
from agents.tariff_agent import run_tariff_agent
from agents.thermal_agent import run_thermal_agent
from agents.optimizer_agent import run_optimizer_agent
from agents.report_agent import run_report_agent


def build_graph() -> StateGraph:
    """Build the LangGraph StateGraph for the analysis pipeline."""
    graph = StateGraph(dict)

    graph.add_node("data", run_data_agent)
    graph.add_node("tariff", run_tariff_agent)
    graph.add_node("thermal", run_thermal_agent)
    graph.add_node("optimizer", run_optimizer_agent)
    graph.add_node("report", run_report_agent)

    graph.set_entry_point("data")
    graph.add_edge("data", "tariff")
    graph.add_edge("tariff", "thermal")
    graph.add_edge("thermal", "optimizer")
    graph.add_edge("optimizer", "report")
    graph.add_edge("report", END)

    return graph.compile()


def run_pipeline(meter_path: str = None) -> dict:
    """Run the full analysis pipeline. Returns final state."""
    initial_state: dict = {}
    if meter_path:
        initial_state["meter_path"] = meter_path

    app = build_graph()
    final_state = app.invoke(initial_state)
    return final_state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Elexity Building Energy Analysis Pipeline"
    )
    parser.add_argument(
        "--input",
        default="data/meter/school_ca_15min.parquet",
        help="Path to meter parquet file",
    )
    args = parser.parse_args()

    print("=== Elexity Building Energy Analysis ===\n")
    result = run_pipeline(meter_path=args.input)
    print(f"\nPipeline complete. Output: {result.get('output_dir')}")
```

**Done when:** `uv run python agents/orchestrator.py` runs all five
agents in sequence and prints the output directory path without crashing.

---

## Phase 7 â€” Streamlit Dashboard

### Task 7.1 â€” streamlit_app/app.py

```python
"""
Streamlit dashboard for interactive building energy savings simulation.
Three panels: Overview, Scenario Simulator, Engineering Tradeoffs.
See PLAN.md - Streamlit Dashboard section.
"""
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from analysis.bill_calculator import calculate_annual_bill
from models.solar_model import load_solar_profile
from analysis.savings_calculator import (
    run_solar_only, calculate_payback, CAPEX, DSGS_ANNUAL_REVENUE
)

st.set_page_config(
    page_title="Elexity Building Energy Analysis",
    layout="wide",
)

st.title("Elexity â€” Commercial Building DER Optimization")
st.caption("Southern California Secondary School | SCE TOU-GS-3 | CAISO")

# ---- Load data (cached) -------------------------------------------------

@st.cache_data
def load_meter() -> pd.DataFrame:
    df = pd.read_parquet("data/meter/school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@st.cache_data
def load_baseline_bill(df: pd.DataFrame) -> pd.DataFrame:
    return calculate_annual_bill(df)


meter_df = load_meter()
baseline_bills = load_baseline_bill(meter_df)
baseline_total = baseline_bills["total"].sum()

# ---- Panel 1: Building Overview ----------------------------------------

st.header("Panel 1 â€” Building Overview")

col1, col2, col3 = st.columns(3)
col1.metric("Annual Bill", f"${baseline_total:,.0f}")
col2.metric("Peak Demand", f"{meter_df['demand_kw'].max():.0f} kW")
col3.metric(
    "Annual Energy",
    f"{(meter_df['demand_kw'] * 0.25).sum() / 1000:.0f} MWh"
)

st.subheader("Monthly Bill Breakdown")
fig1, ax1 = plt.subplots(figsize=(10, 4))
months = baseline_bills["month"].values
ax1.bar(months, baseline_bills["energy_charge"], label="Energy")
ax1.bar(months, baseline_bills["demand_charge"],
        bottom=baseline_bills["energy_charge"], label="Demand")
ax1.bar(months, baseline_bills["fixed_charge"],
        bottom=baseline_bills["energy_charge"] + baseline_bills["demand_charge"],
        label="Fixed")
ax1.set_xlabel("Month")
ax1.set_ylabel("USD")
ax1.set_title("Monthly Bill â€” Energy / Demand / Fixed")
ax1.legend()
st.pyplot(fig1)

# ---- Panel 2: Scenario Simulator (interactive) -------------------------

st.header("Panel 2 â€” Scenario Simulator")

solar_kw = st.slider("Solar system size (kW)", 0, 500, 100, step=25)
battery_kw = st.slider("Battery power (kW)", 0, 500, 125, step=25)
battery_kwh = st.slider("Battery energy (kWh)", 0, 1000, 250, step=50)
dsgs = st.toggle("Enroll in DSGS grid services", value=True)

if solar_kw > 0:
    solar_df = run_solar_only(meter_df, solar_kw)
    solar_total = solar_df["total"].sum()
    solar_savings = baseline_total - solar_total
else:
    solar_savings = 0.0
    solar_total = baseline_total

grid_revenue = DSGS_ANNUAL_REVENUE if dsgs else 0.0
total_savings = solar_savings + grid_revenue

capex = 0
if solar_kw > 0:
    capex += CAPEX["solar_100kw"] * (solar_kw / 100)
if battery_kw > 0:
    capex += CAPEX["battery_125kw_250kwh"] * (battery_kwh / 250)

payback = calculate_payback(total_savings, capex) if capex > 0 else {}

col_a, col_b, col_c = st.columns(3)
col_a.metric("Estimated Annual Savings", f"${total_savings:,.0f}")
col_b.metric("Capital Cost", f"${capex:,.0f}")
col_c.metric(
    "Simple Payback",
    (
        f"{payback.get('simple_payback_years', 'N/A')} yr"
        if payback.get("simple_payback_years")
        else "N/A"
    ),
)

# ---- Panel 3: Engineering Tradeoffs -----------------------------------

st.header("Panel 3 â€” Engineering Tradeoffs")
st.info(
    "See PLAN.md for the four key engineering tradeoffs: "
    "pre-cool depth, battery sizing, grid services conflict, "
    "and seasonal strategy differences."
)

sizes = [50, 75, 100, 125, 150, 200]
# Simplified demand charge savings estimate (linear diminishing returns)
savings_by_size = [
    min(27000, 27000 * (s / 125) ** 0.6) for s in sizes
]
fig3, ax3 = plt.subplots(figsize=(7, 4))
ax3.plot(sizes, savings_by_size, "o-", color="steelblue")
ax3.axvline(125, color="red", linestyle="--", label="Default (125 kW)")
ax3.set_xlabel("Battery Power (kW)")
ax3.set_ylabel("Annual Demand Charge Savings ($)")
ax3.set_title("Battery Size vs Demand Charge Savings (diminishing returns)")
ax3.legend()
st.pyplot(fig3)
```

**Done when:** `uv run streamlit run streamlit_app/app.py` opens at
`http://localhost:8501` with all three panels rendering without errors.
Moving the solar slider updates the savings metric.

---

## Phase 8 [DONE] â€” Notebook Deliverable

### Task 8.1 [DONE] â€” notebooks/analysis.ipynb

Create `notebooks/analysis.ipynb` with the following 7 sections as
markdown + code cells. Each section should be runnable top-to-bottom.

Structure (cell-by-cell outline):

```
Cell 1 [markdown]: Title + executive summary (2-3 sentences)
Cell 2 [code]:     imports + load data (meter, weather, prices, tariff)
Cell 3 [markdown]: Section 1 â€” Data Loading and Validation
Cell 4 [code]:     print row counts, date range, peak demand, annual kWh
Cell 5 [markdown]: Section 2 â€” Cost Driver Analysis
Cell 6 [code]:     calculate_annual_bill(), plot heatmap + scatter
Cell 7 [markdown]: Section 3 â€” Thermal Model Calibration
Cell 8 [code]:     fit_rc_model(), print R, C, R^2
Cell 9 [markdown]: Section 4 â€” Investment Recommendations
Cell 10 [code]:    run_solar_only(), waterfall data, print scenario bills
Cell 11 [markdown]:Section 5 â€” Payback Analysis
Cell 12 [code]:    calculate_payback() for each scenario, print table
Cell 13 [markdown]:Section 6 â€” Engineering Tradeoffs (narrative)
Cell 14 [code]:    plot pre-cool curve, battery sizing curve
Cell 15 [markdown]:Section 7 â€” Next Steps and Limitations
```

Create the notebook using Jupyter:

```bash
uv run jupyter notebook notebooks/analysis.ipynb
```

Or create it programmatically if running headless:

```bash
uv run jupyter nbconvert --to notebook --execute notebooks/analysis.ipynb
```

**Done when:** `uv run jupyter nbconvert --execute --to html \
notebooks/analysis.ipynb` completes without errors and produces
`notebooks/analysis.html` with all 7 sections visible.

---

## Phase 9 [DONE] â€” FastAPI Service + Docker

Reference: PLAN.md â€” FastAPI Service + Docker (Phase 9)

The analysis pipeline is wrapped in a FastAPI service testable via
Swagger UI (`/docs`). A `docker-compose.yml` runs the API service
(port 8000) and the Streamlit dashboard (port 8501) from the same
image.

---

### Task 9.1 [DONE] â€” Add FastAPI dependencies

```bash
uv add fastapi "uvicorn[standard]" httpx
```

Verify `pyproject.toml` now contains `fastapi`, `uvicorn`, and `httpx`
in the `[project] dependencies` list.

**Done when:** `uv run python -c "import fastapi; print(fastapi.__version__)"
` prints a version >= 0.111.

---

### Task 9.2 [DONE] â€” api/schemas.py

Create `api/__init__.py` (empty) and `api/schemas.py`:

```python
"""
Pydantic request and response models for the FastAPI service.
All monetary values in USD, power in kW, energy in kWh.
"""
from pydantic import BaseModel, Field


class MonthRequest(BaseModel):
    month: int = Field(..., ge=1, le=12, description="Month number 1-12")


class OptimizeRequest(BaseModel):
    month: int = Field(..., ge=1, le=12)
    solar_kw: float = Field(100.0, ge=0, le=1000,
                            description="Installed PV size (kW)")
    battery_power_kw: float = Field(125.0, ge=0, le=500,
                                    description="Battery power rating (kW)")
    battery_energy_kwh: float = Field(250.0, ge=0, le=2000,
                                      description="Battery capacity (kWh)")
    enable_precool: bool = Field(True,
                                 description="Allow HVAC pre-cooling")
    enable_dsgs: bool = Field(True,
                              description="Enroll in DSGS demand response")


class AnnualSavingsRequest(BaseModel):
    solar_kw: float = Field(100.0, ge=0, le=1000)
    battery_power_kw: float = Field(125.0, ge=0, le=500)
    battery_energy_kwh: float = Field(250.0, ge=0, le=2000)
    enable_precool: bool = True
    enable_dsgs: bool = True


class MonthlyBillResponse(BaseModel):
    month: int
    energy_charge: float
    demand_charge: float
    fixed_charge: float
    total: float
    peak_demand_kw: float
    on_peak_demand_kw: float
    total_kwh: float


class HealthResponse(BaseModel):
    status: str
    data_rows: int
    peak_demand_kw: float
```

**Done when:** `uv run python -c "from api.schemas import OptimizeRequest;
print('OK')"` prints OK.

---

### Task 9.3 [DONE] â€” api/main.py

Create `api/main.py`. This is the main FastAPI application.

```python
"""
FastAPI service for Elexity building energy analysis.

Endpoints:
  GET  /health             â€” data load check
  GET  /tariff             â€” full SCE TOU-GS-3 rate schedule
  POST /bill/monthly       â€” reconstruct one month's bill
  POST /bill/annual        â€” reconstruct all 12 months
  POST /cost-driver        â€” bill component % shares
  POST /optimize           â€” run MILP optimizer for one month
  POST /savings/annual     â€” full-year savings waterfall + NPV

Swagger UI: http://localhost:8000/docs
ReDoc:      http://localhost:8000/redoc
"""
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException

from analysis.bill_calculator import (
    calculate_annual_bill,
    calculate_monthly_bill,
    _load_meter,
)
from analysis.tariff import load_tariff
from api.schemas import (
    AnnualSavingsRequest,
    HealthResponse,
    MonthlyBillResponse,
    MonthRequest,
    OptimizeRequest,
)

# â”€â”€ Shared state loaded once at startup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_df: pd.DataFrame = None
_tariff: dict = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _df, _tariff
    _df = _load_meter()
    _tariff = load_tariff()
    yield


app = FastAPI(
    title="Elexity Building Energy Analysis API",
    description=(
        "REST API for SCE TOU-GS-3 bill reconstruction, DER dispatch "
        "optimization, and savings analysis for a C&I secondary school "
        "in Southern California."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# â”€â”€ Health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    """Confirm the service is running and data is loaded."""
    if _df is None:
        raise HTTPException(status_code=503, detail="Data not loaded")
    return HealthResponse(
        status="ok",
        data_rows=len(_df),
        peak_demand_kw=round(float(_df["demand_kw"].max()), 1),
    )


# â”€â”€ Tariff â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/tariff", tags=["Tariff"])
def get_tariff():
    """Return the full SCE TOU-GS-3 rate schedule."""
    return _tariff


# â”€â”€ Bill â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.post(
    "/bill/monthly",
    response_model=MonthlyBillResponse,
    tags=["Bill"],
)
def bill_monthly(req: MonthRequest):
    """Reconstruct one month's SCE TOU-GS-3 bill from meter data."""
    try:
        result = calculate_monthly_bill(_df, req.month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.post("/bill/annual", tags=["Bill"])
def bill_annual():
    """Reconstruct all 12 months' bills. Returns list + annual totals."""
    annual = calculate_annual_bill(_df)
    rows = annual.to_dict(orient="records")
    totals = {
        "annual_total": round(annual["total"].sum(), 2),
        "annual_energy_charge": round(annual["energy_charge"].sum(), 2),
        "annual_demand_charge": round(annual["demand_charge"].sum(), 2),
        "annual_fixed_charge": round(annual["fixed_charge"].sum(), 2),
        "annual_kwh": round(annual["total_kwh"].sum(), 1),
    }
    return {"months": rows, "annual": totals}


# â”€â”€ Cost driver â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.post("/cost-driver", tags=["Analysis"])
def cost_driver():
    """
    Decompose annual bill into energy / demand / fixed % shares.
    Also returns monthly peak demand array for heatmap rendering.
    """
    annual = calculate_annual_bill(_df)
    grand = annual["total"].sum()
    shares = {
        "energy_pct": round(annual["energy_charge"].sum() / grand * 100, 1),
        "demand_pct": round(annual["demand_charge"].sum() / grand * 100, 1),
        "fixed_pct": round(annual["fixed_charge"].sum() / grand * 100, 1),
    }
    monthly_peaks = annual[["month", "peak_demand_kw"]].to_dict(
        orient="records"
    )
    return {"shares": shares, "monthly_peaks": monthly_peaks}


# â”€â”€ Optimizer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.post("/optimize", tags=["Optimization"])
def optimize(req: OptimizeRequest):
    """
    Run MILP optimizer for one month with the specified DER configuration.
    Returns dispatch schedule and savings vs baseline bill.

    Note: optimizer module is built in Phase 4. This endpoint returns a
    placeholder until models/optimizer.py exists.
    """
    try:
        from models.optimizer import optimize_dispatch  # noqa: F401
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail=(
                "Optimizer not yet built (Phase 4). "
                "Complete TASKS.md Phase 4 first."
            ),
        )
    # Full implementation wired in Phase 4
    raise HTTPException(status_code=501, detail="Wire-up in Phase 4")


@app.post("/savings/annual", tags=["Optimization"])
def savings_annual(req: AnnualSavingsRequest):
    """
    Run optimizer across all 12 months and return savings waterfall.
    Returns: baseline_bill, optimized_bill, savings, NPV, payback_years.

    Placeholder until Phase 5 savings_calculator.py is built.
    """
    try:
        from analysis.savings_calculator import compute_annual_savings  # noqa
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail=(
                "Savings calculator not yet built (Phase 5). "
                "Complete TASKS.md Phase 5 first."
            ),
        )
    raise HTTPException(status_code=501, detail="Wire-up in Phase 5")
```

**Done when:**

```bash
uv run uvicorn api.main:app --reload --port 8000
```

Opens in browser at `http://localhost:8000/docs` and the following
`curl` commands return 200:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/tariff
curl -X POST http://localhost:8000/bill/monthly \
     -H "Content-Type: application/json" \
     -d '{"month": 7}'
curl -X POST http://localhost:8000/bill/annual \
     -H "Content-Type: application/json" -d '{}'
curl -X POST http://localhost:8000/cost-driver \
     -H "Content-Type: application/json" -d '{}'
```

`/bill/monthly` for month 7 returns `total` > 3000.
`/cost-driver` returns `demand_pct` > 20.

---

### Task 9.4 [DONE] â€” tests/test_api.py

Create `tests/__init__.py` (empty) and `tests/test_api.py`:

```python
"""
Smoke tests for the FastAPI service.
Run with: uv run pytest tests/test_api.py -v
No Docker needed â€” uses in-process TestClient.
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["data_rows"] == 35040
    assert 150 <= data["peak_demand_kw"] <= 220


def test_tariff_has_summer_rates():
    r = client.get("/tariff")
    assert r.status_code == 200
    tariff = r.json()
    summer = tariff["energy_charges_per_kwh"]["summer"]
    assert abs(summer["on_peak"]["rate"] - 0.28317) < 0.001


def test_bill_monthly_july():
    r = client.post("/bill/monthly", json={"month": 7})
    assert r.status_code == 200
    data = r.json()
    assert data["month"] == 7
    assert data["total"] > 3000
    assert data["peak_demand_kw"] > 0


def test_bill_monthly_invalid():
    r = client.post("/bill/monthly", json={"month": 13})
    assert r.status_code == 422  # Pydantic validation


def test_bill_annual_twelve_months():
    r = client.post("/bill/annual", json={})
    assert r.status_code == 200
    data = r.json()
    assert len(data["months"]) == 12
    assert data["annual"]["annual_total"] > 50000


def test_cost_driver_shares_sum_to_100():
    r = client.post("/cost-driver", json={})
    assert r.status_code == 200
    shares = r.json()["shares"]
    total = shares["energy_pct"] + shares["demand_pct"] + shares["fixed_pct"]
    assert abs(total - 100.0) < 0.5


def test_optimize_returns_501_before_phase4():
    r = client.post(
        "/optimize",
        json={"month": 7, "solar_kw": 100, "battery_power_kw": 125,
              "battery_energy_kwh": 250, "enable_precool": True,
              "enable_dsgs": True},
    )
    assert r.status_code == 501
```

**Done when:** `uv run pytest tests/test_api.py -v` passes all 7 tests.

---

### Task 9.5 [DONE] â€” Dockerfile

Create `Dockerfile` at the project root:

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app

# Install uv from official image layer
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first (layer cache)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source
COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

# Default: FastAPI on 8000
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
```

**Done when:** `docker build -t elexity-analysis .` completes with no
errors.

---

### Task 9.6 [DONE] â€” docker-compose.yml

Create `docker-compose.yml` at the project root:

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data:ro
      - ./outputs:/app/outputs
    env_file: .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3

  dash:
    build: .
    command: >
      uv run streamlit run streamlit_app/app.py
      --server.port 8501
      --server.address 0.0.0.0
    ports:
      - "8501:8501"
    volumes:
      - ./data:/app/data:ro
    env_file: .env
    depends_on:
      api:
        condition: service_healthy
```

**Done when:** `docker compose up` starts both services and:
- `http://localhost:8000/docs` shows Swagger UI
- `http://localhost:8000/health` returns `{"status": "ok", ...}`
- `http://localhost:8501` shows Streamlit dashboard

---

### Task 9.7 [DONE] â€” Integration sanity check

After `docker compose up`, run full pipeline sanity check via the API:

```bash
# Annual bill via API
curl -s -X POST http://localhost:8000/bill/annual \
     -H "Content-Type: application/json" -d '{}' | python -m json.tool

# Cost driver shares
curl -s -X POST http://localhost:8000/cost-driver \
     -H "Content-Type: application/json" -d '{}' | python -m json.tool
```

Check returned values against targets:

| Metric | Expected range |
|---|---|
| `annual.annual_total` | $70,000â€“$220,000 |
| `annual.annual_kwh` | 250,000â€“2,000,000 |
| Peak demand (July) | 20â€“220 kW |
| `shares.demand_pct` | 20â€“45% |
| `shares.energy_pct` | 50â€“75% |

**Done when:** all metrics in range and both services healthy.

---

## Phase 10 â€” DA Price Forecast

### Task 10.1 â€” models/price_forecast.py

Replaces the perfect-foresight assumption. Builds a simple day-ahead
price shape model from historical CAISO LMPs.
See PLAN.md â€” Version 2 Roadmap / Market Layer Architecture.

```python
"""
Day-ahead price forecast model for CAISO SP15 zone.
Produces hourly LMP forecast for next 24hr from seasonal median
+ temperature adjustment. Replaces ex-post perfect foresight.

Sources:
  CAISO 2024 Battery Storage Report (may-2025)
  LBNL Navigating Modeling Frontiers for ESRs (2024)
"""
import numpy as np
import pandas as pd
from pathlib import Path

_PRICES_CSV = (
    Path(__file__).parents[1] / "data" / "prices" / "caiso_dam_lmp_2023.csv"
)


def build_price_shape(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute median LMP by (month, hour_of_day) from historical data.
    This is the 'seasonal shape' used as a prior for DA forecasting.

    Returns DataFrame indexed by (month, hour) with columns:
      median_lmp, p10_lmp, p90_lmp  (all in $/MWh)
    """
    df = prices_df.copy()
    df["ts"] = pd.to_datetime(df["INTERVALSTARTTIME_GMT"], utc=True)
    df["month"] = df["ts"].dt.month
    df["hour"] = df["ts"].dt.hour
    df["lmp"] = pd.to_numeric(df["MW"], errors="coerce")

    shape = (
        df.groupby(["month", "hour"])["lmp"]
        .agg(
            median_lmp="median",
            p10_lmp=lambda x: x.quantile(0.10),
            p90_lmp=lambda x: x.quantile(0.90),
        )
        .reset_index()
    )
    return shape


def forecast_da_prices(
    target_date: pd.Timestamp,
    price_shape: pd.DataFrame,
    T_outdoor_forecast: np.ndarray = None,
    temp_sensitivity: float = 0.8,
) -> pd.DataFrame:
    """
    Produce a 24-hour DA price forecast for a given date.

    Args:
        target_date: the delivery date (D+0).
        price_shape: output of build_price_shape().
        T_outdoor_forecast: 24-element array of hourly temps (Â°F).
            If provided, adds a temperature adjustment term.
        temp_sensitivity: $/MWh per Â°F above 85Â°F. Captures the
            afternoon price spike driven by cooling demand.

    Returns:
        DataFrame with columns: hour, forecast_lmp, p10, p90.
    """
    month = target_date.month
    shape_month = price_shape[price_shape["month"] == month].copy()

    forecast = shape_month[["hour", "median_lmp", "p10_lmp", "p90_lmp"]].copy()
    forecast = forecast.rename(
        columns={"median_lmp": "forecast_lmp", "p10_lmp": "p10", "p90_lmp": "p90"}
    )

    if T_outdoor_forecast is not None and len(T_outdoor_forecast) == 24:
        heat_adjustment = np.maximum(0.0, T_outdoor_forecast - 85.0) * temp_sensitivity
        forecast["forecast_lmp"] = forecast["forecast_lmp"].values + heat_adjustment
        forecast["p10"] = forecast["p10"].values + heat_adjustment * 0.5
        forecast["p90"] = forecast["p90"].values + heat_adjustment * 1.5

    forecast["forecast_lmp"] = forecast["forecast_lmp"].round(2)
    return forecast.reset_index(drop=True)


def load_and_forecast(
    target_date: str = "2023-07-15",
    T_outdoor_forecast: np.ndarray = None,
) -> pd.DataFrame:
    """Load historical prices and return DA forecast for target_date."""
    prices = pd.read_csv(_PRICES_CSV)
    shape = build_price_shape(prices)
    target = pd.Timestamp(target_date)
    return forecast_da_prices(target, shape, T_outdoor_forecast)


if __name__ == "__main__":
    # Forecast for a hot summer weekday (July 15)
    T_hot = np.array([
        68, 66, 65, 64, 64, 65, 68, 72, 76, 80, 84, 87,
        90, 92, 93, 93, 92, 90, 87, 84, 80, 76, 73, 70
    ], dtype=float)

    fc = load_and_forecast("2023-07-15", T_hot)
    print("DA price forecast for 2018-07-15 (hot day):")
    print(fc[["hour", "forecast_lmp", "p10", "p90"]].to_string(index=False))
    peak_hour = fc.loc[fc["forecast_lmp"].idxmax()]
    print(
        f"\nPeak forecast: ${peak_hour['forecast_lmp']:.2f}/MWh "
        f"at hour {int(peak_hour['hour'])}:00"
    )
```

**Done when:** `uv run python models/price_forecast.py` prints a 24-row
DA price forecast table with a clear afternoon peak (hours 14â€“20) above
$50/MWh on the hot-day scenario, and a flat night-time trough below $30.

---

### Task 10.2 â€” Validate forecast vs perfect foresight

```python
import pandas as pd
import numpy as np
from models.price_forecast import load_and_forecast, build_price_shape

prices = pd.read_csv("data/prices/caiso_dam_lmp_2023.csv")
shape = build_price_shape(prices)

# Compute RMSE of median forecast vs actual for summer months
prices["ts"] = pd.to_datetime(prices["INTERVALSTARTTIME_GMT"], utc=True)
prices["month"] = prices["ts"].dt.month
prices["hour"] = prices["ts"].dt.hour
prices["lmp"] = pd.to_numeric(prices["MW"], errors="coerce")

summer = prices[prices["month"].isin([6, 7, 8, 9])]
merged = summer.merge(
    shape[shape["month"].isin([6, 7, 8, 9])],
    on=["month", "hour"],
    how="left",
)
rmse = np.sqrt(((merged["lmp"] - merged["median_lmp"]) ** 2).mean())
bias = (merged["median_lmp"] - merged["lmp"]).mean()
print(f"Forecast RMSE: ${rmse:.2f}/MWh  Bias: ${bias:.2f}/MWh")
print("(CAISO 2024 report: operators pad sell bids ~$230/MWh above DA)")
```

**Done when:** RMSE is printed (expect $10â€“$30/MWh for seasonal median
baseline). This establishes the forecast quality baseline before adding
ML improvements in later iterations.

---

## Phase 11 â€” Rolling MPC Controller

### Task 11.1 â€” models/mpc_controller.py

Wraps `models/optimizer.py` in a rolling 24hr MPC loop.
See PLAN.md â€” Version 2 Roadmap / Market Layer Architecture.

```python
"""
Rolling Model Predictive Control (MPC) for battery dispatch.
Re-solves the MILP every 15 minutes with updated SoC and price forecast.
Implements the Day-Ahead layer (known prices) and a simplified
Real-Time layer (forecast prices updated every 15 min).

Reference: LBNL "Navigating Modeling Frontiers for ESRs" (2024)
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from models.optimizer import optimize_dispatch
from models.price_forecast import build_price_shape, forecast_da_prices


@dataclass
class MPCState:
    """Mutable controller state carried between 15-min intervals."""
    soc_kwh: float = 125.0          # 50% of 250kWh default
    realized_grid_kw: list = field(default_factory=list)
    realized_cost_usd: list = field(default_factory=list)
    dispatch_log: list = field(default_factory=list)


def run_mpc_day(
    load_kw: np.ndarray,
    solar_kw: np.ndarray,
    actual_prices_kwh: np.ndarray,
    forecast_prices_kwh: np.ndarray,
    demand_rate: float,
    state: MPCState,
    battery_power_kw: float = 125.0,
    battery_energy_kwh: float = 250.0,
    dt: float = 0.25,
    horizon_intervals: int = 96,
) -> MPCState:
    """
    Run one full day (96 x 15-min intervals) of rolling MPC.

    At each interval:
      1. Re-solve MILP with current SoC and remaining-day price forecast.
      2. Apply only the first dispatch interval (receding horizon).
      3. Advance SoC using actual power (not optimal).
      4. Record realized grid draw and cost at actual price.

    Args:
        load_kw: actual 96-element load array (kW).
        solar_kw: actual 96-element solar output (kW).
        actual_prices_kwh: actual 96-element RT prices ($/kWh).
        forecast_prices_kwh: forecast 96-element DA prices ($/kWh).
        demand_rate: $/kW for peak demand this month.
        state: MPCState carrying SoC from prior intervals.
        horizon_intervals: how many future intervals the MILP optimizes.
        dt: timestep in hours.

    Returns:
        Updated MPCState.
    """
    n = len(load_kw)
    eta = np.sqrt(0.92)  # one-way efficiency

    for t in range(n):
        remaining = n - t
        h = min(horizon_intervals, remaining)

        result = optimize_dispatch(
            load_kw=load_kw[t: t + h],
            solar_kw=solar_kw[t: t + h],
            prices_kwh=forecast_prices_kwh[t: t + h],
            tariff_rates=forecast_prices_kwh[t: t + h],
            demand_rate=demand_rate,
            battery_power_kw=battery_power_kw,
            battery_energy_kwh=battery_energy_kwh,
        )

        if result["status"] not in ("optimal", "optimal_inaccurate"):
            # Fallback: do nothing this interval
            p_charge_t = 0.0
            p_discharge_t = 0.0
        else:
            p_charge_t = float(result["p_charge"][0])
            p_discharge_t = float(result["p_discharge"][0])

        # Advance SoC with actual physics
        state.soc_kwh += (p_charge_t * eta - p_discharge_t / eta) * dt
        state.soc_kwh = np.clip(
            state.soc_kwh,
            battery_energy_kwh * 0.10,
            battery_energy_kwh * 0.95,
        )

        # Realized grid draw and cost at actual price
        grid_kw = (
            load_kw[t] - solar_kw[t] + p_charge_t - p_discharge_t
        )
        cost_interval = (
            grid_kw * actual_prices_kwh[t] * dt
        )

        state.realized_grid_kw.append(round(grid_kw, 3))
        state.realized_cost_usd.append(round(cost_interval, 4))
        state.dispatch_log.append({
            "interval": t,
            "soc_kwh": round(state.soc_kwh, 2),
            "p_charge_kw": round(p_charge_t, 3),
            "p_discharge_kw": round(p_discharge_t, 3),
            "grid_kw": round(grid_kw, 3),
            "forecast_price": round(forecast_prices_kwh[t], 4),
            "actual_price": round(actual_prices_kwh[t], 4),
        })

    return state


def compare_mpc_vs_perfect(
    load_kw: np.ndarray,
    solar_kw: np.ndarray,
    actual_prices_kwh: np.ndarray,
    forecast_prices_kwh: np.ndarray,
    demand_rate: float,
    battery_power_kw: float = 125.0,
    battery_energy_kwh: float = 250.0,
) -> dict:
    """
    Compare MPC (forecast prices) vs perfect foresight (actual prices).
    Returns a dict with cost under each approach and the gap.
    """
    # Perfect foresight: use actual prices as forecast
    state_pf = MPCState(soc_kwh=battery_energy_kwh * 0.50)
    state_pf = run_mpc_day(
        load_kw, solar_kw, actual_prices_kwh, actual_prices_kwh,
        demand_rate, state_pf, battery_power_kw, battery_energy_kwh,
    )

    # MPC: use forecast prices
    state_mpc = MPCState(soc_kwh=battery_energy_kwh * 0.50)
    state_mpc = run_mpc_day(
        load_kw, solar_kw, actual_prices_kwh, forecast_prices_kwh,
        demand_rate, state_mpc, battery_power_kw, battery_energy_kwh,
    )

    cost_pf = sum(state_pf.realized_cost_usd)
    cost_mpc = sum(state_mpc.realized_cost_usd)

    return {
        "perfect_foresight_cost": round(cost_pf, 2),
        "mpc_forecast_cost": round(cost_mpc, 2),
        "gap_usd": round(cost_mpc - cost_pf, 2),
        "gap_pct": round((cost_mpc - cost_pf) / abs(cost_pf) * 100, 1)
        if cost_pf != 0 else None,
    }


if __name__ == "__main__":
    import pandas as pd
    from analysis.tariff import get_energy_rate, get_demand_rates
    from models.price_forecast import load_and_forecast

    df = pd.read_parquet("data/meter/school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Use one week in July for smoke test
    week = df[
        (df["timestamp"].dt.month == 7)
        & (df["timestamp"].dt.day <= 7)
    ].copy()

    load = week["demand_kw"].values
    solar = np.zeros(len(load))
    actual_rates = np.array([
        get_energy_rate(ts) for ts in week["timestamp"]
    ])

    # DA forecast rates (seasonal median, no temp adjustment here)
    fc = load_and_forecast("2023-07-01")
    # Expand hourly forecast to 15-min intervals for the week
    fc_rates = np.tile(fc["forecast_lmp"].values / 1000, 7 * 4)[:len(load)]

    dr = get_demand_rates(7)
    demand_rate = dr.get("on_peak_kw", 0) + dr.get("all_time_kw", 0)

    comparison = compare_mpc_vs_perfect(
        load_kw=load,
        solar_kw=solar,
        actual_prices_kwh=actual_rates,
        forecast_prices_kwh=fc_rates,
        demand_rate=demand_rate,
    )
    print("MPC vs Perfect Foresight (July week):")
    for k, v in comparison.items():
        print(f"  {k}: {v}")
```

**Done when:** `uv run python models/mpc_controller.py` prints the
comparison dict. `gap_pct` should be in the range 5â€“25% (MPC pays more
than perfect foresight due to price forecast error â€” this is the
real-world information loss the model now captures).

---

## Phase 12 â€” CAISO Ancillary Services Value Stack

### Task 12.1 â€” Download CAISO AS prices

Add CAISO ancillary service price download to the data pipeline.
CAISO OASIS provides historical AS prices (Regulation, Spin) free.

```python
"""
Download CAISO ancillary service clearing prices for 2018.
Append to scripts/download_data.py or run standalone.
"""
import requests, zipfile, io, time, pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

AS_DIR = Path("data") / "ancillary_services"
AS_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://oasis.caiso.com/oasisapi/SingleZip"

AS_PRODUCTS = {
    "REG_UP":  "AS_MILEAGE_UP",
    "REG_DN":  "AS_MILEAGE_DN",
    "SPIN":    "AS_SPIN",
    "NONSPIN": "AS_NONSPIN",
}


def download_as_prices(product: str, year: int = 2023) -> pd.DataFrame:
    """Download one AS product for a full year, month by month."""
    frames = []
    for month in range(1, 13):
        start = datetime(year, month, 1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end -= timedelta(days=1)

        params = {
            "queryname": "PRC_AS",
            "startdatetime": start.strftime("%Y%m%dT00:00-0800"),
            "enddatetime":   end.strftime("%Y%m%dT23:00-0800"),
            "version": "1",
            "market_run_id": "DAM",
            "anc_type": product,
            "anc_region": "AS_CAISO_EXP",
            "resultformat": "6",
        }
        try:
            r = requests.get(BASE_URL, params=params, timeout=60)
            z = zipfile.ZipFile(io.BytesIO(r.content))
            csv_name = [f for f in z.namelist() if f.endswith(".csv")][0]
            df = pd.read_csv(z.open(csv_name))
            frames.append(df)
            print(f"  {product} {start.strftime('%B %Y')}: {len(df)} rows")
            time.sleep(2)
        except Exception as e:
            print(f"  {product} {start.strftime('%B %Y')} failed: {e}")

    if frames:
        result = pd.concat(frames, ignore_index=True)
        out = AS_DIR / f"caiso_as_{product.lower()}_2018.csv"
        result.to_csv(out, index=False)
        print(f"Saved: {out}")
        return result
    return pd.DataFrame()


if __name__ == "__main__":
    for product in ["REG_UP", "REG_DN", "SPIN"]:
        download_as_prices(product, 2018)
```

**Done when:** three CSV files exist in `data/ancillary_services/`:
`caiso_as_reg_up_2023.csv`, `caiso_as_reg_dn_2023.csv`,
`caiso_as_spin_2023.csv`, each with >= 8,000 rows.
If CAISO OASIS download fails, the module falls back to generating
synthetic AS prices based on 2023 published annual averages.

---

### Task 12.2 â€” analysis/ancillary_services.py

```python
"""
CAISO ancillary services revenue estimation.
Estimates Regulation Up/Down + Spinning Reserve revenue for a
125kW/250kWh battery in CAISO, subject to ASSOC constraints.

Key rules (CAISO Tariff Section 8, Nov 2025):
  - Same MW can be bid into multiple AS types simultaneously.
  - ASSOC: battery must hold >= 30 min of all AS awards.
  - DSGS and CAISO AS are mutually exclusive per interval.

Reference: CAISO 2024 Battery Storage Special Report.
"""
import numpy as np
import pandas as pd
from pathlib import Path

AS_DIR = Path("data") / "ancillary_services"

# ASSOC: minimum SoC headroom fraction for each product (30-min rule)
ASSOC_HEADROOM = {
    "reg_up": 0.5,   # 30 min / 60 min = 0.50 of capacity reserved
    "reg_dn": 0.5,
    "spin":   0.5,
}

# Regulatory: for DSGS Option 3, cannot stack DSGS + CAISO AS
# in the same interval. DSGS events are May-Oct, triggered by grid stress.
DSGS_MONTHS = [5, 6, 7, 8, 9, 10]


def load_as_prices(product: str) -> pd.DataFrame:
    """Load historical AS prices, falling back to synthetic if absent."""
    path = AS_DIR / f"caiso_as_{product}_2018.csv"
    if path.exists():
        df = pd.read_csv(path)
        return df

    # Synthetic fallback based on 2018 CAISO published annual averages
    # Reg Up: ~$10/MWh avg, Spin: ~$5/MWh avg (varies widely by season)
    np.random.seed(789)
    timestamps = pd.date_range("2023-01-01", "2023-12-31 23:00", freq="h")
    avg = {"reg_up": 10.0, "reg_dn": 8.0, "spin": 5.0}.get(product, 7.0)
    prices = np.maximum(0, np.random.lognormal(
        mean=np.log(avg), sigma=0.8, size=len(timestamps)
    ))
    df = pd.DataFrame({
        "INTERVALSTARTTIME_GMT": timestamps.strftime("%Y-%m-%dT%H:00:00Z"),
        "MW": prices.round(2),
        "product": product,
    })
    print(f"  Using synthetic {product} prices (avg ${prices.mean():.1f}/MWh)")
    return df


def estimate_as_revenue(
    battery_power_kw: float = 125.0,
    battery_energy_kwh: float = 250.0,
    dsgs_events_per_year: int = 15,
    dsgs_duration_hr: float = 2.0,
    dsgs_rate_kwh: float = 2.00,
) -> dict:
    """
    Estimate annual CAISO AS + DSGS revenue for a battery.

    Strategy:
      - During DSGS event hours: dispatch for DSGS (mutually exclusive).
      - All other hours: bid Reg Up + Reg Down + Spin into CAISO AS.
      - ASSOC: offer only 50% of battery power into AS to hold headroom.

    Returns:
        dict with annual revenue breakdown by product.
    """
    reg_up = load_as_prices("reg_up")
    reg_dn = load_as_prices("reg_dn")
    spin = load_as_prices("spin")

    # Convert to $/kWh (prices are in $/MWh)
    reg_up_avg = reg_up["MW"].mean() / 1000
    reg_dn_avg = reg_dn["MW"].mean() / 1000
    spin_avg = spin["MW"].mean() / 1000

    # AS-eligible capacity: 50% of battery power (ASSOC headroom)
    as_capacity_kw = battery_power_kw * (1 - ASSOC_HEADROOM["reg_up"])

    # Hours per year available for CAISO AS (not DSGS events)
    dsgs_hours = dsgs_events_per_year * dsgs_duration_hr
    as_hours = 8760 - dsgs_hours

    # Revenue: capacity payment * hours * price per kWh-of-capacity
    # Simplified: treated as capacity payments per kW-hour offered
    reg_up_rev = as_capacity_kw * as_hours * reg_up_avg
    reg_dn_rev = as_capacity_kw * as_hours * reg_dn_avg
    spin_rev   = as_capacity_kw * as_hours * spin_avg

    # DSGS revenue
    dsgs_energy_kwh = battery_power_kw * dsgs_duration_hr * dsgs_events_per_year
    dsgs_rev = dsgs_energy_kwh * dsgs_rate_kwh

    total = reg_up_rev + reg_dn_rev + spin_rev + dsgs_rev

    return {
        "reg_up_annual_usd": round(reg_up_rev, 0),
        "reg_dn_annual_usd": round(reg_dn_rev, 0),
        "spin_annual_usd": round(spin_rev, 0),
        "dsgs_annual_usd": round(dsgs_rev, 0),
        "total_grid_services_usd": round(total, 0),
        "as_capacity_offered_kw": as_capacity_kw,
        "dsgs_hours_per_year": dsgs_hours,
        "note": (
            "DSGS and CAISO AS are mutually exclusive per interval. "
            "See CAISO Tariff Sec 8 + DSGS 5th Edition (2026)."
        ),
    }


if __name__ == "__main__":
    result = estimate_as_revenue()
    print("\nCAISO AS + DSGS Revenue Estimate (125kW / 250kWh battery):")
    for k, v in result.items():
        if k != "note":
            print(f"  {k}: {v}")
    print(f"\n  Note: {result['note']}")
    print(
        "\nExpected ranges (CAISO 2024 report):"
        "\n  Reg Up + Down: $15,000-$25,000/yr for 125kW battery"
        "\n  DSGS: $6,000-$10,000/yr (15 events x 2hr x 125kW x $2/kWh)"
    )
```

**Done when:** `uv run python analysis/ancillary_services.py` prints an
annual revenue breakdown. Total grid services revenue should be in the
range $20,000â€“$40,000/year, with Regulation Up + Down as the largest
component ($15,000â€“$25,000) and DSGS as a smaller additive component
($6,000â€“$10,000). The note confirming mutual exclusivity must print.

---

### Task 12.3 â€” Integrate AS revenue into savings_calculator.py

Update `analysis/savings_calculator.py` to add the full AS value stack
to the waterfall chart alongside the existing scenario stack.

```python
# Add at the bottom of analysis/savings_calculator.py

from analysis.ancillary_services import estimate_as_revenue


def run_full_stack_with_as(
    df: pd.DataFrame,
    solar_kw: float = 100.0,
    battery_power_kw: float = 125.0,
    battery_energy_kwh: float = 250.0,
) -> dict:
    """
    Compute the complete value stack including CAISO AS revenue.
    Extends the Phase 1 savings_calculator with the Phase 2 AS layer.

    Returns dict with all revenue streams and updated payback.
    """
    baseline = run_baseline(df)["total"].sum()
    solar_bill = run_solar_only(df, solar_kw)["total"].sum()
    solar_savings = baseline - solar_bill

    as_result = estimate_as_revenue(battery_power_kw, battery_energy_kwh)
    total_grid_services = as_result["total_grid_services_usd"]

    total_savings = solar_savings + total_grid_services
    capex = (
        CAPEX["solar_100kw"] * (solar_kw / 100)
        + CAPEX["battery_125kw_250kwh"] * (battery_energy_kwh / 250)
    )
    payback = calculate_payback(total_savings, capex)

    return {
        "baseline_annual_bill": round(baseline, 2),
        "solar_savings": round(solar_savings, 2),
        "reg_up_revenue": as_result["reg_up_annual_usd"],
        "reg_dn_revenue": as_result["reg_dn_annual_usd"],
        "spin_revenue": as_result["spin_annual_usd"],
        "dsgs_revenue": as_result["dsgs_annual_usd"],
        "total_annual_value": round(total_savings, 2),
        "capex": round(capex, 2),
        **payback,
    }
```

**Done when:** calling `run_full_stack_with_as(df)` returns a dict with
all six revenue streams populated. Total annual value should be
$70,000â€“$130,000/year (solar savings ~$40k + AS ~$20â€“35k). Payback
should be 3.5â€“6 years.

---

## Quick Reference

| What | Where |
|---|---|
| Architecture overview | [PLAN.md](PLAN.md) |
| Version 2 market design | PLAN.md â€” Version 2 Roadmap |
| Full model code details | [CONTEXT.md](CONTEXT.md) |
| Tariff rates | `data/tariff/sce_tou_gs3.json` |
| Tariff parser | `analysis/tariff.py` |
| Bill calculator | `analysis/bill_calculator.py` |
| Thermal model | `models/thermal_model.py` |
| Battery model | `models/battery_model.py` |
| MILP optimizer | `models/optimizer.py` |
| DA price forecast | `models/price_forecast.py` |
| MPC controller | `models/mpc_controller.py` |
| AS value stack | `analysis/ancillary_services.py` |
| Agent pipeline | `agents/orchestrator.py` |
| Dashboard | `streamlit_app/app.py` (port 8501) |
| Sanity-check numbers | PLAN.md â€” Sanity-Check Numbers |







