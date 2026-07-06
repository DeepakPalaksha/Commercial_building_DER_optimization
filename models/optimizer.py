"""
MILP dispatch optimizer using cvxpy + HIGHS.

Minimises the electricity bill for a given planning horizon by
optimally dispatching:
  - Battery storage (charge / discharge)
  - Solar PV (curtailment-allowed)
  - HVAC pre-cooling (optional, requires RC model params)

SCE TOU-GS-3 has THREE independent demand charges, each measuring
the peak from a different time window of the same load curve:
  - On-peak demand:  $19.10/kW  (weekdays 14:00-20:00, summer only)
  - Mid-peak demand: $5.80/kW   (weekdays 10:00-14:00 + 20:00-21:00)
  - All-time demand: $8.85/kW   (every interval in the month)

The optimizer models all three via independent peak variables so
battery discharge is directed to the highest-value time window first.

The all-time demand protection constraint is implicit: because
p_grid <= p_peak_all and p_peak_all is in the minimised objective,
the solver will not allow battery charging to create new all-time
peaks (doing so would increase p_peak_all and therefore cost).

See recommendation_tariff_control.md Part 4 and PLAN.md.
"""
import numpy as np
import cvxpy as cp


def optimize_dispatch(
    load_kw: np.ndarray,
    solar_kw: np.ndarray,
    prices_kwh: np.ndarray,
    tariff_rates: np.ndarray,
    on_peak_mask: np.ndarray,
    mid_peak_mask: np.ndarray,
    on_peak_rate: float = 19.10,
    mid_peak_rate: float = 5.80,
    all_time_rate: float = 8.85,
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

    Power balance at each timestep t:
        p_grid[t] = load[t] - solar[t] + p_charge[t] - p_discharge[t]

    Battery SoC dynamics:
        soc[t+1] = soc[t] + (p_charge[t]*eta - p_discharge[t]/eta)*dt

    Three independent demand charge peaks (SCE TOU-GS-3):
        p_peak_on  >= p_grid[t]  for all t in on_peak_mask
        p_peak_mid >= p_grid[t]  for all t in mid_peak_mask
        p_peak_all >= p_grid[t]  for all t (every interval)

    Objective: minimise energy_cost + demand_cost
        energy_cost  = sum(tariff_rates[t] * p_grid[t]) * dt
        demand_cost  = on_peak_rate  * p_peak_on
                     + mid_peak_rate * p_peak_mid
                     + all_time_rate * p_peak_all

    The all-time demand protection is implicit: because p_peak_all
    appears in the objective, the solver avoids charging the battery
    in a way that creates new all-time peaks.

    If thermal control is enabled (T_outdoor, R, C provided):
        HVAC is a flexible load. Pre-cooling is modelled as running
        HVAC below the normal setpoint during off-peak hours.

    Args:
        load_kw:            Baseline building load (kW), shape (T,).
        solar_kw:           Solar PV output (kW), shape (T,).
        prices_kwh:         CAISO LMP ($/kWh), shape (T,). Reserved
                            for V2 DA price co-optimisation.
        tariff_rates:       SCE energy rate ($/kWh), shape (T,).
        on_peak_mask:       Boolean array shape (T,). True at on-peak
                            intervals (summer weekday 14:00-20:00).
        mid_peak_mask:      Boolean array shape (T,). True at mid-peak
                            intervals.
        on_peak_rate:       On-peak demand charge rate ($/kW).
                            Pass 0.0 for winter months (no on-peak).
        mid_peak_rate:      Mid-peak demand charge rate ($/kW).
        all_time_rate:      All-time demand charge rate ($/kW).
        battery_power_kw:   Max charge/discharge power (kW).
        battery_energy_kwh: Usable capacity (kWh).
        efficiency_rt:      Round-trip battery efficiency [0,1].
        soc_min_frac:       Minimum SoC as fraction of capacity.
        soc_max_frac:       Maximum SoC as fraction of capacity.
        T_outdoor:          Outdoor temperature (degF), shape (T,).
                            If None, thermal sub-problem is skipped.
        R:                  Thermal resistance (degF-hr/kWh).
        C:                  Thermal capacitance (kWh/degF).
        T_comfort_min:      Minimum indoor comfort bound (degF).
        T_comfort_max:      Maximum indoor comfort bound (degF).
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
            peak_on_kw     -- optimal on-peak demand (kW)
            peak_mid_kw    -- optimal mid-peak demand (kW)
            peak_all_kw    -- optimal all-time demand (kW)
            peak_demand_kw -- alias for peak_all_kw (backward compat)
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

    # Convert masks to boolean numpy arrays
    on_peak_mask = np.asarray(on_peak_mask, dtype=bool)
    mid_peak_mask = np.asarray(mid_peak_mask, dtype=bool)

    # ── Decision variables ─────────────────────────────────────────
    p_charge = cp.Variable(T, nonneg=True, name="p_charge")
    p_discharge = cp.Variable(T, nonneg=True, name="p_discharge")
    soc = cp.Variable(T + 1, nonneg=True, name="soc")
    p_grid = cp.Variable(T, name="p_grid")

    # Three independent demand-charge peaks (SCE TOU-GS-3)
    p_peak_on  = cp.Variable(nonneg=True, name="p_peak_on")
    p_peak_mid = cp.Variable(nonneg=True, name="p_peak_mid")
    p_peak_all = cp.Variable(nonneg=True, name="p_peak_all")

    # ── Constraints ────────────────────────────────────────────────
    constraints = [
        # Power balance
        p_grid == load_kw - solar_kw + p_charge - p_discharge,
        # Battery energy dynamics
        soc[0] == soc_init_kwh,
        soc[1:] == soc[:-1] + (p_charge * eta - p_discharge / eta) * dt,
        soc >= soc_min_kwh,
        soc <= soc_max_kwh,
        # Battery power limits
        p_charge    <= battery_power_kw,
        p_discharge <= battery_power_kw,
        # All-time demand peak tracks every interval
        p_grid <= p_peak_all,
    ]

    # On-peak demand peak — only relevant when mask has True entries
    if on_peak_mask.any():
        constraints.append(p_grid[on_peak_mask] <= p_peak_on)

    # Mid-peak demand peak — only relevant when mask has True entries
    if mid_peak_mask.any():
        constraints.append(p_grid[mid_peak_mask] <= p_peak_mid)

    if use_thermal:
        # HVAC flexible load: allow setpoint to vary within comfort band.
        hvac_baseline = np.maximum(
            0.0, (T_outdoor - T_setpoint) / R
        )
        p_hvac_delta = cp.Variable(T, name="p_hvac_delta")
        T_indoor = cp.Variable(T + 1, name="T_indoor")

        constraints += [
            p_grid == (
                load_kw - solar_kw + p_charge - p_discharge + p_hvac_delta
            ),
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
            p_hvac_delta >= -hvac_baseline,
        ]

    # ── Objective ──────────────────────────────────────────────────
    energy_cost = cp.sum(cp.multiply(tariff_rates, p_grid)) * dt
    demand_cost = (
        on_peak_rate  * p_peak_on
        + mid_peak_rate * p_peak_mid
        + all_time_rate * p_peak_all
    )
    objective = cp.Minimize(energy_cost + demand_cost)

    # ── Solve ──────────────────────────────────────────────────────
    prob = cp.Problem(objective, constraints)
    _SOLVER_ORDER = [
        (cp.HIGHS,    {}),
        (cp.CLARABEL, {}),
        (cp.SCS,      {"eps": 1e-5}),
    ]
    for solver, opts in _SOLVER_ORDER:
        if solver in cp.installed_solvers():
            prob.solve(solver=solver, verbose=False, **opts)
            break
    else:
        prob.solve(verbose=False)

    def _scalar(v):
        return float(v) if v is not None else None

    result: dict = {
        "status":         prob.status,
        "total_cost":     prob.value,
        "p_grid":         p_grid.value,
        "p_charge":       p_charge.value,
        "p_discharge":    p_discharge.value,
        "soc":            soc.value,
        "peak_on_kw":     _scalar(p_peak_on.value),
        "peak_mid_kw":    _scalar(p_peak_mid.value),
        "peak_all_kw":    _scalar(p_peak_all.value),
        "peak_demand_kw": _scalar(p_peak_all.value),  # backward compat
    }
    if use_thermal and prob.status in ("optimal", "optimal_inaccurate"):
        result["T_indoor"]     = T_indoor.value
        result["p_hvac_delta"] = p_hvac_delta.value

    return result


if __name__ == "__main__":
    import pandas as pd
    from pathlib import Path
    from analysis.tariff import get_energy_rate, get_demand_rates, classify_period

    _ROOT = Path(__file__).parent.parent

    print("Loading meter data...")
    df = pd.read_parquet(
        _ROOT / "data" / "meter" / "school_ca_15min.parquet"
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Smoke test: one week of August data (summer, on-peak applies)
    week = df[
        (df["timestamp"].dt.month == 8)
        & (df["timestamp"].dt.day <= 7)
    ].copy()
    print(
        f"  Testing on {len(week)} timesteps "
        f"({len(week)/4:.0f} hours, August 1-7)"
    )

    load = week["demand_kw"].values.astype(float)
    solar = np.zeros(len(load))
    tariff_rates = np.array([
        get_energy_rate(ts) for ts in week["timestamp"]
    ])
    on_peak_mask = np.array([
        classify_period(ts) == "on_peak" for ts in week["timestamp"]
    ])
    mid_peak_mask = np.array([
        classify_period(ts) == "mid_peak" for ts in week["timestamp"]
    ])

    dr = get_demand_rates(8)
    print(
        "Running MILP optimizer "
        "(3-demand, battery only, no solar, no thermal)..."
    )
    result = optimize_dispatch(
        load_kw=load,
        solar_kw=solar,
        prices_kwh=tariff_rates,
        tariff_rates=tariff_rates,
        on_peak_mask=on_peak_mask,
        mid_peak_mask=mid_peak_mask,
        on_peak_rate=dr.get("on_peak_kw", 19.10),
        mid_peak_rate=dr.get("mid_peak_kw", 5.80),
        all_time_rate=dr.get("all_time_kw", 8.85),
    )

    print(f"\n  Solver status:    {result['status']}")
    if result["status"] in ("optimal", "optimal_inaccurate"):
        print(f"  Optimized cost:   ${result['total_cost']:,.2f}")
        print(f"  Peak on-peak:     {result['peak_on_kw']:.1f} kW")
        print(f"  Peak mid-peak:    {result['peak_mid_kw']:.1f} kW")
        print(f"  Peak all-time:    {result['peak_all_kw']:.1f} kW")
        peak_baseline = float(load.max())
        print(f"  Baseline peak:    {peak_baseline:.1f} kW")
        on_peak_base = float(load[on_peak_mask].max())
        reduction = on_peak_base - result["peak_on_kw"]
        print(
            f"  On-peak reduced:  {reduction:.1f} kW "
            f"({reduction/on_peak_base*100:.0f}%)"
        )
        print("\n  [OK] 3-demand optimizer smoke test passed")
    else:
        print(f"  [WARN] Solver returned: {result['status']}")
