"""
Report agent: writes outputs/{timestamp}/ with charts, JSON summary,
and (optionally) a Claude narrative for the waterfall.

Outputs written:
  outputs/{ts}/savings_summary.json   -- full structured results
  outputs/{ts}/figures/waterfall.png  -- incremental savings bar chart
  outputs/{ts}/figures/dispatch.png   -- August MILP dispatch timeline

Inputs from state:
  state['meter'], state['rc_params'], state['baseline_annual_bill'],
  state['scenario_results'], state['annual_waterfall'],
  state['milp_august_result'] (optional)

See PLAN.md -- Output Format section.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.savings_calculator import (
    CAPEX,
    DSGS_ANNUAL_REVENUE,
    calculate_payback,
)

matplotlib.use("Agg")


# ── Chart helpers ─────────────────────────────────────────────────────────

def _save_waterfall(waterfall: list[dict], fig_dir: Path) -> None:
    """Incremental savings bar chart for the value stack."""
    labels = [w["label"] for w in waterfall]
    values = [w["incremental"] for w in waterfall]
    colors = ["#2196F3" if v >= 0 else "#F44336" for v in values]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(labels, values, color=colors, edgecolor="white", width=0.6)

    for bar, val in zip(bars, values):
        if val != 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 100,
                f"${val:,.0f}",
                ha="center", va="bottom", fontsize=9, fontweight="bold",
            )

    ax.set_ylabel("Annual Savings / Revenue ($)", fontsize=11)
    ax.set_title(
        "DER Value Stack — Incremental Annual Savings", fontsize=12,
        fontweight="bold",
    )
    ax.axhline(0, color="black", linewidth=0.8)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda x, _: f"${x:,.0f}")
    )
    plt.xticks(rotation=15, ha="right", fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "waterfall.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {fig_dir / 'waterfall.png'}")


def _save_dispatch(
    milp_result: dict,
    meter: pd.DataFrame,
    fig_dir: Path,
) -> None:
    """August MILP dispatch timeline (first 7 days)."""
    if milp_result.get("status") not in ("optimal", "optimal_inaccurate"):
        return

    aug_mask = meter["timestamp"].dt.month == 8
    ts = meter.loc[aug_mask, "timestamp"].values
    load = meter.loc[aug_mask, "demand_kw"].values

    p_grid = milp_result.get("p_grid")
    p_charge = milp_result.get("p_charge")
    p_discharge = milp_result.get("p_discharge")
    soc = milp_result.get("soc")
    if p_grid is None:
        return

    # First 7 days = 672 intervals
    n = 672
    t_range = range(min(n, len(p_grid)))
    x = [i * 0.25 for i in t_range]   # hours

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

    axes[0].plot(x, load[:n], color="#455A64", alpha=0.5, label="Baseline load")
    axes[0].plot(x, p_grid[:n], color="#1976D2", label="Optimised grid import")
    axes[0].set_ylabel("Power (kW)")
    axes[0].set_title("August MILP Dispatch — First 7 Days", fontweight="bold")
    axes[0].legend(fontsize=8)

    axes[1].bar(
        x,
        [c - d for c, d in zip(p_charge[:n], p_discharge[:n])],
        color=["#4CAF50" if v > 0 else "#F44336"
               for v in (p_charge[:n] - p_discharge[:n])],
        width=0.22, alpha=0.8,
    )
    axes[1].set_ylabel("Battery (kW)\n+charge / -discharge")
    axes[1].axhline(0, color="black", linewidth=0.5)

    if soc is not None:
        axes[2].plot(x, soc[:n], color="#FF9800", linewidth=1.5)
        axes[2].set_ylabel("SoC (kWh)")
    axes[2].set_xlabel("Hour of month")

    fig.tight_layout()
    fig.savefig(fig_dir / "dispatch_august.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {fig_dir / 'dispatch_august.png'}")


# ── Main agent function ───────────────────────────────────────────────────

def run_report_agent(state: dict) -> dict:
    """
    Write outputs/{timestamp}/ with charts and savings_summary.json.
    """
    run_ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = Path("outputs") / run_ts
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    meter: pd.DataFrame = state["meter"]
    baseline_annual: float = state.get("baseline_annual_bill", 0.0)
    scenarios: dict = state.get("scenario_results", {})
    waterfall: list = state.get("annual_waterfall", [])
    rc: dict = state.get("rc_params", {})
    milp: dict = state.get("milp_august_result", {})

    # ── Charts ────────────────────────────────────────────────────────
    if waterfall:
        _save_waterfall(waterfall, fig_dir)
    if milp:
        _save_dispatch(milp, meter, fig_dir)

    # ── Financial metrics ─────────────────────────────────────────────
    solar_savings = scenarios.get("solar_only", {}).get(
        "annual_savings", 0.0
    )
    full_savings = scenarios.get("full_stack", {}).get(
        "annual_savings", 0.0
    )

    payback_solar = calculate_payback(
        solar_savings, CAPEX["solar_100kw"]
    )
    payback_full = calculate_payback(
        full_savings, CAPEX["full_stack"]
    )

    # ── JSON summary ──────────────────────────────────────────────────
    summary = {
        "run_id": run_ts,
        "building": {
            "type": "SecondarySchool",
            "location": "Mission Viejo, CA",
            "climate_zone": "3B",
            "utility": "SCE",
            "tariff": "TOU-GS-3",
            "data_year": 2023,
            "peak_demand_kw": round(float(meter["demand_kw"].max()), 1),
            "annual_kwh": round(
                float((meter["demand_kw"] * 0.25).sum()), 0
            ),
            "annual_mwh": round(
                float((meter["demand_kw"] * 0.25).sum()) / 1000, 1
            ),
        },
        "baseline_annual_bill_usd": round(baseline_annual, 2),
        "scenarios": {
            name: {
                k: (round(v, 2) if isinstance(v, float) else v)
                for k, v in r.items()
            }
            for name, r in scenarios.items()
        },
        "waterfall": waterfall,
        "payback": {
            "solar_only": payback_solar,
            "full_stack": payback_full,
        },
        "engineering_tradeoffs": {
            "thermal_model_r2": rc.get("r_squared"),
            "rc_resistance_degf_hr_per_kwh": rc.get("R"),
            "rc_capacitance_kwh_per_degf": rc.get("C"),
            "time_constant_hours": (
                round(rc["R"] * rc["C"], 2)
                if rc.get("R") and rc.get("C") else None
            ),
            "free_loadshed_window_hours": state.get(
                "free_loadshed_window_hours"
            ),
        },
        "milp_august": {
            "status": milp.get("status"),
            "peak_demand_kw": milp.get("peak_demand_kw"),
        },
        "output_dir": str(out_dir),
    }

    def _json_safe(obj):
        """Replace non-finite floats with null so the output is valid JSON.

        Python's json module serialises float('inf') as the bare token
        ``Infinity``, which is valid JavaScript but NOT valid JSON (RFC 8259).
        Any JSON parser (VS Code, jq, Python json.loads) will reject it with
        'Value expected' or a similar error.
        """
        import math
        if isinstance(obj, float) and not math.isfinite(obj):
            return None
        raise TypeError(type(obj))

    json_path = out_dir / "savings_summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2, default=_json_safe)

    # ── Console summary ───────────────────────────────────────────────
    print(f"\n[report_agent] Output written to: {out_dir}")
    print(
        f"  Baseline bill:  ${baseline_annual:>10,.0f}/yr"
    )
    print(
        f"  Solar savings:  ${solar_savings:>10,.0f}/yr  "
        f"(payback {payback_solar.get('simple_payback_years', '?')} yr)"
    )
    print(
        f"  Full-stack:     ${full_savings:>10,.0f}/yr  "
        f"(payback {payback_full.get('simple_payback_years', '?')} yr)"
    )

    state["output_dir"] = str(out_dir)
    state["savings_summary"] = summary
    return state
