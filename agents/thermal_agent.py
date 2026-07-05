"""
Thermal agent: calibrates the RC thermal model from meter data
and produces a pre-cooling schedule recommendation.

Inputs from state:
  state['meter']    -- populated by data_agent (must have T_outdoor_f)
  state['weather']  -- optional EPW DataFrame; used to override temperature

Outputs to state:
  state['rc_params']                  -- dict {R, C, r_squared, ...}
  state['free_loadshed_window_hours'] -- float, hr of free load-shed

See PLAN.md -- Core Models and Seasonal Control Strategies sections.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from models.thermal_model import (
    fit_rc_model,
    simulate_precooling,
    precooling_energy_kwh,
)

# Fallback RC params if calibration fails (typical commercial school)
_FALLBACK_RC = {"R": 0.42, "C": 5.0, "r_squared": 0.0, "n_samples": 0,
                "T_setpoint": 72.0}


def run_thermal_agent(state: dict) -> dict:
    """
    Fit RC model from meter data and estimate pre-cooling potential.
    """
    meter: pd.DataFrame = state["meter"].copy()
    weather: pd.DataFrame = state.get("weather", pd.DataFrame())

    # ── Optionally replace T_outdoor_f with EPW temperature ──────────
    if not weather.empty and "temp_air" in weather.columns:
        try:
            weather_ts = weather[["temp_air"]].copy()
            weather_ts.index = pd.to_datetime(weather_ts.index)
            weather_15min = weather_ts.resample("15min").ffill()
            weather_15min["T_outdoor_f"] = (
                weather_15min["temp_air"] * 9 / 5 + 32
            )
            meter["T_outdoor_f"] = (
                weather_15min["T_outdoor_f"].values[: len(meter)]
            )
        except Exception as exc:
            print(f"  [thermal_agent] EPW temperature merge failed: {exc}")

    # ── RC calibration ────────────────────────────────────────────────
    try:
        rc_params = fit_rc_model(meter)
    except Exception as exc:
        print(
            f"  [thermal_agent] RC fit failed ({exc}), using fallback params"
        )
        rc_params = _FALLBACK_RC.copy()

    # ── Pre-cooling simulation (representative hot afternoon) ─────────
    T_afternoon = np.full(24, 92.0)   # 6 hours at 92 degF (24 x 15-min)
    free_hrs = simulate_precooling(
        T_afternoon,
        rc_params["R"],
        rc_params["C"],
        T_precool=70.0,
        T_comfort_max=76.0,
    )
    extra_kwh = precooling_energy_kwh(
        rc_params["R"], T_precool=70.0, T_setpoint=72.0
    )

    print(
        f"[thermal_agent] R={rc_params['R']:.4f}, "
        f"C={rc_params['C']:.1f}, "
        f"R2={rc_params['r_squared']:.3f}, "
        f"free_loadshed={free_hrs:.2f} hr, "
        f"precool_extra={extra_kwh:.1f} kWh"
    )

    state.update({
        "rc_params": rc_params,
        "free_loadshed_window_hours": free_hrs,
        "precooling_energy_kwh": extra_kwh,
        "meter": meter,   # may have updated T_outdoor_f from EPW
    })
    return state
