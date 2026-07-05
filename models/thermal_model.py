"""
RC thermal model for a commercial building.
Calibrates the thermal resistance R (degF-hr/kWh) from HVAC load vs
outdoor temperature using least-squares curve fitting, then estimates
the thermal capacitance C assuming a 2-hour time constant.

See PLAN.md -- Core Models section for physics equations.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import curve_fit
from scipy.stats import pearsonr


def _steady_state_hvac(
    T_outdoor: np.ndarray,
    R: float,
    T_setpoint: float = 72.0,
) -> np.ndarray:
    """Steady-state HVAC kW needed to hold indoor temperature at setpoint."""
    return np.maximum(0.0, (T_outdoor - T_setpoint) / R)


def fit_rc_model(
    df: pd.DataFrame,
    hvac_col: str = "out.electricity.hvac.demand_kw",
    temp_col: str = "T_outdoor_f",
    T_setpoint: float = 72.0,
) -> dict:
    """
    Fit thermal resistance R from HVAC load-vs-temperature scatter.

    Filters to cooling season, occupied hours, and positive HVAC load
    before fitting to avoid noise from heating and unoccupied periods.

    Args:
        df:          15-min interval DataFrame with 'timestamp' column.
        hvac_col:    Column name for HVAC electricity demand (kW).
        temp_col:    Column name for outdoor temperature (degF).
        T_setpoint:  Indoor comfort setpoint (degF). Default 72.

    Returns:
        dict with keys R, C, r_squared, n_samples, T_setpoint.

    Warns if R^2 < 0.70 (building may not be HVAC-dominated).
    """
    for col in (hvac_col, temp_col):
        if col not in df.columns:
            raise ValueError(f"Required column missing from DataFrame: {col}")

    # Filter: cooling season + positive HVAC + warm outdoor temp
    mask = (
        df["timestamp"].dt.month.isin([5, 6, 7, 8, 9, 10])
        & (df[hvac_col] > 1.0)
        & (df[temp_col] > 65.0)
    )
    sub = df[mask].dropna(subset=[hvac_col, temp_col])

    if len(sub) < 100:
        raise ValueError(
            f"Too few samples ({len(sub)}) for RC fit. "
            "Check HVAC and temperature columns."
        )

    T_out = sub[temp_col].values
    hvac_kw = sub[hvac_col].values

    popt, _ = curve_fit(
        lambda T, R: _steady_state_hvac(T, R, T_setpoint),
        T_out,
        hvac_kw,
        p0=[0.4],
        bounds=(0.01, 10.0),
    )
    R = float(popt[0])

    predicted = _steady_state_hvac(T_out, R, T_setpoint)
    corr, _ = pearsonr(hvac_kw, predicted)
    r_squared = corr ** 2

    # Estimate C from time constant: tau = R*C, assume tau = 2 hr
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
            f"  WARNING: R^2={r_squared:.3f} < 0.70. "
            "Building may not be HVAC-dominated or data is synthetic. "
            "Pre-cooling savings estimates will be approximate."
        )
    else:
        print(
            f"  RC model fit: R={R:.4f} degF-hr/kWh, "
            f"C={C:.1f} kWh/degF, R^2={r_squared:.3f}"
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
    Simulate indoor temperature drift after HVAC setpoint is raised.

    The building is pre-cooled to T_precool, then the HVAC is effectively
    off (setpoint raised above comfort band). Indoor temperature rises
    due to heat transfer from the warm outdoor environment.

    Args:
        T_outdoor_series: Outdoor temperature at each timestep (degF).
        R:                Thermal resistance (degF-hr/kWh).
        C:                Thermal capacitance (kWh/degF).
        T_precool:        Indoor temperature after pre-cooling (degF).
        T_comfort_max:    Upper comfort limit; load-shed ends here (degF).
        T_setpoint:       Normal HVAC setpoint (degF).
        dt:               Timestep in hours (0.25 for 15-min intervals).

    Returns:
        Hours before indoor temperature exceeds T_comfort_max.
        Returns the full horizon duration if limit is never reached.
    """
    T = float(T_precool)
    for i, T_out in enumerate(T_outdoor_series):
        dT = (T_out - T) / (R * C) * dt
        T = T + dT
        if T >= T_comfort_max:
            return round(i * dt, 2)
    return round(len(T_outdoor_series) * dt, 2)


def precooling_energy_kwh(
    R: float,
    T_precool: float = 70.0,
    T_setpoint: float = 72.0,
    dt: float = 0.25,
    n_steps: int = 8,
) -> float:
    """
    Estimate extra energy consumed pre-cooling the building.

    Approximates as the steady-state HVAC load at the cooler setpoint
    times the pre-cooling duration.

    Returns: energy in kWh.
    """
    delta_kw = _steady_state_hvac(
        np.array([T_setpoint]), R, T_precool
    )[0]
    return round(delta_kw * n_steps * dt, 2)


if __name__ == "__main__":
    _DATA = Path(__file__).parent.parent / "data" / "meter"
    df = pd.read_parquet(_DATA / "school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    print("Fitting RC thermal model to meter data...")
    params = fit_rc_model(df)
    print(f"  RC params: {params}")

    # Pre-cooling simulation: hot July afternoon at 92 degF
    T_afternoon = np.full(24, 92.0)  # 6 hours at 92 degF (24 x 15-min)
    free_hrs = simulate_precooling(
        T_afternoon,
        params["R"],
        params["C"],
        T_precool=70.0,
    )
    extra_kwh = precooling_energy_kwh(params["R"], T_precool=70.0)
    print(f"\n  Pre-cooling scenario: T_outdoor=92 degF, T_precool=70 degF")
    print(f"  Free load-shed window : {free_hrs:.2f} hr")
    print(f"  Extra pre-cool energy : {extra_kwh:.2f} kWh")
    print(f"  (Expected: ~2-3 hr free window for a commercial school)")
