"""
Tariff agent: reconstructs the baseline electricity bill and builds
a per-timestep rate schedule array.

Inputs from state:
  state['meter']   -- populated by data_agent

Outputs to state:
  state['baseline_annual_bill']    -- float, total annual bill ($)
  state['baseline_monthly_bills']  -- DataFrame from calculate_annual_bill
  state['rate_schedule']           -- np.ndarray, $/kWh per 15-min step

See PLAN.md -- Agent Architecture and Bill Calculator sections.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.bill_calculator import calculate_annual_bill
from analysis.tariff import get_energy_rate, get_demand_rates


def run_tariff_agent(state: dict) -> dict:
    """
    Reconstruct baseline annual bill and build per-timestep rate array.
    """
    meter: pd.DataFrame = state["meter"]

    # ── Baseline bill ────────────────────────────────────────────────
    annual_bill = calculate_annual_bill(meter)
    baseline_total = float(annual_bill["total"].sum())

    # ── Per-timestep energy rate array ───────────────────────────────
    # Used by optimizer_agent as the tariff_rates input to optimize_dispatch.
    rate_schedule = np.array(
        [get_energy_rate(ts) for ts in meter["timestamp"]]
    )

    # ── Demand rate summary (summer for reference) ───────────────────
    summer_dr = get_demand_rates(7)   # July rates as representative
    peak_kw = float(meter["demand_kw"].max())
    annual_kwh = float((meter["demand_kw"] * 0.25).sum())

    print(
        f"[tariff_agent] baseline=${baseline_total:,.0f}/yr, "
        f"peak={peak_kw:.1f} kW, "
        f"annual_energy={annual_kwh/1000:.0f} MWh"
    )
    print(
        f"  Bill split: "
        f"energy={annual_bill['energy_charge'].sum():,.0f}, "
        f"demand={annual_bill['demand_charge'].sum():,.0f}, "
        f"fixed={annual_bill['fixed_charge'].sum():,.0f}"
    )

    state.update({
        "baseline_annual_bill": baseline_total,
        "baseline_monthly_bills": annual_bill,
        "rate_schedule": rate_schedule,
        "summer_demand_rates": summer_dr,
    })
    return state
