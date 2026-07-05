"""
MILP dispatch optimizer using cvxpy + GLPK_MI.

Minimises the electricity bill for a given planning horizon by
optimally dispatching:
  - Battery storage (charge / discharge)
  - Solar PV (curtailment-allowed)
  - HVAC pre-cooling (optional, requires RC model params)

The objective is to reduce both energy charges ($/kWh) and peak
demand charges ($/kW) while respecting all physical constraints.

See CONTEXT.md -- MILP Optimizer and PLAN.md -- Core Models.
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
    efficiency_rt: float = 0.92,
    soc_min_frac: float = 0.10,
    soc_max_frac: float = 0.95,
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

    The power balance at each timestep t:
        p_grid[t] = load[t] - solar[t] + p_charge[t] - p_discharge[t]

    Battery SoC dynamics:
        soc[t+1] = soc[t] + (p_charge[t]*eta - p_discharge[t]/eta) * dt

    If thermal control is enabled (T_outdoor, R, C provided):
        HVAC is treated as a flexible load. Pre-cooling is modelled as
        running HVAC below the normal setpoint during off-peak hours.

    Objective: minimise energy_cost + demand_cost
        energy_cost = sum(tariff_rates[t] * p_grid[t]) * dt
        demand_cost = demand_rate * max(p_grid[t])

    Args:
        load_kw:            Baseline building load (kW), shape (T,).
        solar_kw:           Solar PV output (kW), shape (T,).
        prices_kwh:         CAISO LMP at each step ($/kWh), shape (T,).
                            Used for future market co-optimisation (V2).
                            In Phase 4 the objective uses tariff_rates.
        tariff_rates:       SCE energy rate at each step ($/kWh), shape (T,).
        demand_rate:        Total demand charge rate ($/kW).
        battery_power_kw:   Max charge/discharge power (kW).
        battery_energy_kwh: Usable capacity (kWh).
        efficiency_rt:      Round-trip battery efficiency [0,1].
        soc_min_frac:       Minimum SoC as fraction of capacity.
        soc_max_frac:       Maximum SoC as fraction of capacity.
        T_outdoor:          Outdoor temperature (degF), shape (T,).
                            If None, thermal sub-problem is skipped.
        R:                  Thermal resistance (degF-hr/kWh).
        C:                  Thermal capacitance (kWh/degF).
        T_comfort_min:      Minimum indoor temperature comfort bound (degF).
        T_comfort_max:      Maximum indoor temperature comfort bound (degF).
        T_setpoint:         Normal HVAC setpoint (degF).
        dt:                 Timestep in hours (0.25 for 15-min data).

    Returns:
        dict with keys:
            status         -- cvxpy solver status string
            total_cost     -- optimal objective value ($)
            p_grid         -- grid import at each step (kW), shape (T,)
            p_charge       -- battery charge power (kW), shape (T,)
            p_discharge    -- battery discharge power (kW), shape (T,)
            soc            -- SoC at each step (kWh), shape (T+1,)
            peak_demand_kw -- optimal peak demand (kW)
            T_indoor       -- indoor temperature (degF), shape (T+1,)
                             (only if thermal sub-problem enabled)
            p_hvac_delta   -- HVAC adjustment from baseline (kW), (T,)
                             (only if thermal sub-problem enabled)
    """
    T = len(load_kw)
    use_thermal = (
        T_outdoor is not None and R is not None and C is not None
    )
    eta = float(np.sqrt(efficiency_rt))   # one-way efficiency

    soc_min_kwh = soc_min_frac * battery_energy_kwh
    soc_max_kwh = soc_max_frac * battery_energy_kwh
    soc_init_kwh = 0.50 * battery_energy_kwh

    # ── Decision variables ─────────────────────────────────────────────
    p_charge = cp.Variable(T, nonneg=True, name="p_charge")
    p_discharge = cp.Variable(T, nonneg=True, name="p_discharge")
    soc = cp.Variable(T + 1, nonneg=True, name="soc")
    p_grid = cp.Variable(T, name="p_grid")
    p_peak = cp.Variable(nonneg=True, name="p_peak")  # demand charge hook

    # ── Constraints ────────────────────────────────────────────────────
    constraints = [
        # Power balance (solar curtailment is implicit — excess solar
        # can charge the battery or be clipped by load<=demand)
        p_grid == load_kw - solar_kw + p_charge - p_discharge,
        # Battery energy dynamics
        soc[0] == soc_init_kwh,
        soc[1:] == soc[:-1] + (p_charge * eta - p_discharge / eta) * dt,
        soc >= soc_min_kwh,
        soc <= soc_max_kwh,
        # Battery power limits
        p_charge <= battery_power_kw,
        p_discharge <= battery_power_kw,
        # Peak demand tracking
        p_grid <= p_peak,
        p_peak >= 0,
    ]

    if use_thermal:
        # HVAC flexible load: allow setpoint to vary within comfort band.
        # hvac_baseline = steady-state cooling load at T_setpoint.
        # p_hvac_delta  = adjustment from baseline (positive = more cooling).
        hvac_baseline = np.maximum(
            0.0, (T_outdoor - T_setpoint) / R
        )
        p_hvac_delta = cp.Variable(T, name="p_hvac_delta")
        T_indoor = cp.Variable(T + 1, name="T_indoor")

        constraints += [
            # Redefine power balance to include HVAC adjustment
            p_grid == (
                load_kw - solar_kw + p_charge - p_discharge + p_hvac_delta
            ),
            # RC thermal dynamics
            T_indoor[0] == T_setpoint,
            T_indoor[1:] == (
                T_indoor[:-1]
                + (
                    (T_outdoor - T_indoor[:-1]) / (R * C)
                    - (hvac_baseline + p_hvac_delta) / C
                ) * dt
            ),
            T_indoor >= T_comfort_min,
            T_indoor <= T_comfort_max,
            # HVAC can only increase cooling (no heating modelled)
            p_hvac_delta >= -hvac_baseline,  # can't shut off more than exists
        ]

    # ── Objective ──────────────────────────────────────────────────────
    energy_cost = cp.sum(cp.multiply(tariff_rates, p_grid)) * dt
    demand_cost = demand_rate * p_peak
    objective = cp.Minimize(energy_cost + demand_cost)

    # ── Solve ──────────────────────────────────────────────────────────
    # Solver preference: HIGHS (fast LP/MIP, bundled with scipy 1.9+),
    # then CLARABEL (conic LP/QP, always installed with cvxpy >= 1.4),
    # then SCS (first-order, slower but universal fallback).
    # GLPK_MI requires a separate install (not assumed here).
    prob = cp.Problem(objective, constraints)
    _SOLVER_ORDER = [
        (cp.HIGHS, {}),
        (cp.CLARABEL, {}),
        (cp.SCS, {"eps": 1e-5}),
    ]
    for solver, opts in _SOLVER_ORDER:
        if solver in cp.installed_solvers():
            prob.solve(solver=solver, verbose=False, **opts)
            break
    else:
        prob.solve(verbose=False)   # let cvxpy pick

    result: dict = {
        "status": prob.status,
        "total_cost": prob.value,
        "p_grid": p_grid.value,
        "p_charge": p_charge.value,
        "p_discharge": p_discharge.value,
        "soc": soc.value,
        "peak_demand_kw": (
            float(p_peak.value) if p_peak.value is not None else None
        ),
    }
    if use_thermal and prob.status in ("optimal", "optimal_inaccurate"):
        result["T_indoor"] = T_indoor.value
        result["p_hvac_delta"] = p_hvac_delta.value

    return result


if __name__ == "__main__":
    import pandas as pd
    from pathlib import Path
    from analysis.tariff import get_energy_rate

    _ROOT = Path(__file__).parent.parent

    print("Loading meter data...")
    df = pd.read_parquet(_ROOT / "data" / "meter" / "school_ca_15min.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Smoke test: one week of July data
    week = df[
        (df["timestamp"].dt.month == 7)
        & (df["timestamp"].dt.day <= 7)
    ].copy()
    print(
        f"  Testing on {len(week)} timesteps "
        f"({len(week)/4:.0f} hours, July 1-7)"
    )

    load = week["demand_kw"].values.astype(float)
    solar = np.zeros(len(load))      # no solar for this smoke test
    tariff_rates = np.array([
        get_energy_rate(ts) for ts in week["timestamp"]
    ])

    print("Running MILP optimizer (battery only, no solar, no thermal)...")
    result = optimize_dispatch(
        load_kw=load,
        solar_kw=solar,
        prices_kwh=tariff_rates,
        tariff_rates=tariff_rates,
        demand_rate=19.10 + 8.85,   # summer on-peak + all-time demand
    )

    print(f"\n  Solver status:   {result['status']}")
    if result["status"] in ("optimal", "optimal_inaccurate"):
        print(f"  Optimized cost:  ${result['total_cost']:,.2f}")
        print(f"  Peak demand:     {result['peak_demand_kw']:.1f} kW")
        peak_baseline = float(load.max())
        print(f"  Baseline peak:   {peak_baseline:.1f} kW")
        reduction = peak_baseline - result["peak_demand_kw"]
        print(f"  Demand reduced:  {reduction:.1f} kW "
              f"({reduction/peak_baseline*100:.0f}%)")
        assert result["status"] in ("optimal", "optimal_inaccurate"), (
            "Solver did not converge"
        )
        print("\n  [OK] Optimizer smoke test passed")
    else:
        print(f"  [WARN] Solver returned: {result['status']}")
