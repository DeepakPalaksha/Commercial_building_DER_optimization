"""
Optimizer agent: runs the MILP dispatch optimizer per scenario.

For the full pipeline run the agent uses the savings_calculator
(rule-based, fast) for the annual waterfall, and runs the MILP on
a representative summer month (August) for the detailed dispatch
result. This keeps the pipeline runtime under 2 minutes.

Inputs from state:
  state['meter']          -- full-year meter DataFrame
  state['rate_schedule']  -- np.ndarray, $/kWh per step
  state['rc_params']      -- dict from thermal_agent
  state['baseline_annual_bill'] -- float

Outputs to state:
  state['scenario_results']  -- dict of scenario -> bill/savings
  state['annual_waterfall']  -- list of waterfall dicts

See PLAN.md -- Agent Architecture section.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.savings_calculator import (
    run_baseline,
    run_solar_only,
    run_solar_hvac,
    run_solar_hvac_battery,
    build_waterfall,
    DSGS_ANNUAL_REVENUE,
)
from models.optimizer import optimize_dispatch
from models.solar_model import load_solar_profile
from analysis.tariff import get_demand_rates, classify_period

SCENARIOS = [
    "baseline",
    "solar_only",
    "solar_hvac",
    "solar_hvac_battery",
    "full_stack",
]


def _get_solar_array(meter: pd.DataFrame, kw: float = 100.0) -> np.ndarray:
    solar_df = load_solar_profile(kw)
    merged = meter.merge(
        solar_df[["timestamp", "solar_kw"]], on="timestamp", how="left"
    )
    return merged["solar_kw"].fillna(0.0).values.astype(float)


def run_optimizer_agent(state: dict) -> dict:
    """
    1. Run the full annual savings calculator (rule-based, fast).
    2. Run the MILP on August (best summer month for demo) for the
       detailed optimised dispatch result.
    """
    meter: pd.DataFrame = state["meter"]
    rc = state.get("rc_params", {"R": 0.42, "C": 5.0})
    rate_schedule: np.ndarray = state["rate_schedule"]
    baseline_total: float = state["baseline_annual_bill"]

    # ── Annual scenario bills (rule-based, fast) ─────────────────────
    print("[optimizer_agent] Running annual scenario calculations...")
    solar_bill_df = run_solar_only(meter)
    solar_hvac_df = run_solar_hvac(meter)
    solar_hvac_bat_df = run_solar_hvac_battery(meter)

    solar_total = float(solar_bill_df["total"].sum())
    solar_hvac_total = float(solar_hvac_df["total"].sum())
    solar_hvac_bat_total = float(solar_hvac_bat_df["total"].sum())
    full_stack_total = solar_hvac_bat_total + DSGS_ANNUAL_REVENUE

    waterfall = build_waterfall(
        baseline_total,
        solar_total,
        solar_hvac_total,
        solar_hvac_bat_total,
        full_stack_total,
    )

    scenario_results = {
        "baseline": {
            "annual_bill": round(baseline_total, 2),
            "annual_savings": 0.0,
        },
        "solar_only": {
            "annual_bill": round(solar_total, 2),
            "annual_savings": round(baseline_total - solar_total, 2),
        },
        "solar_hvac": {
            "annual_bill": round(solar_hvac_total, 2),
            "annual_savings": round(baseline_total - solar_hvac_total, 2),
        },
        "solar_hvac_battery": {
            "annual_bill": round(solar_hvac_bat_total, 2),
            "annual_savings": round(
                baseline_total - solar_hvac_bat_total, 2
            ),
        },
        "full_stack": {
            "annual_bill": round(
                solar_hvac_bat_total - DSGS_ANNUAL_REVENUE, 2
            ),
            "annual_savings": round(
                baseline_total - solar_hvac_bat_total + DSGS_ANNUAL_REVENUE,
                2,
            ),
            "dsgs_revenue": DSGS_ANNUAL_REVENUE,
        },
    }

    # ── MILP detailed dispatch: August (representative summer month) ──
    print("[optimizer_agent] Running MILP on August (detailed dispatch)...")
    aug_mask = meter["timestamp"].dt.month == 8
    aug_load = meter.loc[aug_mask, "demand_kw"].values.astype(float)
    aug_solar = _get_solar_array(meter)[aug_mask.values]
    aug_rates = rate_schedule[aug_mask.values]

    # Build TOU masks for August (summer: on-peak applies)
    aug_ts_list = meter.loc[aug_mask, "timestamp"].tolist()
    on_peak_mask = np.array(
        [classify_period(t) == "on_peak"  for t in aug_ts_list]
    )
    mid_peak_mask = np.array(
        [classify_period(t) == "mid_peak" for t in aug_ts_list]
    )

    dr = get_demand_rates(8)  # August = summer rates

    milp_result = optimize_dispatch(
        load_kw=aug_load,
        solar_kw=aug_solar,
        prices_kwh=aug_rates,
        tariff_rates=aug_rates,
        on_peak_mask=on_peak_mask,
        mid_peak_mask=mid_peak_mask,
        on_peak_rate=dr.get("on_peak_kw", 19.10),
        mid_peak_rate=dr.get("mid_peak_kw", 5.80),
        all_time_rate=dr.get("all_time_kw", 8.85),
        # Skip thermal sub-problem for the August MILP:
        # RC thermal constraints can become infeasible when
        # T_outdoor is very high and comfort bounds are tight.
        # Thermal pre-cooling is handled by run_solar_hvac() above.
        T_outdoor=None,
        R=None,
        C=None,
    )

    milp_bill = milp_result.get("total_cost")
    if milp_bill is None or (
        isinstance(milp_bill, float) and not np.isfinite(milp_bill)
    ):
        milp_bill = None   # solver returned infeasible or unbounded
    scenario_results["milp_august"] = {
        "status":       milp_result["status"],
        "bill":         round(milp_bill, 2) if milp_bill is not None else None,
        "peak_on_kw":   milp_result.get("peak_on_kw"),
        "peak_mid_kw":  milp_result.get("peak_mid_kw"),
        "peak_all_kw":  milp_result.get("peak_all_kw"),
        "peak_demand_kw": milp_result.get("peak_demand_kw"),  # compat
    }

    # Print summary
    print(f"[optimizer_agent] Scenario bills:")
    for name, r in scenario_results.items():
        bill = r.get("annual_bill") or r.get("bill")
        bill_str = f"${bill:>10,.0f}" if bill is not None else "     N/A"
        savings = r.get("annual_savings", "")
        tag = f"  savings=${savings:,.0f}/yr" if savings else ""
        print(f"  {name:<22} {bill_str}{tag}")

    if milp_result["status"] in ("optimal", "optimal_inaccurate"):
        aug_peak_base = float(aug_load.max())
        on_peak_base = (
            float(aug_load[on_peak_mask].max()) if on_peak_mask.any()
            else 0.0
        )
        peak_on_opt  = milp_result.get("peak_on_kw")  or on_peak_base
        peak_all_opt = milp_result.get("peak_all_kw") or aug_peak_base
        print(
            f"  MILP August (3-demand):"
            f" on-peak {on_peak_base:.1f} → {peak_on_opt:.1f} kW"
            f" | all-time {aug_peak_base:.1f} → {peak_all_opt:.1f} kW"
        )

    state.update({
        "scenario_results": scenario_results,
        "annual_waterfall": waterfall,
        "milp_august_result": milp_result,
    })
    return state
